"""Preserve applied feedback while permitting independently sourced future judgment."""
from copy import deepcopy
from typing import Literal

from pydantic import Field, model_validator

from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningStrategyView, ArchitectLearningStateView, ArchitectLearningDecisionView,
    ArchitectLearningCapabilityView, ArchitectLearningProfileView, ArchitectLearningFeedbackView,
    ArchitectLearningExecutionView,
)
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Known, StrictRecord, TextId, TimePoint, ref_type, walk_references
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers
from src.methods.architect_learning import LEARNING_METHOD


APPLIED_CODE = 'feedback_already_applied_to_original_judgment'
JUDGMENT_CODE = 'no_new_declared_judgment_change'
_METADATA = {'ref', 'available_at', 'effective_window'}


class ArchitectAppliedFeedbackQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    original_state_ref: ref_type('ArchitectLearningState')
    current_strategy_ref: ref_type('Strategy')
    current_state_ref: ref_type('ArchitectLearningState')
    queried_at: TimePoint
    status: Literal['applied', 'unknown']
    event_keys: list[TextId] = Field(min_length=1)
    application_execution_refs: list[ref_type('ArchitectLearningExecution')] = Field(min_length=1)
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_history(self):
        if (self.original_state_ref.key()[:2] != self.current_state_ref.key()[:2]
                or len(set(self.event_keys)) != len(self.event_keys)
                or len({ref.key()[:2] for ref in self.application_execution_refs}) != len(self.application_execution_refs)
                or len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs)):
            raise ValueError('Applied-feedback query replaces original state or duplicates events/executions/evidence')
        return self


