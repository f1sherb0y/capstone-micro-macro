"""Independent durable A07 notification outbox; never invokes signing or result submission."""
from copy import deepcopy
from dataclasses import dataclass, fields
import json
from typing import Callable, Literal

from pydantic import Field, model_validator

from integration.module_host import module_factory_descriptor
from integration.task_continuation import observation_signal_matches
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, ResumeCondition, StrictRecord, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.government_decision_objects import (
    GovDecisionCaseView, GovDecisionBasisView, GovDecisionCommandView, GovDecisionEffectView,
    GovFormalDecisionView, GovDecisionNotificationView,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.government_decision_conditions import _QUERY_CODE, _UNRESOLVED_CODE
from src.coordination.government_decision_notification import NOTIFICATION_CODE, GovernmentDecisionNotificationSnapshot
from src.coordination.government_decision_query import GovernmentDecisionQueryRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.organization.registry import scope_covers


class GovernmentDecisionNotificationSettings(StrictRecord):
    binding_id: TextId
    version: TextId
    macro_version: TextId


class GovernmentDecisionNotificationRequest(StrictRecord):
    notification_id: Digest
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    decision_ref: ref_type('Decision')
    command_ref: ref_type('DecisionCommand')
    original_operation_id: TextId
    business_key: TextId
    draft_sha256: Digest
    recipient_id: TextId
    binding_id: TextId
    binding_version: TextId
    macro_version: TextId


class GovernmentDecisionNotificationReceipt(StrictRecord):
    notification_id: Digest
    run_id: TextId
    organization_id: TextId
    decision_ref: ref_type('Decision')
    recipient_id: TextId
    observed_at: TimePoint
    status: Literal['absent', 'sent', 'delivered', 'unknown', 'failed']
    notification: GovDecisionNotificationView | None
    retry_safe: bool = False
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)
    original_reply: dict

    @model_validator(mode='after')
    def actual_status(self):
        if self.retry_safe and self.status != 'absent':
            raise ValueError('Notification retry requires definitive absence and proof that the prior send has ended')
        if self.status == 'absent' and self.notification is not None:
            raise ValueError('Absent notification cannot carry an existing delivery record')
        if self.status in {'sent', 'delivered', 'failed'} and self.notification is None:
            raise ValueError('Known notification disposition requires its actual native record')
        if self.notification is not None:
            row = self.notification
            if (row.decision_ref != self.decision_ref or row.recipient_id != self.recipient_id
                    or row.status != self.status or row.available_at.clock_ref != self.observed_at.clock_ref
                    or row.available_at.offset > self.observed_at.offset):
                raise ValueError('Notification reply substitutes its actual record, recipient or observation time')
            if row.status == 'delivered':
                if (row.delivered_at is None or row.delivered_at.clock_ref != self.observed_at.clock_ref
                        or row.delivered_at.offset > row.available_at.offset or not row.evidence_refs):
                    raise ValueError('Delivered notification requires observed actual delivery time and evidence')
            elif row.delivered_at is not None:
                raise ValueError('Undelivered notification cannot carry an actual delivery time')
        if len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError('Notification reply duplicates observation evidence')
        return self


@dataclass(frozen=True)
class GovernmentDecisionNotificationCallbacks:
    """Native endpoints, sender/read authorization and actual reply authentication.

    send/request and query/request retain the same notification_id. Validators
    receive request, selected and the persisted record. validate_receipt additionally
    receives raw and operation, and returns a correlated receipt preserving raw.
    retry_safe requires authoritative absence and proof that all old sends are
    terminal; a timeout, unknown delivery or a failed reply alone is insufficient.
    """
    send: Callable
    query: Callable
    validate_send: Callable
    validate_query: Callable
    validate_receipt: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Decision notifications require actual send/query endpoints and independent validators')


