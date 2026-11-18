"""Independent GOV-A09 change notification transport using the durable notification outbox."""
from copy import deepcopy
from pydantic import TypeAdapter

from integration.government_decision_notification_transport import (
    GovernmentDecisionNotificationTransport, GovernmentDecisionNotificationRequest,
)
from integration.task_continuation import observation_signal_matches
from src.actions.contracts.common import EvidenceRecord, ResumeCondition, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_transition_objects import (
    GovTransitionDecisionView, GovTransitionRuleView, GovChangeBasisView, GovChangeEffectView,
    GovDecisionCommandView, GovDecisionNotificationView,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.government_transition_conditions import _CODE
from src.coordination.government_transition_notification import NOTIFICATION_CODE, GovernmentTransitionNotificationSnapshot
from src.coordination.government_decision_query import GovernmentDecisionQueryRecord
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


class GovernmentTransitionNotificationRequest(GovernmentDecisionNotificationRequest):
    prior_decision_ref: ref_type('Decision')


class GovernmentTransitionNotificationTransport(GovernmentDecisionNotificationTransport):
    VERSION = 'government-transition-notification-transport.v1'
    TABLE = 'government_transition_notifications'
    METADATA_KEY = 'government_transition_notification_transport'
    SNAPSHOT_TYPE = GovernmentTransitionNotificationSnapshot

    @staticmethod
    def _reader_type():
        from integration.government_transition_reader import GovernmentTransitionReader
        return GovernmentTransitionReader

    def _select(self, identity, signal, recipient_id):
        signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
        if (identity.action_id != 'GOV-A09' or identity.role != 'Government' or identity.purpose != 'action'
                or identity.run_id != self.store.run_id or signal.run_id != identity.run_id
                or signal.organization_id != identity.organization_id):
            raise TaskConflict('Change notification replaces original action/run/recipient')
        source = self.store.get(identity)
        if source['state'] != 'waiting_input' or len(source['conditions']) != 1 or self.store.continuation(identity) is not None:
            raise TaskConflict('Change notification requires original pending formal-fact wait without a signing successor')
        condition = ResumeCondition.model_validate(source['conditions'][0])
        query_wait = condition.condition_code == _CODE
        if (condition.condition_code not in {NOTIFICATION_CODE, _CODE}
                or condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in condition.object_refs) != (('DecisionCommand',) if query_wait else ('Decision',))
                or not self.dispatcher.journal._matches(condition, signal)):
            raise TaskConflict('Change notification changes original formal-fact wait or signal')
        events = [row for row in self.dispatcher.inbox.for_organization(run_id=identity.run_id,
            organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
        if len(events) != 1:
            raise TaskConflict('Change notification requires original persisted recipient feedback')
        projected = self.dispatcher.project_signal(deepcopy(events[0]))
        if not observation_signal_matches(events[0], projected, expected=signal):
            raise TaskConflict('Change notification replaces persisted feedback projection')
        selected = self.reader(ConditionCheck(deepcopy(source), condition, signal), notification_transport=True)
        reading, context = selected.reading, selected.context
        try:
            raw, old_context = selected.original_action_input, selected.original_context
            scope = TypeAdapter(ScopeRef).validate_python(raw['scope'])
            if (old_context is None or task_digest(raw) != identity.input_sha256
                    or task_digest(old_context.model_dump(mode='json')) != identity.context_sha256
                    or selected.action_input != raw or context.operation_id != old_context.operation_id):
                raise TaskConflict('Change notification replaces original signing invocation or input')
            rows = []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('Change notification lacks exact original scoped sources')
                rows.append(row)
                return row

            snapshot = GovernmentTransitionNotificationSnapshot.model_validate(selected.notification_snapshot)
            prior = read(ref_type('Decision').model_validate(raw['prior_decision_ref']), GovTransitionDecisionView)
            rule = read(ref_type('Rule').model_validate(raw['transition_rule_ref']), GovTransitionRuleView)
            if rule.decision_basis_ref is None:
                raise TaskConflict('Change notification loses original change basis')
            basis = read(rule.decision_basis_ref, GovChangeBasisView)
            command = read(basis.command_ref, GovDecisionCommandView)
            effect = read(basis.draft.effect_rule_ref, GovChangeEffectView)
            decision, now = snapshot.decision, context.business_time
            if (snapshot.source_identity_sha256 != task_digest(source['identity']) or snapshot.run_id != identity.run_id
                    or snapshot.organization_id != identity.organization_id or snapshot.as_of != now
                    or snapshot.prior_decision_ref != prior.ref or not scope_covers(prior.scope, scope)
                    or prior.history_coverage != 'complete' or prior.as_of != old_context.business_time
                    or rule.purpose != 'transition' or rule.choice not in {'renew', 'suspend', 'revoke', 'restore'}
                    or rule.organization_id != identity.organization_id or rule.prior_decision_ref != prior.ref
                    or basis.transition_rule_ref != rule.ref or basis.draft.outcome != rule.choice
                    or basis.draft.prior_decision_ref != prior.ref or basis.draft.case_ref != prior.case_ref
                    or basis.draft.decision_basis_ref != basis.ref or basis.draft.covered_scope != scope
                    or basis.draft.submission_ref.model_dump(mode='json') != raw['affected_submission_ref']
                    or decision.organization_id != identity.organization_id or decision.applicant_id != prior.applicant_id
                    or decision.ref.key()[:2] == prior.ref.key()[:2] or decision.outcome != basis.draft.outcome
                    or decision.permit_ref != prior.permit_ref or decision.conditions != basis.draft.conditions
                    or old_context.business_time.clock_ref != now.clock_ref or old_context.business_time.offset > now.offset
                    or prior.organization_id != identity.organization_id or decision.case_ref != prior.case_ref
                    or decision.submission_ref != command.submission_ref or decision.command_ref != command.ref
                    or command.submission_ref != basis.draft.submission_ref
                    or command.case_ref != prior.case_ref or command.decision_basis_ref != basis.ref
                    or command.operation_id != old_context.operation_id or command.draft_sha256 != content_digest(basis.draft)
                    or command.official_decision_ref not in (None, decision.ref)
                    or decision.business_key != command.business_key or decision.draft_sha256 != command.draft_sha256
                    or decision.signer_actor_id != old_context.actor_id or decision.signer_function_ref != old_context.function_ref
                    or not scope_covers(decision.scope, scope) or decision.available_at.clock_ref != now.clock_ref
                    or decision.available_at.offset > now.offset
                    or effect.decision_basis_ref != basis.ref or effect.outcome != basis.draft.outcome
                    or effect.expiry_rule_ref != basis.draft.expiry_rule_ref
                    or {ref.key() for ref in effect.next_procedure_refs} != {ref.key() for ref in basis.draft.next_procedure_refs}):
                raise TaskConflict('Change notification substitutes the actual original signed fact, terms or signer')
            recipients = set(basis.draft.notification_recipient_ids)
            if (recipient_id not in recipients or prior.applicant_id not in recipients
                    or len(recipients) != len(basis.draft.notification_recipient_ids)
                    or recipients != set(effect.notification_recipient_ids)
                    or len(recipients) != len(effect.notification_recipient_ids)):
                raise TaskConflict('Change notification changes authorized original recipients')
            decisions = [read(ref, GovTransitionDecisionView) for ref in prior.history_refs]
            matching = [row for row in decisions if row.business_key == command.business_key]
            if (len({ref.key()[:2] for ref in prior.history_refs}) != len(prior.history_refs)
                    or any(row.case_ref != prior.case_ref for row in decisions)):
                raise TaskConflict('Change notification duplicates or borrows original formal history')
            query = None
            if query_wait:
                if (tuple(condition.object_refs) != (command.ref,) or matching or command.official_decision_ref is not None
                        or command.lookup_status == 'present' or command.status == 'recorded'
                        or not (command.status == 'submitted_unknown' or command.lookup_status == 'unknown')
                        or selected.command_query is None):
                    raise TaskConflict('Change notification requires original uncertain-command gate and actual found-fact query')
                query = GovernmentDecisionQueryRecord.model_validate(selected.command_query)
                if (query.source_identity_sha256 != task_digest(source['identity']) or query.run_id != identity.run_id
                        or query.organization_id != identity.organization_id or query.command_ref != command.ref
                        or query.operation_id != command.operation_id or query.business_key != command.business_key
                        or query.draft_sha256 != command.draft_sha256 or query.result != 'present'
                        or query.official_decision_ref != decision.ref or query.queried_at != now):
                    raise TaskConflict('Change notification query does not authenticate this original found decision')
            elif len(matching) != 1 or matching[0].ref != decision.ref or tuple(condition.object_refs) != (decision.ref,):
                raise TaskConflict('Change notification changes the original recorded-decision wait')
            actual = {row.ref.key()[:2]: row for row in snapshot.notifications}
            if len(actual) != len(snapshot.notifications):
                raise TaskConflict('Change notification duplicates a physical history record')
            for row in snapshot.notifications:
                if (row.recipient_id not in recipients
                        or row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or row.status == 'delivered' and (row.delivered_at is None or row.delivered_at.clock_ref != now.clock_ref
                            or row.delivered_at.offset > row.available_at.offset or row.delivered_at.offset < decision.available_at.offset)
                        or row.status != 'delivered' and row.delivered_at is not None):
                    raise TaskConflict('Change notification loses actual recipient, status or delivery time')
            if matching:
                original = matching[0]
                for field in ('ref', 'case_ref', 'submission_ref', 'command_ref', 'business_key', 'draft_sha256',
                        'signer_actor_id', 'signer_function_ref', 'scope', 'available_at', 'effective_window',
                        'organization_id', 'applicant_id', 'outcome', 'permit_ref', 'effect_rule_ref', 'conditions'):
                    if getattr(original, field) != getattr(decision, field):
                        raise TaskConflict('Change notification rewrites original signed content')
                for ref in original.notification_refs:
                    old = read(ref, GovDecisionNotificationView)
                    current = actual.get(ref.key()[:2])
                    if (current is None or current.recipient_id != old.recipient_id
                            or old.status == 'delivered' and (current.status != 'delivered' or current.delivered_at != old.delivered_at)):
                        raise TaskConflict('Change notification drops or rewrites previous actual delivery history')
            rows.extend([decision, *snapshot.notifications])
            proof_refs = [*snapshot.evidence_refs, *(query.evidence_refs if query is not None else ())]
            proof_refs.extend(ref for row in rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Change notification requires observed original signing, lookup and history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            plan = dict(original_action_input=deepcopy(raw), original_context=old_context.model_dump(mode='json'),
                snapshot=snapshot.model_dump(mode='json'), original_command=command.model_dump(mode='json'),
                command_query=None if query is None else query.model_dump(mode='json'),
                transition_sources=deepcopy(selected.transition_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                evidence=list(evidence.values()), recipient_id=recipient_id)
            if self.validate_relation(source_identity=deepcopy(source['identity']), condition_code=condition.condition_code,
                    notification_transport=True, plan=deepcopy(plan), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Change notification lacks native actual signed fact, complete history and original duty authentication')
            request = GovernmentTransitionNotificationRequest(prior_decision_ref=prior.ref,notification_id=task_digest([
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