def check_applied_feedback(check, selected, validate_relation, *, terminal=False, judgment_change=False, engineer=False, qs=False):
    from src.coordination.architect_learning_conditions import ArchitectLearningConditionReading, _FIELDS
    action_id, role = ('ENGINEER-A12', 'Engineer') if engineer else ('ARCHITECT-A12', 'Architect')
    fields = frozenset({'scope', 'strategy_ref', 'qualification_refs', 'feedback_refs', 'learning_profile_ref'}) if engineer else _FIELDS
    strategy_type, state_type, decision_type, execution_type, query_type = (
        ArchitectLearningStrategyView, ArchitectLearningStateView, ArchitectLearningDecisionView,
        ArchitectLearningExecutionView, ArchitectAppliedFeedbackQueryRecord)
    if engineer:
        from src.actions.contracts.engineer_learning_objects import (
            EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView, EngineerLearningExecutionView,
        )
        from src.coordination.engineer_learning_applied_feedback import EngineerAppliedFeedbackQueryRecord
        strategy_type, state_type, decision_type, execution_type, query_type = (
            EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView,
            EngineerLearningExecutionView, EngineerAppliedFeedbackQueryRecord)
    if qs:
        if engineer:
            raise TaskConflict('Applied-feedback recovery requires one original role route')
        from src.actions.contracts.qs_learning_objects import (
            QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView, QSLearningExecutionView,
        )
        from src.coordination.qs_training_conditions import QS_TRAINING_FIELDS
        from src.coordination.qs_learning_applied_feedback import QSAppliedFeedbackQueryRecord
        action_id, role, fields = 'QS-A12', 'QS', QS_TRAINING_FIELDS
        strategy_type, state_type, decision_type, execution_type, query_type = (
            QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView,
            QSLearningExecutionView, QSAppliedFeedbackQueryRecord)
    state_kind = 'QSLearningState' if qs else 'EngineerLearningState' if engineer else 'ArchitectLearningState'
    source = check.source['identity']
    condition_code = JUDGMENT_CODE if judgment_change else APPLIED_CODE
    if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
            or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != (('LearningProfile',) if judgment_change else
                (state_kind,))
            or judgment_change and terminal
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectLearningConditionReading)):
        raise TaskConflict('Applied-feedback recovery replaces original wait/private recipient')
    reading, context, original_context = selected.reading, selected.context, selected.original_context
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (set(raw) != fields or set(current_raw) != fields or task_digest(raw) != source['input_sha256']
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != action_id or context.execution_mode != 'llm'
            or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
            or context.scope != original_context.scope or raw['scope'] != current_raw['scope']
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and raw != current_raw):
        raise TaskConflict('Applied-feedback recovery changes original invocation/scope or current authorization')
    reading.check_method_context(context, action_id)
    proof_refs, versions = [], []

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Applied-feedback recovery lacks exact original/current source versions')
        proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
        return row

    def feedback(refs, at, *, verified=False):
        if len({ref.key() for ref in refs}) != len(refs):
            raise TaskConflict('Applied-feedback recovery duplicates declared feedback')
        events = {}
        for ref in refs:
            row = read(ref, ArchitectLearningFeedbackView)
            points = [row.event.occurred_at, row.authored_at, row.available_at, row.received_at, at]
            if (row.recipient_organization_id != source['organization_id']
                    or any(point.clock_ref != at.clock_ref for point in points)
                    or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                    or row.event_sha256 != content_digest(row.event)
                    or row.event.event_key in events and events[row.event.event_key] != row.event_sha256):
                raise TaskConflict('Applied-feedback recovery rewrites private event content/chronology')
            subject = reading.resolve(row.event.subject_ref)
            if (not isinstance(subject, StrictRecord) or content_digest(subject) != row.event.subject_sha256
                    or hasattr(subject, 'available_at') and (subject.available_at.clock_ref != at.clock_ref
                        or subject.available_at.offset > row.received_at.offset)):
                raise TaskConflict('Applied-feedback recovery replaces original received event subject')
            proof_refs.extend(ref for ref in walk_references(subject) if ref.kind == 'Evidence')
            if verified and (row.status != 'verified' or not isinstance(row.verified, Known) or row.verified.value is not True):
                raise TaskConflict('Applied-feedback wait lacks original verified feedback')
            events[row.event.event_key] = row.event_sha256
        return events

    query = None if selected.applied_feedback_query is None else query_type.model_validate(
        deepcopy(selected.applied_feedback_query))
    for action_input, invocation in ((raw, original_context), (current_raw, context)):
        is_current = action_input is current_raw
        if terminal and is_current and (query is None or query.status != 'applied'):
            return 'waiting', None
        strategy_ref = query.current_strategy_ref if terminal and is_current else ref_type('Strategy').model_validate(action_input['strategy_ref'])
        strategy = read(strategy_ref, strategy_type)
        state = read(strategy.learning_state_ref, state_type)
        decision = read(strategy.decision_profile_ref, decision_type)
        capability = read(state.capability_ref, ArchitectLearningCapabilityView)
        if action_input['learning_profile_ref'] is None:
            raise TaskConflict('Applied-feedback recovery loses the original selected learning profile')
        profile = read(ref_type('LearningProfile').model_validate(action_input['learning_profile_ref']), ArchitectLearningProfileView)
        if (any(row.organization_id != source['organization_id'] for row in (strategy, state, decision, capability, profile))
                or any(row.author_organization_id != source['organization_id'] for row in (strategy, decision, capability, profile))
                or state.strategy_ref != strategy.ref or decision.strategy_ref != strategy.ref
                or state.scope != invocation.scope or decision.scope != invocation.scope or state.coverage != 'complete'
                or state.as_of != invocation.business_time or state.learning_profile_ref != profile.ref
                or not engineer and not qs and capability.ref.key()[:2] != ref_type('Capability').model_validate(action_input['capability_ref']).key()[:2]
                or profile.strategy_ref.key()[:2] != strategy.ref.key()[:2]
                or profile.calculation_method_ref != LEARNING_METHOD
                or not isinstance(profile.enabled, Known) or profile.enabled.value is not True
                or not terminal and is_current and decision.choice != 'update_judgment'
                or not is_current and decision.choice != 'update_judgment'):
            raise TaskConflict('Applied-feedback recovery replaces complete private strategy/state/profile')
        required_current = (strategy, state) if terminal and is_current else (strategy, state, decision, capability, profile)
        if any(row.available_at.clock_ref != invocation.business_time.clock_ref
                or row.available_at.offset > invocation.business_time.offset
                or not row.effective_window.contains(invocation.business_time) for row in required_current):
            return 'unavailable', None
        if not terminal or not is_current:
            grant, function = reading.resolve(decision.authority_ref), reading.resolve(invocation.function_ref)
            if (decision.actor_id != invocation.actor_id or decision.function_ref != invocation.function_ref
                    or decision.authority_ref not in invocation.authorization_refs or not isinstance(grant, Authorization)
                    or grant.actor_id != invocation.actor_id or grant.organization_id != source['organization_id']
                    or grant.function_ref != invocation.function_ref or action_id not in grant.action_ids
                    or not grant.validity.contains(invocation.business_time)
                    or not any(scope_covers(scope, invocation.scope) for scope in grant.scopes)
                    or not isinstance(function, RoleAssignment) or function.role != role):
                raise TaskConflict('Applied-feedback recovery lacks original/current independent decision authority')
            proof_refs.extend([*grant.basis_refs, *function.basis_refs])
        if not {ref.key() for ref in state.applied_feedback_refs} <= {ref.key() for ref in state.received_feedback_refs}:
            raise TaskConflict('Applied-feedback history applies unreceived feedback')
        received = feedback(state.received_feedback_refs, invocation.business_time)
        applied = feedback(state.applied_feedback_refs, invocation.business_time)
        refs = [ref_type('Feedback').model_validate(ref) for ref in action_input['feedback_refs']]
        chosen = feedback(refs, invocation.business_time, verified=True)
        if (not {ref.key() for ref in refs} <= {ref.key() for ref in state.received_feedback_refs}
                or (not terminal or not is_current) and {ref.key() for ref in refs} != {ref.key() for ref in decision.feedback_refs}
                or any(received.get(key) != value for key, value in [*applied.items(), *chosen.items()])):
            raise TaskConflict('Applied-feedback recovery substitutes declared received/selected event history')
        executions = [read(ref, execution_type) for ref in state.execution_refs]
        if (len({row.ref.key()[:2] for row in executions}) != len(executions)
                or len({row.business_key for row in executions}) != len(executions)
                or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                    or row.strategy_ref.key()[:2] != strategy.ref.key()[:2]
                    or row.available_at.clock_ref != invocation.business_time.clock_ref
                    or row.available_at.offset > invocation.business_time.offset for row in executions)):
            raise TaskConflict('Applied-feedback recovery drops or duplicates private execution identities')
        if not terminal or not is_current:
            if any(row.business_key == decision.business_key or row.status in {'pending', 'unknown'} for row in executions):
                if not is_current:
                    raise TaskConflict('Applied-feedback wait bypasses its original execution-query gate')
                return 'waiting', None
        versions.append(dict(strategy=strategy, state=state, decision=decision, capability=capability, profile=profile,
            received=received, applied=applied, chosen=chosen, executions=executions))
    old, current = versions
    if engineer:
        from src.coordination.engineer_learning_applied_feedback import preserve_applied_feedback_qualifications
        preserve_applied_feedback_qualifications(raw, current_raw, old, current, read, original_context, context, terminal=terminal)
    if qs:
        from src.coordination.qs_learning_applied_feedback import preserve_qs_feedback_history
        state = preserve_qs_feedback_history(raw, current_raw, old, current, read, selected,
            terminal=terminal, judgment_change=judgment_change)
        if state != 'ready':
            return state, None
    if (tuple(check.condition.object_refs) != ((old['profile'].ref,) if judgment_change else (old['state'].ref,))
            or not old['chosen'] or not judgment_change and set(old['chosen']) - set(old['applied'])):
        raise TaskConflict('Applied-feedback recovery differs from original no-fresh-feedback gate')
    current_executions = {row.ref.key()[:2]: row for row in current['executions']}
    if (old['strategy'].ref.key()[:2] != current['strategy'].ref.key()[:2]
            or old['state'].ref.key()[:2] != current['state'].ref.key()[:2]
            or old['capability'].model_dump(exclude=_METADATA | ({'qualification_refs'} if engineer else set()))
                != current['capability'].model_dump(exclude=_METADATA | ({'qualification_refs'} if engineer else set()))
            or any(current['received'].get(key) != value for key, value in old['received'].items())
            or any(current['applied'].get(key) != value for key, value in old['applied'].items())
            or any(not {ref.key() for ref in getattr(old['state'], field)} <= {ref.key() for ref in getattr(current['state'], field)}
                for field in ('received_feedback_refs', 'applied_feedback_refs'))
            or any(current_executions.get(row.ref.key()[:2]) != row for row in old['executions'])):
        raise TaskConflict('Applied-feedback recovery rewrites retained events/capability/execution history')
    judgment_proof = None
    if judgment_change:
        from src.coordination.architect_learning_judgment_change import read_judgment_change
        state, judgment_proof = read_judgment_change(selected, old, current, engineer=engineer, qs=qs)
        if state != 'ready':
            return state, None
    elif terminal:
        if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
                or query.organization_id != source['organization_id'] or query.original_state_ref != old['state'].ref
                or query.current_state_ref != current['state'].ref or query.queried_at != context.business_time
                or set(query.event_keys) != set(old['chosen'])):
            raise TaskConflict('Applied-feedback query replaces original wait or actually selected event identities')
        covered = set()
        for ref in query.application_execution_refs:
            execution = read(ref, execution_type)
            decision = read(execution.decision_ref, decision_type)
            if (current_executions.get(ref.key()[:2]) != execution or execution.status != 'succeeded'
                    or execution.decision_sha256 != content_digest(decision) or decision.choice != 'update_judgment'
                    or decision.business_key != execution.business_key or decision.organization_id != source['organization_id']
                    or decision.strategy_ref.key()[:2] != execution.strategy_ref.key()[:2]):
                raise TaskConflict('Applied-feedback query lacks actual successful original judgment application')
            covered.update(feedback(decision.feedback_refs, context.business_time))
        if not set(query.event_keys) <= covered or not set(query.event_keys) <= set(current['applied']):
            raise TaskConflict('Applied-feedback query omits original actual applied event history')
        proof_refs.extend(query.evidence_refs)
    elif not set(current['chosen']) - set(current['applied']):
        return 'waiting', None
    evidence = {}
    for ref in proof_refs:
        row = reading.resolve(ref)
        if not isinstance(row, EvidenceRecord) or row.ref != ref or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Applied-feedback recovery requires actual observed history/application evidence')
        evidence[ref.key()] = row.model_dump(mode='json')
    resolution = dict(schema_version='qs-judgment-change-resolution.v1' if qs and judgment_change else
        'qs-applied-feedback-resolution.v1' if qs else
        'engineer-judgment-change-resolution.v1' if engineer and judgment_change else
        'engineer-applied-feedback-resolution.v1' if engineer else
        'architect-judgment-change-resolution.v1' if judgment_change else 'architect-applied-feedback-resolution.v1',
        disposition='new_judgment_available' if judgment_change else 'already_applied',
        query=None if query is None else query.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        learning_sources=deepcopy(selected.learning_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
        evidence=list(evidence.values()))
    if judgment_change:
        resolution['judgment_change'] = deepcopy(judgment_proof)
    if validate_relation(source_identity=deepcopy(source), condition_code=condition_code, terminal_application=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Applied-feedback recovery lacks native actual application/history/author authentication')
    return 'ready', resolution


def architect_original_applied_feedback_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Applied-feedback recovery requires guarded sources and independent native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_applied_feedback(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ARCHITECT-A12', APPLIED_CODE, '1', frozenset({'dependency_change'}), evaluate)