class GovernmentDecisionNotificationTransport:
    VERSION = 'government-decision-notification-transport.v1'
    TABLE = 'government_decision_notifications'
    METADATA_KEY = 'government_decision_notification_transport'
    SNAPSHOT_TYPE = GovernmentDecisionNotificationSnapshot

    @staticmethod
    def _reader_type():
        from integration.government_decision_reader import GovernmentDecisionReader
        return GovernmentDecisionReader

    def __init__(self, *, store, reader, dispatcher, settings, callbacks, read_guard, validate_relation):
        if (self.TABLE not in {'government_decision_notifications', 'government_transition_notifications'}
                or store.path is None or type(reader) is not self._reader_type() or reader.snapshots.store is not store
                or dispatcher.journal.store is not store or not isinstance(callbacks, GovernmentDecisionNotificationCallbacks)
                or not callable(read_guard) or not callable(validate_relation)):
            raise ValueError('Decision notifications require original persistent A07 sources, inbox and explicit native endpoints')
        self.store, self.reader, self.dispatcher = store, reader, dispatcher
        self.settings = GovernmentDecisionNotificationSettings.model_validate(settings).model_copy(deep=True)
        self.callbacks, self.read_guard, self.validate_relation = callbacks, read_guard, validate_relation
        self._original = (store, reader, dispatcher, callbacks, read_guard, validate_relation,
            dispatcher.journal, dispatcher.inbox, dispatcher.project_signal)
        self._declared = self._configuration()
        self._key = self.METADATA_KEY
        with store._transaction():
            store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.TABLE} (notification_id TEXT PRIMARY KEY, record TEXT NOT NULL)')
            prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original decision notification endpoint/configuration changed')

    def _configuration(self):
        return dict(schema_version=self.VERSION, run_id=self.store.run_id, settings=self.settings.model_dump(mode='json'),
            table=self.TABLE, metadata_key=self.METADATA_KEY,
            snapshot_type=self.SNAPSHOT_TYPE.__module__ + '.' + self.SNAPSHOT_TYPE.__qualname__,
            reader=self.reader.configuration_evidence(),
            code=module_factory_descriptor(type(self).execute, self.VERSION),
            select=module_factory_descriptor(type(self)._select, 'select_notification'),
            project_signal=module_factory_descriptor(self.dispatcher.project_signal, 'project_signal'),
            callbacks={item.name: module_factory_descriptor(getattr(self.callbacks, item.name), item.name) for item in fields(self.callbacks)},
            read_guard=module_factory_descriptor(self.read_guard, 'read_guard'),
            validate_relation=module_factory_descriptor(self.validate_relation, 'validate_relation'))

    def _check(self):
        if (any(current is not original for current, original in zip(
                (self.store, self.reader, self.dispatcher, self.callbacks, self.read_guard, self.validate_relation,
                    self.dispatcher.journal, self.dispatcher.inbox, self.dispatcher.project_signal), self._original))
                or self.reader.snapshots.store is not self.store or self.dispatcher.journal.store is not self.store
                or self._key != self.METADATA_KEY or type(self.reader) is not self._reader_type()
                or self._configuration() != self._declared):
            raise TaskConflict('Original decision notification components or declarations changed')
        with self.store._lock:
            prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None or json.loads(prior[0]) != self._declared:
                raise TaskConflict('Decision notification binding evidence changed')

    def _record(self, notification_id):
        row = self.store._db.execute(f'SELECT record FROM {self.TABLE} WHERE notification_id=?', (notification_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def _save(self, notification_id, record):
        self.store._db.execute(f'INSERT OR REPLACE INTO {self.TABLE} VALUES (?,?)',
            (notification_id, canonical(record)))

    def _select(self, identity, signal, recipient_id):
        signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
        if (identity.action_id != 'GOV-A07' or identity.role != 'Government' or identity.purpose != 'action'
                or identity.run_id != self.store.run_id or signal.run_id != identity.run_id
                or signal.organization_id != identity.organization_id):
            raise TaskConflict('Decision notification replaces original action/run/recipient')
        source = self.store.get(identity)
        if source['state'] != 'waiting_input' or len(source['conditions']) != 1 or self.store.continuation(identity) is not None:
            raise TaskConflict('Decision notification requires original pending formal-fact wait without a signing successor')
        condition = ResumeCondition.model_validate(source['conditions'][0])
        query_wait = condition.condition_code in {_QUERY_CODE, _UNRESOLVED_CODE}
        if (condition.condition_code not in {NOTIFICATION_CODE, _QUERY_CODE, _UNRESOLVED_CODE}
                or condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in condition.object_refs) != (('DecisionCommand',) if query_wait else ('Decision',))
                or not self.dispatcher.journal._matches(condition, signal)):
            raise TaskConflict('Decision notification changes original formal-fact wait or signal')
        events = [row for row in self.dispatcher.inbox.for_organization(run_id=identity.run_id,
            organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
        if len(events) != 1:
            raise TaskConflict('Decision notification requires original persisted recipient feedback')
        projected = self.dispatcher.project_signal(deepcopy(events[0]))
        if not observation_signal_matches(events[0], projected, expected=signal):
            raise TaskConflict('Decision notification replaces persisted feedback projection')
        selected = self.reader(ConditionCheck(deepcopy(source), condition, signal), notification_transport=True)
        reading, context = selected.reading, selected.context
        try:
            raw, old_context = selected.original_action_input, selected.original_context
            if (old_context is None or task_digest(raw) != identity.input_sha256
                    or task_digest(old_context.model_dump(mode='json')) != identity.context_sha256
                    or selected.action_input != raw or context.operation_id != old_context.operation_id):
                raise TaskConflict('Decision notification replaces original signing invocation or input')
            rows = []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or not scope_covers(context.scope, row.scope):
                    raise TaskConflict('Decision notification lacks exact original scoped sources')
                rows.append(row)
                return row

            snapshot = GovernmentDecisionNotificationSnapshot.model_validate(selected.notification_snapshot)
            case = read(ref_type('RegulatoryCase').model_validate(raw['case_ref']), GovDecisionCaseView)
            basis = read(ref_type('DecisionBasis').model_validate(raw['decision_basis_ref']), GovDecisionBasisView)
            command = read(basis.command_ref, GovDecisionCommandView)
            effect = read(basis.draft.effect_rule_ref, GovDecisionEffectView)
            decision, now = snapshot.decision, context.business_time
            if (snapshot.source_identity_sha256 != task_digest(source['identity']) or snapshot.run_id != identity.run_id
                    or snapshot.organization_id != identity.organization_id or snapshot.as_of != now
                    or old_context.business_time.clock_ref != now.clock_ref or old_context.business_time.offset > now.offset
                    or case.organization_id != identity.organization_id or decision.case_ref != case.ref
                    or decision.submission_ref != command.submission_ref or decision.command_ref != command.ref
                    or command.case_ref != case.ref or command.decision_basis_ref != basis.ref
                    or command.operation_id != old_context.operation_id or command.draft_sha256 != content_digest(basis.draft)
                    or command.official_decision_ref not in (None, decision.ref)
                    or decision.business_key != command.business_key or decision.draft_sha256 != command.draft_sha256
                    or decision.signer_actor_id != basis.signer_actor_id or decision.signer_function_ref != basis.signer_function_ref
                    or not scope_covers(context.scope, decision.scope) or decision.available_at.clock_ref != now.clock_ref
                    or decision.available_at.offset > now.offset or not effect.modeled
                    or effect.decision_rule_ref != basis.decision_rule_ref or effect.outcome != basis.draft.outcome):
                raise TaskConflict('Decision notification substitutes the actual original signed fact, terms or signer')
            recipients = set(basis.draft.notification_recipient_ids)
            if (recipient_id not in recipients or case.applicant_id not in recipients
                    or len(recipients) != len(basis.draft.notification_recipient_ids)
                    or recipients != set(effect.notification_recipient_ids)
                    or len(recipients) != len(effect.notification_recipient_ids)):
                raise TaskConflict('Decision notification changes authorized original recipients')
            decisions = [read(ref, GovFormalDecisionView) for ref in case.decision_refs]
            matching = [row for row in decisions if row.business_key == command.business_key]
            if (len({ref.key()[:2] for ref in case.decision_refs}) != len(case.decision_refs)
                    or any(row.case_ref != case.ref for row in decisions)):
                raise TaskConflict('Decision notification duplicates or borrows original formal history')
            query = None
            if query_wait:
                if (tuple(condition.object_refs) != (command.ref,) or matching or command.official_decision_ref is not None
                        or command.lookup_status == 'present' or command.status == 'recorded'
                        or condition.condition_code == _QUERY_CODE and (command.status not in {'submitted_unknown', 'failed'} or command.lookup_status == 'absent')
                        or condition.condition_code == _UNRESOLVED_CODE and (command.lookup_status != 'unknown' or command.status in {'submitted_unknown', 'failed'})
                        or selected.command_query is None):
                    raise TaskConflict('Decision notification requires original uncertain-command gate and actual found-fact query')
                query = GovernmentDecisionQueryRecord.model_validate(selected.command_query)
                if (query.source_identity_sha256 != task_digest(source['identity']) or query.run_id != identity.run_id
                        or query.organization_id != identity.organization_id or query.command_ref != command.ref
                        or query.operation_id != command.operation_id or query.business_key != command.business_key
                        or query.draft_sha256 != command.draft_sha256 or query.result != 'present'
                        or query.official_decision_ref != decision.ref or query.queried_at != now):
                    raise TaskConflict('Decision notification query does not authenticate this original found decision')
            elif len(matching) != 1 or matching[0].ref != decision.ref or tuple(condition.object_refs) != (decision.ref,):
                raise TaskConflict('Decision notification changes the original recorded-decision wait')
            actual = {row.ref.key()[:2]: row for row in snapshot.notifications}
            if len(actual) != len(snapshot.notifications):
                raise TaskConflict('Decision notification duplicates a physical history record')
            for row in snapshot.notifications:
                if (row.recipient_id not in recipients or not scope_covers(context.scope, row.scope)
                        or row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or row.status == 'delivered' and (row.delivered_at is None or row.delivered_at.clock_ref != now.clock_ref
                            or row.delivered_at.offset > row.available_at.offset or row.delivered_at.offset < decision.available_at.offset)
                        or row.status != 'delivered' and row.delivered_at is not None):
                    raise TaskConflict('Decision notification loses actual recipient, status or delivery time')
            if matching:
                original = matching[0]
                for field in ('ref', 'case_ref', 'submission_ref', 'command_ref', 'business_key', 'draft_sha256',
                        'signer_actor_id', 'signer_function_ref', 'scope', 'available_at', 'effective_window'):
                    if getattr(original, field) != getattr(decision, field):
                        raise TaskConflict('Decision notification rewrites original signed content')
                for ref in original.notification_refs:
                    old = read(ref, GovDecisionNotificationView)
                    current = actual.get(ref.key()[:2])
                    if (current is None or current.recipient_id != old.recipient_id
                            or old.status == 'delivered' and (current.status != 'delivered' or current.delivered_at != old.delivered_at)):
                        raise TaskConflict('Decision notification drops or rewrites previous actual delivery history')
            rows.extend([decision, *snapshot.notifications])
            proof_refs = [*snapshot.evidence_refs, *(query.evidence_refs if query is not None else ())]
            proof_refs.extend(ref for row in rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Decision notification requires observed original signing, lookup and history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            plan = dict(original_action_input=deepcopy(raw), original_context=old_context.model_dump(mode='json'),
                snapshot=snapshot.model_dump(mode='json'), original_command=command.model_dump(mode='json'),
                command_query=None if query is None else query.model_dump(mode='json'),
                decision_sources=deepcopy(selected.decision_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                evidence=list(evidence.values()), recipient_id=recipient_id)
            if self.validate_relation(source_identity=deepcopy(source['identity']), condition_code=condition.condition_code,
                    notification_transport=True, plan=deepcopy(plan), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Decision notification lacks native actual signed fact, complete history and original duty authentication')
            request = GovernmentDecisionNotificationRequest(notification_id=task_digest([
                identity.run_id, identity.organization_id, list(decision.ref.key()[:2]), recipient_id]),
                source_identity_sha256=task_digest(source['identity']), run_id=identity.run_id, organization_id=identity.organization_id,
                decision_ref=decision.ref, command_ref=command.ref, original_operation_id=command.operation_id,
                business_key=command.business_key, draft_sha256=command.draft_sha256, recipient_id=recipient_id,
                binding_id=self.settings.binding_id, binding_version=self.settings.version, macro_version=self.settings.macro_version)
            reading.recheck()
            return request, selected, source
        except BaseException:
            reading.recheck()
            raise

    def execute(self, identity, *, signal, recipient_id):
        return self._dispatch(identity, signal=signal, recipient_id=recipient_id, query_only=False)

    def recover(self, identity, *, signal, recipient_id):
        return self._dispatch(identity, signal=signal, recipient_id=recipient_id, query_only=True)

    def _dispatch(self, identity, *, signal, recipient_id, query_only):
        self._check()
        identity = TaskIdentity(**identity.as_dict())
        with self.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            request, selected, source = self._select(identity, signal, recipient_id)
            try:
                with self.store._transaction():
                    record = self._record(request.notification_id)
                    if record is None:
                        record = dict(schema_version=self.VERSION, request=request.model_dump(mode='json'),
                            state='prepared', revision=0, receipts=[], attempts=[], last_error=None)
                        self._save(request.notification_id, record)
                    elif record['request'] != request.model_dump(mode='json'):
                        raise TaskConflict('Original notification identity/decision/content/binding changed')
                history = self.SNAPSHOT_TYPE.model_validate(selected.notification_snapshot).notifications
                already_known = any(row.recipient_id == recipient_id and
                    (row.status != 'failed' or record['state'] != 'absence_confirmed') for row in history)
                operation = 'query' if query_only or already_known or record['state'] not in {'prepared', 'absence_confirmed'} else 'send'
                validator = self.callbacks.validate_send if operation == 'send' else self.callbacks.validate_query
                if validator(request=request.model_copy(deep=True), selected=selected, record=deepcopy(record)) is not True:
                    raise TaskConflict('Decision notification lacks current independent send/read authorization and retry safety')
                self._check()
                selected.reading.recheck()
                if self.store.get(identity) != source or self.store.continuation(identity) is not None:
                    raise TaskConflict('Original decision wait changed before notification transport')
                if record['state'] == 'delivered':
                    return deepcopy(record)
                with self.store._transaction():
                    current = self._record(request.notification_id)
                    if current != record:
                        raise TaskConflict('Original notification changed before endpoint claim')
                    record['attempts'].append(dict(operation=operation, at=selected.context.business_time.model_dump(mode='json')))
                    record['revision'] += 1
                    record['state'] = 'send_unknown' if operation == 'send' else 'query_unknown'
                    self._save(request.notification_id, record)
                transport = self.callbacks.send if operation == 'send' else self.callbacks.query
                try:
                    raw = transport(request.model_copy(deep=True))
                except Exception as error:
                    with self.store._transaction():
                        if self._record(request.notification_id) != record:
                            raise TaskConflict('Notification state changed during uncertain endpoint call') from error
                        record['last_error'] = dict(operation=operation, exception_type=type(error).__name__)
                        record['revision'] += 1
                        self._save(request.notification_id, record)
                    return deepcopy(record)
                receipt = GovernmentDecisionNotificationReceipt.model_validate(self.callbacks.validate_receipt(
                    request=request.model_copy(deep=True), raw=deepcopy(raw), operation=operation,
                    selected=selected, record=deepcopy(record)))
                if (receipt.original_reply != raw or receipt.notification_id != request.notification_id
                        or receipt.run_id != request.run_id or receipt.organization_id != request.organization_id
                        or receipt.decision_ref != request.decision_ref or receipt.recipient_id != request.recipient_id
                        or receipt.observed_at != selected.context.business_time or operation == 'send' and receipt.retry_safe):
                    raise TaskConflict('Decision notification reply replaces original correlation, reply or query evidence')
                self._check()
                selected.reading.recheck()
                with self.store._transaction():
                    if self._record(request.notification_id) != record:
                        raise TaskConflict('Notification state changed while validating actual endpoint reply')
                    if receipt.status != 'absent':
                        record['state'] = receipt.status
                    elif operation == 'query' and receipt.retry_safe:
                        record['state'] = 'absence_confirmed'
                    elif record['state'] == 'prepared':
                        record['state'] = 'unknown'
                    record['receipts'].append(receipt.model_dump(mode='json'))
                    record['last_error'] = None
                    record['revision'] += 1
                    self._save(request.notification_id, record)
                return deepcopy(record)
            finally:
                selected.reading.recheck()
                self._check()
