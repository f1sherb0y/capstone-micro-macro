"""Close A09 formal-change waits after native actual delivery, without replaying signing."""
from copy import deepcopy

from integration.task_continuation import observation_signal_matches
from pydantic import TypeAdapter

from src.actions.contracts.common import EvidenceRecord, ResumeCondition, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_transition_objects import (
    GovTransitionDecisionView, GovTransitionRuleView, GovChangeBasisView, GovChangeEffectView,
    GovDecisionCommandView, GovDecisionNotificationView,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.government_transition_conditions import _CODE
from src.coordination.government_transition_notification import (
    NOTIFICATION_CODE, GovernmentTransitionNotificationCompletionRecord,
)
from src.coordination.government_decision_query import GovernmentDecisionQueryRecord
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


def reconcile_government_transition_notification(*, identity, signal, reader, dispatcher, validate_relation):
    store = reader.snapshots.store
    signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
    if (identity.action_id != 'GOV-A09' or identity.role != 'Government' or identity.purpose != 'action'
            or signal.run_id != identity.run_id or signal.organization_id != identity.organization_id):
        raise TaskConflict('Change delivery changes original action/run/recipient')
    events = [row for row in dispatcher.inbox.for_organization(run_id=identity.run_id,
        organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
    if len(events) != 1:
        raise TaskConflict('Change delivery requires original persisted recipient feedback')
    projected = dispatcher.project_signal(deepcopy(events[0]))
    if not observation_signal_matches(events[0], projected, expected=signal):
        raise TaskConflict('Change delivery replaces persisted feedback projection')
    source = store.get(identity)
    if (source['state'] not in {'waiting_input', 'wait_resolved'} or len(source['conditions']) != 1
            or store.continuation(identity) is not None):
        raise TaskConflict('Change delivery requires original wait without a signing successor')
    condition = ResumeCondition.model_validate(source['conditions'][0])
    query_wait = condition.condition_code == _CODE
    if (condition.condition_code not in {NOTIFICATION_CODE, _CODE}
            or condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in condition.object_refs) != (('DecisionCommand',) if query_wait else ('Decision',))
            or not dispatcher.journal._matches(condition, signal)):
        raise TaskConflict('Change delivery replaces original formal-fact wait or matching signal')
    selected = reader(ConditionCheck(deepcopy(source), condition, signal), notification_terminal=True)
    reading, context = selected.reading, selected.context
    try:
        old_context, raw = selected.original_context, selected.original_action_input
        if (old_context is None or task_digest(raw) != identity.input_sha256
                or task_digest(old_context.model_dump(mode='json')) != identity.context_sha256
                or selected.action_input != raw or selected.notification_completion is None
                or reading._resolver.source_mode != 'formal' or reading.organization_id != identity.organization_id
                or context.operation_id != old_context.operation_id or context.business_time != signal.business_time):
            raise TaskConflict('Change delivery changes original invocation, draft or formal sources')
        completion = GovernmentTransitionNotificationCompletionRecord.model_validate(deepcopy(selected.notification_completion))
        scope = TypeAdapter(ScopeRef).validate_python(raw['scope'])
        proof_rows = []

        def read(ref, schema, *, linked=False):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref or not linked and not scope_covers(context.scope, row.scope):
                raise TaskConflict('Change delivery lacks exact original scoped source')
            proof_rows.append(row)
            return row

        prior = read(ref_type('Decision').model_validate(raw['prior_decision_ref']), GovTransitionDecisionView, linked=True)
        rule = read(ref_type('Rule').model_validate(raw['transition_rule_ref']), GovTransitionRuleView, linked=True)
        if rule.decision_basis_ref is None:
            raise TaskConflict('Change delivery loses original change draft basis')
        basis = read(rule.decision_basis_ref, GovChangeBasisView)
        command = read(basis.command_ref, GovDecisionCommandView)
        effect = read(basis.draft.effect_rule_ref, GovChangeEffectView)
        decision, now = completion.decision, context.business_time
        if (completion.source_identity_sha256 != task_digest(source['identity'])
                or completion.run_id != identity.run_id or completion.organization_id != identity.organization_id
                or completion.prior_decision_ref != prior.ref or prior.organization_id != identity.organization_id
                or not scope_covers(prior.scope, scope) or prior.history_coverage != 'complete'
                or prior.as_of != old_context.business_time or rule.purpose != 'transition'
                or rule.choice not in {'renew', 'suspend', 'revoke', 'restore'}
                or rule.organization_id != identity.organization_id or rule.prior_decision_ref != prior.ref
                or basis.transition_rule_ref != rule.ref or basis.draft.outcome != rule.choice
                or basis.draft.prior_decision_ref != prior.ref or basis.draft.case_ref != prior.case_ref
                or basis.draft.decision_basis_ref != basis.ref or basis.draft.covered_scope.model_dump(mode='json') != raw['scope']
                or basis.draft.submission_ref.model_dump(mode='json') != raw['affected_submission_ref']
                or decision.organization_id != identity.organization_id or decision.applicant_id != prior.applicant_id
                or decision.outcome != basis.draft.outcome or decision.permit_ref != prior.permit_ref
                or decision.ref.key()[:2] == prior.ref.key()[:2]
                or decision.conditions != basis.draft.conditions
                or command.operation_id != old_context.operation_id or command.draft_sha256 != content_digest(basis.draft)
                or command.case_ref != prior.case_ref or command.submission_ref != basis.draft.submission_ref
                or command.decision_basis_ref != basis.ref or decision.case_ref != prior.case_ref
                or decision.submission_ref != command.submission_ref or decision.command_ref != command.ref
                or decision.business_key != command.business_key or decision.draft_sha256 != command.draft_sha256
                or decision.signer_actor_id != old_context.actor_id or decision.signer_function_ref != old_context.function_ref
                or command.official_decision_ref not in {None, decision.ref}
                or effect.decision_basis_ref != basis.ref or effect.outcome != basis.draft.outcome
                or not scope_covers(decision.scope, scope)
                or effect.expiry_rule_ref != basis.draft.expiry_rule_ref
                or {ref.key() for ref in effect.next_procedure_refs} != {ref.key() for ref in basis.draft.next_procedure_refs}
                or completion.completed_at.clock_ref != now.clock_ref or old_context.business_time.clock_ref != now.clock_ref
                or not old_context.business_time.offset <= completion.completed_at.offset <= now.offset
                or decision.available_at.clock_ref != now.clock_ref or decision.available_at.offset > now.offset):
            raise TaskConflict('Change delivery substitutes original signed fact, terms, signer or completion time')
        decisions = [read(ref, GovTransitionDecisionView, linked=True) for ref in prior.history_refs]
        matching = [row for row in decisions if row.business_key == command.business_key]
        if (len({ref.key()[:2] for ref in prior.history_refs}) != len(prior.history_refs)
                or any(row.case_ref != prior.case_ref for row in decisions)):
            raise TaskConflict('Change delivery duplicates or borrows original case formal history')
        query = None
        if query_wait:
            if (tuple(condition.object_refs) != (command.ref,) or matching or command.official_decision_ref is not None
                    or command.lookup_status == 'present' or command.status == 'recorded'
                    or not (command.status == 'submitted_unknown' or command.lookup_status == 'unknown')
                    or selected.command_query is None):
                raise TaskConflict('Change delivery lacks original uncertain-command gate and actual found-fact query')
            query = GovernmentDecisionQueryRecord.model_validate(deepcopy(selected.command_query))
            if (query.source_identity_sha256 != task_digest(source['identity']) or query.run_id != identity.run_id
                    or query.organization_id != identity.organization_id or query.command_ref != command.ref
                    or query.operation_id != command.operation_id or query.business_key != command.business_key
                    or query.draft_sha256 != command.draft_sha256 or query.result != 'present'
                    or query.official_decision_ref != decision.ref or query.queried_at != now):
                raise TaskConflict('Change delivery query does not authenticate this original found decision')
        elif (len(matching) != 1 or matching[0].ref != decision.ref or tuple(condition.object_refs) != (decision.ref,)):
            raise TaskConflict('Change delivery replaces original recorded formal decision')
        recipients = set(basis.draft.notification_recipient_ids)
        if (len(recipients) != len(basis.draft.notification_recipient_ids)
                or not recipients or prior.applicant_id not in recipients
                or recipients != set(effect.notification_recipient_ids)
                or len(recipients) != len(effect.notification_recipient_ids)):
            raise TaskConflict('Change delivery substitutes authorized original recipients')
        delivered, notifications = set(), completion.notifications
        if len({row.ref.key()[:2] for row in notifications}) != len(notifications):
            raise TaskConflict('Change delivery repeats a physical notification')
        for row in notifications:
            if (row.recipient_id not in recipients
                    or row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset):
                raise TaskConflict('Change delivery borrows another recipient/scope or future notification')
            if row.status == 'delivered':
                if (row.delivered_at is None or row.delivered_at.clock_ref != now.clock_ref
                        or row.delivered_at.offset > completion.completed_at.offset
                        or row.delivered_at.offset > row.available_at.offset
                        or row.delivered_at.offset < decision.available_at.offset or not row.evidence_refs):
                    raise TaskConflict('Change delivery lacks observed actual delivery before completion')
                delivered.add(row.recipient_id)
            elif row.delivered_at is not None:
                raise TaskConflict('Undelivered notification carries a fabricated delivery time')
        if delivered != recipients:
            raise TaskConflict('Change delivery remains incomplete for original recipients')
        if matching:
            original = matching[0]
            immutable = ('ref', 'case_ref', 'submission_ref', 'command_ref', 'business_key', 'draft_sha256',
                'signer_actor_id', 'signer_function_ref', 'scope', 'available_at', 'effective_window',
                'organization_id', 'applicant_id', 'outcome', 'permit_ref', 'effect_rule_ref', 'conditions')
            if any(getattr(original, field) != getattr(decision, field) for field in immutable):
                raise TaskConflict('Change delivery rewrites the original formal record')
            current_notifications = {row.ref.key()[:2]: row for row in notifications}
            for ref in original.notification_refs:
                old = read(ref, GovDecisionNotificationView, linked=True)
                current = current_notifications.get(ref.key()[:2])
                if (current is None or current.recipient_id != old.recipient_id or current.decision_ref != old.decision_ref
                        or old.status == 'delivered' and (current.status != 'delivered' or current.delivered_at != old.delivered_at)):
                    raise TaskConflict('Change delivery drops or rewrites previously received notification history')
        proof_rows.extend([decision, effect, *notifications])
        proof_refs = [*completion.evidence_refs, *(query.evidence_refs if query is not None else ())]
        proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
        evidence = {}
        for ref in proof_refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Change delivery requires observed signing, lookup and actual delivery evidence')
            evidence[ref.key()] = row.model_dump(mode='json')
        resolution = dict(schema_version='government-transition-delivery-resolution.v1',
            completion=completion.model_dump(mode='json'), command_query=None if query is None else query.model_dump(mode='json'),
            original_action_input=deepcopy(raw), original_context=old_context.model_dump(mode='json'),
            context=context.model_dump(mode='json'), transition_sources=deepcopy(selected.transition_sources),
            unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()))
        if validate_relation(source_identity=deepcopy(source['identity']), condition_code=condition.condition_code,
                terminal_notification=True, resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Change delivery lacks native original fact, complete history, delivery and legal effect authentication')
        reading.recheck()
        reader._check()
        previous = store.wait_resolution(identity)
        if previous is not None:
            if previous['resolution']['completion'] != completion.model_dump(mode='json'):
                raise TaskConflict('Change delivery rewrites archived original completion')
            return previous
        return store.resolve_wait(identity, source['revision'], resolution=resolution,
            validate_resolution=lambda current_source, _: current_source == source)
    finally:
        reading.recheck()
        reader._check()
