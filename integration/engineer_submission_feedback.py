"""Own-Engineer actual feedback correlated with original submission and authorized sources."""
from copy import deepcopy
import json
from typing import Annotated, Literal

from pydantic import Field

from integration.engineer_role_contract_host import _ACTIONS
from integration.engineer_submission_host import EngineerSubmissionHost
from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class EngineerFeedbackObservation(StrictRecord):
    schema_version: Literal['engineer-feedback-observation.v1']
    native_event_id: TextId
    target_action_id: TextId
    observed_at: TimePoint
    available_at: TimePoint
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]


class EngineerSubmissionFeedback:
    """Store independently verified actual feedback, without producing native facts.

    The application supplies a separate currently authorized formal reading
    and observed event/source relation. The existing inbox persists only own
    visible source snapshots and original task/result/receipt hashes. Recording
    creates neither a successor task nor an accepted business effect.
    Feedback preserves the original Engineer result and receipt identity; it
    does not approve professional design, sign conclusions, grant use rights,
    apply learning or training,
    confirm fees or cash, release resources or erase service obligations.
    The application holds the current source/authorization guard for reading.

    A new case/project scope requires the actual application's independently
    evidenced relation validation. It is never inferred from native acceptance.
    """
    VERSION = 'engineer-submission-feedback.v2'

    def __init__(self, *, host, inbox, version, validate_relation, validate_read):
        if (not isinstance(host, EngineerSubmissionHost) or not isinstance(inbox, ObservationInbox)
                or inbox.path is None or inbox.run_id != host.store.run_id
                or inbox.organization_ids != host.store.organization_ids
                or not isinstance(version, str) or not version.strip()
                or not callable(validate_relation) or not callable(validate_read)):
            raise ValueError('Engineer feedback requires original host, persistent own inbox and explicit relation/read validators')
        self.host, self.inbox, self.version = host, inbox, version
        self.validate_relation, self.validate_read = validate_relation, validate_read
        self._components = (host, inbox, validate_relation, validate_read)
        self._declared = self._configuration()
        self._key = 'engineer_submission_feedback:' + host.configuration.host_id
        with host.store._transaction():
            prior = host.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                host.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original engineer feedback configuration changed; explicit review required')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.host.store.run_id, 'version': self.version,
            'host_sha256': task_digest(self.host._declared), 'inbox_path': str(self.inbox.path),
            'code': module_factory_descriptor(type(self).record, self.VERSION),
            'validate_relation': module_factory_descriptor(self.validate_relation, 'validate_relation'),
            'validate_read': module_factory_descriptor(self.validate_read, 'validate_read')}

    def _check(self):
        current = (self.host, self.inbox, self.validate_relation, self.validate_read)
        if any(actual is not original for actual, original in zip(current, self._components)):
            raise TaskConflict('Engineer feedback substituted its original components')
        self.host._check()
        if (self._configuration() != self._declared or self.inbox.run_id != self.host.store.run_id
                or self.inbox.organization_ids != self.host.store.organization_ids):
            raise TaskConflict('Engineer feedback substituted original host, inbox or validation boundary')
        with self.host.store._lock:
            prior = self.host.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None or json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original engineer feedback configuration evidence changed')

    def _reading(self, context, reading):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or context.run_id != self.host.store.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id not in _ACTIONS
                or context.execution_mode == 'offline_fixture'
                or reading._resolver.source_mode != 'formal' or reading._organizations.run_id != context.run_id
                or reading._role != 'Engineer'):
            raise TaskConflict('Engineer feedback requires a current own-Engineer formal action reading')
        reading.check_method_context(context, context.contract_ref.id)
        reading.recheck()
        return context

    def record(self, identity, *, context, reading, observation):
        identity = TaskIdentity(**identity.as_dict())
        context = self._reading(context, reading)
        observation = EngineerFeedbackObservation.model_validate(observation).model_copy(deep=True)
        if (reading.organization_id != identity.organization_id or observation.target_action_id != context.contract_ref.id
                or len({ref.key() for ref in observation.source_refs}) != len(observation.source_refs)
                or len({ref.key() for ref in observation.relation_evidence_refs}) != len(observation.relation_evidence_refs)
                or observation.native_evidence_ref.key() in {ref.key() for ref in observation.relation_evidence_refs}):
            raise TaskConflict('Engineer feedback changes original recipient/target or independent source-relation identities')
        receipt = self.host.read_receipt(identity)
        snapshot = self.host.workers[identity.action_id].snapshots.get(identity)
        original = ActionContext.model_validate(snapshot['context'])
        times = [original.business_time, observation.observed_at, observation.available_at, context.business_time]
        # Scope may change through an actual case/project relation. The mandatory
        # application validator below sees both original and current contexts,
        # native receipt and independent observed evidence before persistence.
        if (any(point.clock_ref != context.business_time.clock_ref for point in times)
                or any(left.offset > right.offset for left, right in zip(times, times[1:]))):
            raise TaskConflict('Engineer feedback changes original clock or actual event availability chronology')
        try:
            evidence = []
            for ref in [observation.native_evidence_ref, *observation.relation_evidence_refs]:
                source = reading.resolve(ref)
                if (not isinstance(source, EvidenceRecord) or source.basis_kind != 'observed'
                        or source.source_kind == 'synthetic'
                        or source.effective_window is not None and not source.effective_window.contains(context.business_time)):
                    raise TaskConflict('Engineer feedback requires independent currently available observed evidence')
                evidence.append(source.model_dump(mode='json'))
            if evidence[0]['content_hash'] != observation.native_source_sha256:
                raise TaskConflict('Engineer feedback native observation changes its original source digest')
            sources = [{'ref': ref.model_dump(mode='json'), 'projection': reading.resolve(ref).model_dump(mode='json')}
                for ref in observation.source_refs]
            if self.validate_relation(identity=TaskIdentity(**identity.as_dict()), receipt=deepcopy(receipt),
                    snapshot=deepcopy(snapshot), observation=observation.model_copy(deep=True),
                    sources=deepcopy(sources), evidence=deepcopy(evidence), context=context.model_copy(deep=True),
                    reading=reading) is not True:
                raise TaskConflict('Engineer feedback requires actual receipt/event/source/recipient relation validation')
            if task_digest(self.host.read_receipt(identity)) != task_digest(receipt):
                raise TaskConflict('Original engineer submission receipt changed during actual feedback validation')
            reading.recheck()
            self._check()
            record = {'schema_version': self.VERSION, 'identity': identity.as_dict(), 'receipt': receipt,
                'context': context.model_dump(mode='json'), 'observation': observation.model_dump(mode='json'),
                'sources': sources, 'source_evidence': evidence, 'configuration_sha256': task_digest(self._declared)}
            record['record_sha256'] = task_digest(record)
            # Separate from a native inbox event; its original ID remains in
            # observation. One original correlation is immutable and deduplicated.
            event_id = 'engineer-feedback:' + task_digest([identity.key, observation.native_event_id, observation.target_action_id])
            return self.inbox.deliver(run_id=identity.run_id, event_id=event_id,
                organization_id=identity.organization_id, payload=record)
        finally:
            reading.recheck()

    def read(self, *, context, reading):
        context = self._reading(context, reading)
        records = []
        for row in self.inbox.for_organization(run_id=context.run_id, organization_id=reading.organization_id):
            if not row['event_id'].startswith('engineer-feedback:'):
                continue
            record = row['payload']
            if (not isinstance(record, dict) or set(record) != {'schema_version', 'identity', 'receipt',
                    'context', 'observation', 'sources', 'source_evidence', 'configuration_sha256', 'record_sha256'}):
                raise TaskConflict('Saved Engineer feedback changes its closed record schema')
            identity = TaskIdentity(**record['identity'])
            observation = EngineerFeedbackObservation.model_validate(record['observation'])
            saved_context = ActionContext.model_validate(record['context'])
            expected_id = 'engineer-feedback:' + task_digest([identity.key, observation.native_event_id, observation.target_action_id])
            if (record.get('schema_version') != self.VERSION or row['event_id'] != expected_id
                    or identity.run_id != context.run_id or identity.organization_id != reading.organization_id
                    or identity.role != 'Engineer' or identity.purpose != 'action' or identity.action_id not in self.host.routes
                    or observation.target_action_id not in _ACTIONS or saved_context.run_id != identity.run_id
                    or saved_context.contract_ref.kind != 'ActionContract'
                    or saved_context.contract_ref.id != observation.target_action_id
                    or saved_context.execution_mode == 'offline_fixture'
                    or record.get('configuration_sha256') != task_digest(self._declared)
                    or record.get('record_sha256') != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
                raise TaskConflict('Saved engineer feedback changed original event/recipient/configuration or digest')
            if observation.target_action_id == context.contract_ref.id:
                records.append(deepcopy(record))
        if self.validate_read(context=context.model_copy(deep=True), reading=reading, records=deepcopy(records)) is not True:
            raise TaskConflict('Engineer feedback history requires current recipient/scope visibility validation')
        reading.recheck()
        self._check()
        return records
