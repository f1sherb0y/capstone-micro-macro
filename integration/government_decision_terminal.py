"""Close A07 formal-fact waits after native actual delivery, without replaying signing."""
from copy import deepcopy

from integration.task_continuation import observation_signal_matches
from src.actions.contracts.common import EvidenceRecord, ResumeCondition, ref_type, walk_references
from src.actions.contracts.government_decision_objects import (
    GovDecisionCaseView, GovDecisionBasisView, GovDecisionCommandView, GovDecisionEffectView,
    GovFormalDecisionView, GovDecisionNotificationView,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.government_decision_conditions import _QUERY_CODE, _UNRESOLVED_CODE
from src.coordination.government_decision_notification import (
    NOTIFICATION_CODE, GovernmentDecisionNotificationCompletionRecord,
)
from src.coordination.government_decision_query import GovernmentDecisionQueryRecord
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


def reconcile_government_decision_notification(*, identity, signal, reader, dispatcher, validate_relation):
    store = reader.snapshots.store
    signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
    if (identity.action_id != 'GOV-A07' or identity.role != 'Government' or identity.purpose != 'action'
            or signal.run_id != identity.run_id or signal.organization_id != identity.organization_id):
        raise TaskConflict('Decision delivery changes original action/run/recipient')
    events = [row for row in dispatcher.inbox.for_organization(run_id=identity.run_id,
        organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
    if len(events) != 1:
        raise TaskConflict('Decision delivery requires original persisted recipient feedback')
    projected = dispatcher.project_signal(deepcopy(events[0]))
    if not observation_signal_matches(events[0], projected, expected=signal):
        raise TaskConflict('Decision delivery replaces persisted feedback projection')
    source = store.get(identity)
    if (source['state'] not in {'waiting_input', 'wait_resolved'} or len(source['conditions']) != 1
            or store.continuation(identity) is not None):
        raise TaskConflict('Decision delivery requires original wait without a signing successor')
    condition = ResumeCondition.model_validate(source['conditions'][0])
    query_wait = condition.condition_code in {_QUERY_CODE, _UNRESOLVED_CODE}
    if (condition.condition_code not in {NOTIFICATION_CODE, _QUERY_CODE, _UNRESOLVED_CODE}
            or condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in condition.object_refs) != (('DecisionCommand',) if query_wait else ('Decision',))
            or not dispatcher.journal._matches(condition, signal)):
        raise TaskConflict('Decision delivery replaces original formal-fact wait or matching signal')
    selected = reader(ConditionCheck(deepcopy(source), condition, signal), notification_terminal=True)
    reading, context = selected.reading, selected.context
    try:
        old_context, raw = selected.original_context, selected.original_action_input
        if (old_context is None or task_digest(raw) != identity.input_sha256
                or task_digest(old_context.model_dump(mode='json')) != identity.context_sha256
                or selected.action_input != raw or selected.notification_completion is None
                or reading._resolver.source_mode != 'formal' or reading.organization_id != identity.organization_id
                or context.operation_id != old_context.operation_id or context.business_time != signal.business_time):
            raise TaskConflict('Decision delivery changes original invocation, draft or formal sources')
        completion = GovernmentDecisionNotificationCompletionRecord.model_validate(deepcopy(selected.notification_completion))
        proof_rows = []

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref or not scope_covers(context.scope, row.scope):
                raise TaskConflict('Decision delivery lacks exact original scoped source')
            proof_rows.append(row)
            return row

        case = read(ref_type('RegulatoryCase').model_validate(raw['case_ref']), GovDecisionCaseView)
        basis = read(ref_type('DecisionBasis').model_validate(raw['decision_basis_ref']), GovDecisionBasisView)
        command = read(basis.command_ref, GovDecisionCommandView)
        effect = read(basis.draft.effect_rule_ref, GovDecisionEffectView)
        decision, now = completion.decision, context.business_time
        if (completion.source_identity_sha256 != task_digest(source['identity'])
                or completion.run_id != identity.run_id or completion.organization_id != identity.organization_id
                or command.operation_id != old_context.operation_id or command.draft_sha256 != content_digest(basis.draft)
                or command.case_ref != case.ref or command.submission_ref != basis.submission_ref
                or command.decision_basis_ref != basis.ref or decision.case_ref != case.ref
                or decision.submission_ref != command.submission_ref or decision.command_ref != command.ref
                or decision.business_key != command.business_key or decision.draft_sha256 != command.draft_sha256
                or decision.signer_actor_id != basis.signer_actor_id or decision.signer_function_ref != basis.signer_function_ref
                or command.official_decision_ref not in {None, decision.ref}
                or effect.decision_rule_ref != basis.decision_rule_ref or effect.outcome != basis.draft.outcome
                or not effect.modeled or not scope_covers(context.scope, decision.scope)
                or completion.completed_at.clock_ref != now.clock_ref or old_context.business_time.clock_ref != now.clock_ref
                or not old_context.business_time.offset <= completion.completed_at.offset <= now.offset
                or decision.available_at.clock_ref != now.clock_ref or decision.available_at.offset > now.offset):
            raise TaskConflict('Decision delivery substitutes original signed fact, terms, signer or completion time')
        decisions = [read(ref, GovFormalDecisionView) for ref in case.decision_refs]
        matching = [row for row in decisions if row.business_key == command.business_key]
        if (len({ref.key()[:2] for ref in case.decision_refs}) != len(case.decision_refs)
                or any(row.case_ref != case.ref for row in decisions)):
            raise TaskConflict('Decision delivery duplicates or borrows original case formal history')
        query = None
        if query_wait:
            if (tuple(condition.object_refs) != (command.ref,) or matching or command.official_decision_ref is not None
                    or command.lookup_status == 'present' or command.status == 'recorded'
                    or condition.condition_code == _QUERY_CODE and (command.status not in {'submitted_unknown', 'failed'}
                        or command.lookup_status == 'absent')
                    or condition.condition_code == _UNRESOLVED_CODE and (command.lookup_status != 'unknown'
                        or command.status in {'submitted_unknown', 'failed'})
                    or selected.command_query is None):
                raise TaskConflict('Decision delivery lacks original uncertain-command gate and actual found-fact query')
            query = GovernmentDecisionQueryRecord.model_validate(deepcopy(selected.command_query))
            if (query.source_identity_sha256 != task_digest(source['identity']) or query.run_id != identity.run_id
                    or query.organization_id != identity.organization_id or query.command_ref != command.ref
                    or query.operation_id != command.operation_id or query.business_key != command.business_key
                    or query.draft_sha256 != command.draft_sha256 or query.result != 'present'
                    or query.official_decision_ref != decision.ref or query.queried_at != now):
                raise TaskConflict('Decision delivery query does not authenticate this original found decision')
        elif (len(matching) != 1 or matching[0].ref != decision.ref or tuple(condition.object_refs) != (decision.ref,)):
            raise TaskConflict('Decision delivery replaces original recorded formal decision')
        recipients = set(basis.draft.notification_recipient_ids)
        if (len(recipients) != len(basis.draft.notification_recipient_ids)
                or not recipients or case.applicant_id not in recipients
                or recipients != set(effect.notification_recipient_ids)
                or len(recipients) != len(effect.notification_recipient_ids)):
            raise TaskConflict('Decision delivery substitutes authorized original recipients')
        delivered, notifications = set(), completion.notifications
        if len({row.ref.key()[:2] for row in notifications}) != len(notifications):
            raise TaskConflict('Decision delivery repeats a physical notification')
        for row in notifications:
            if (row.recipient_id not in recipients or not scope_covers(context.scope, row.scope)
                    or row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset):
                raise TaskConflict('Decision delivery borrows another recipient/scope or future notification')
            if row.status == 'delivered':
                if (row.delivered_at is None or row.delivered_at.clock_ref != now.clock_ref
                        or row.delivered_at.offset > completion.completed_at.offset
                        or row.delivered_at.offset > row.available_at.offset
                        or row.delivered_at.offset < decision.available_at.offset or not row.evidence_refs):
                    raise TaskConflict('Decision delivery lacks observed actual delivery before completion')
                delivered.add(row.recipient_id)
            elif row.delivered_at is not None:
                raise TaskConflict('Undelivered notification carries a fabricated delivery time')
        if delivered != recipients:
            raise TaskConflict('Decision delivery remains incomplete for original recipients')
        if matching:
            original = matching[0]
            immutable = ('ref', 'case_ref', 'submission_ref', 'command_ref', 'business_key', 'draft_sha256',
                'signer_actor_id', 'signer_function_ref', 'scope', 'available_at', 'effective_window')
            if any(getattr(original, field) != getattr(decision, field) for field in immutable):
                raise TaskConflict('Decision delivery rewrites the original formal record')
            current_notifications = {row.ref.key()[:2]: row for row in notifications}
            for ref in original.notification_refs:
                old = read(ref, GovDecisionNotificationView)
                current = current_notifications.get(ref.key()[:2])
                if (current is None or current.recipient_id != old.recipient_id or current.decision_ref != old.decision_ref
                        or old.status == 'delivered' and (current.status != 'delivered' or current.delivered_at != old.delivered_at)):
                    raise TaskConflict('Decision delivery drops or rewrites previously received notification history')
        proof_rows.extend([decision, effect, *notifications])
        proof_refs = [*completion.evidence_refs, *(query.evidence_refs if query is not None else ())]
        proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
        evidence = {}
        for ref in proof_refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Decision delivery requires observed signing, lookup and actual delivery evidence')
            evidence[ref.key()] = row.model_dump(mode='json')
        resolution = dict(schema_version='government-decision-delivery-resolution.v1',
            completion=completion.model_dump(mode='json'), command_query=None if query is None else query.model_dump(mode='json'),
            original_action_input=deepcopy(raw), original_context=old_context.model_dump(mode='json'),
            context=context.model_dump(mode='json'), decision_sources=deepcopy(selected.decision_sources),
            unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()))
        if validate_relation(source_identity=deepcopy(source['identity']), condition_code=condition.condition_code,
                terminal_notification=True, resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Decision delivery lacks native original fact, complete history, delivery and legal effect authentication')
        reading.recheck()
        reader._check()
        previous = store.wait_resolution(identity)
        if previous is not None:
            if previous['resolution']['completion'] != completion.model_dump(mode='json'):
                raise TaskConflict('Decision delivery rewrites archived original completion')
            return previous
        return store.resolve_wait(identity, source['revision'], resolution=resolution,
            validate_resolution=lambda current_source, _: current_source == source)
    finally:
        reading.recheck()
        reader._check()
