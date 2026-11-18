"""Authenticate actual A12 execution queries before resuming private learning."""
from copy import deepcopy

from pydantic import Field, model_validator

from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningStrategyView, ArchitectLearningStateView, ArchitectLearningDecisionView,
    ArchitectLearningCapabilityView, ArchitectLearningExecutionView,
)
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import ActionContext, EvidenceRecord, StrictRecord, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXECUTION_CODE = 'query_original_architect_learning_execution'
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_DECISION_METADATA = {'ref', 'strategy_ref', 'available_at', 'effective_window'}
_SOURCE_METADATA = {'ref', 'available_at', 'effective_window'}


class ArchitectLearningExecutionQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    execution_ref: ref_type('ArchitectLearningExecution')
    business_key: TextId
    decision_sha256: Digest
    queried_at: TimePoint
    execution: ArchitectLearningExecutionView
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def original_execution(self):
        if (self.execution.ref.key()[:2] != self.execution_ref.key()[:2]
                or self.execution.run_id != self.run_id or self.execution.organization_id != self.organization_id
                or self.execution.business_key != self.business_key or self.execution.decision_sha256 != self.decision_sha256
                or len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs)):
            raise ValueError('Learning query replaces original run/firm/business/decision or repeats evidence')
        return self


def check_learning_execution(check, selected, validate_relation, *, terminal=False, engineer=False, qs=False):
    """A same-business terminal result is archived; other resolved history permits fresh judgment."""
    from src.coordination.architect_learning_conditions import ArchitectLearningConditionReading, _FIELDS
    action_id, role = ('ENGINEER-A12', 'Engineer') if engineer else ('ARCHITECT-A12', 'Architect')
    fields = frozenset({'scope', 'strategy_ref', 'qualification_refs', 'feedback_refs', 'learning_profile_ref'}) if engineer else _FIELDS
    strategy_type, state_type, decision_type, execution_type, query_type = (
        ArchitectLearningStrategyView, ArchitectLearningStateView, ArchitectLearningDecisionView,
        ArchitectLearningExecutionView, ArchitectLearningExecutionQueryRecord)
    if engineer:
        from src.actions.contracts.engineer_learning_objects import (
            EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView, EngineerLearningExecutionView,
        )
        from src.coordination.engineer_learning_execution_query import EngineerLearningExecutionQueryRecord
        strategy_type, state_type, decision_type, execution_type, query_type = (
            EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView,
            EngineerLearningExecutionView, EngineerLearningExecutionQueryRecord)
    if qs:
        if engineer:
            raise TaskConflict('Learning execution query requires one original role route')
        from src.actions.contracts.qs_learning_objects import (
            QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView, QSLearningExecutionView,
        )
        from src.coordination.qs_learning_execution_query import QSLearningExecutionQueryRecord
        action_id, role = 'QS-A12', 'QS'
        fields = frozenset({'scope', 'strategy_ref', 'forecast_refs', 'outcome_refs',
            'comparability_result_ref', 'feedback_refs', 'learning_profile_ref'})
        strategy_type, state_type, decision_type, execution_type, query_type = (
            QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView,
            QSLearningExecutionView, QSLearningExecutionQueryRecord)
    execution_kind = 'QSLearningExecution' if qs else 'EngineerLearningExecution' if engineer else 'ArchitectLearningExecution'
    source = check.source['identity']
    if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
            or check.condition.condition_code != EXECUTION_CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != (execution_kind,)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectLearningConditionReading)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView)):
        raise TaskConflict('Learning execution query replaces original wait, firm or typed sources')
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
        raise TaskConflict('Learning execution query changes original snapshot/scope or selected invocation')
    reading.check_method_context(context, action_id)
    rows, proof_refs = [], []

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Learning execution query lacks exact original/current source history')
        rows.append(row)
        proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
        return row

    versions = []
    for action_input, invocation in ((raw, original_context), (current_raw, context)):
        strategy = read(ref_type('Strategy').model_validate(action_input['strategy_ref']), strategy_type)
        state = read(strategy.learning_state_ref, state_type)
        decision = read(strategy.decision_profile_ref, decision_type)
        capability = read(state.capability_ref if engineer or qs else ref_type('Capability').model_validate(action_input['capability_ref']), ArchitectLearningCapabilityView)
        if (any(row.organization_id != source['organization_id'] for row in (strategy, state, decision, capability))
                or any(row.author_organization_id != source['organization_id'] for row in (strategy, decision, capability))
                or state.strategy_ref != strategy.ref or state.capability_ref != capability.ref
                or state.scope != invocation.scope or state.coverage != 'complete'
                or (not terminal or action_input is raw) and state.as_of != invocation.business_time
                or decision.strategy_ref != strategy.ref or decision.scope != invocation.scope
                or decision.actor_id != invocation.actor_id or decision.function_ref != invocation.function_ref
                or (not terminal or action_input is raw) and decision.authority_ref not in invocation.authorization_refs
                or {ref.key() for ref in decision.feedback_refs} != {ref_type('Feedback').model_validate(ref).key() for ref in action_input['feedback_refs']}
                or not {ref.key() for ref in decision.feedback_refs} <= {ref.key() for ref in state.received_feedback_refs}):
            raise TaskConflict('Learning execution query replaces original complete private state/decision/feedback authority')
        grant, function = reading.resolve(decision.authority_ref), reading.resolve(invocation.function_ref)
        authority_at = original_context.business_time if terminal and action_input is current_raw else invocation.business_time
        if (not isinstance(grant, Authorization) or grant.ref != decision.authority_ref
                or grant.actor_id != invocation.actor_id or grant.organization_id != source['organization_id']
                or grant.function_ref != invocation.function_ref or action_id not in grant.action_ids
                or not grant.validity.contains(authority_at)
                or not any(scope_covers(scope, invocation.scope) for scope in grant.scopes)
                or not isinstance(function, RoleAssignment) or function.function_ref != invocation.function_ref
                or function.role != role):
            raise TaskConflict('Learning execution query lacks original/current independent working authorization')
        proof_refs.extend([*grant.basis_refs, *function.basis_refs])
        history = [read(ref, execution_type) for ref in state.execution_refs]
        if (len({row.ref.key()[:2] for row in history}) != len(history)
                or len({row.business_key for row in history}) != len(history)
                or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                    or row.strategy_ref.id != strategy.ref.id or row.available_at.clock_ref != invocation.business_time.clock_ref
                    or row.available_at.offset > invocation.business_time.offset for row in history)):
            raise TaskConflict('Learning execution query duplicates or borrows business execution history')
        versions.append(dict(strategy=strategy, state=state, decision=decision, capability=capability, history=history))
    old, current = versions
    first = next((row for row in old['history'] if row.business_key == old['decision'].business_key
        or row.status in {'pending', 'unknown'}), None)
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Learning execution query differs from original first same-business/uncertain execution gate')
    original_decision = read(first.decision_ref, decision_type)
    if (first.decision_sha256 != content_digest(original_decision) or original_decision.business_key != first.business_key
            or original_decision.organization_id != first.organization_id or original_decision.scope != first.scope
            or original_decision.author_organization_id != source['organization_id']
            or original_decision.strategy_ref != first.strategy_ref):
        raise TaskConflict('Learning execution query rewrites original executed decision digest/business identity')
    if (original_decision.available_at.clock_ref != original_context.business_time.clock_ref
            or original_decision.available_at.offset > original_context.business_time.offset):
        raise TaskConflict('Learning execution query introduces a decision unavailable at the original waiting point')
    same_business = first.business_key == old['decision'].business_key
    if same_business and original_decision.model_dump(exclude=_DECISION_METADATA) != old['decision'].model_dump(exclude=_DECISION_METADATA):
        raise TaskConflict('Learning execution query changes original content under the same business identity')
    if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field in ('strategy', 'state', 'decision', 'capability'))
            or old['decision'].model_dump(exclude=_DECISION_METADATA) != current['decision'].model_dump(exclude=_DECISION_METADATA)
            or old['capability'].model_dump(exclude=_SOURCE_METADATA) != current['capability'].model_dump(exclude=_SOURCE_METADATA)
            or old['strategy'].judgments != current['strategy'].judgments
            or raw['learning_profile_ref'] != current_raw['learning_profile_ref'] or raw['feedback_refs'] != current_raw['feedback_refs']
            or any(not {ref.key() for ref in getattr(old['state'], field)} <= {ref.key() for ref in getattr(current['state'], field)}
                for field in ('received_feedback_refs', 'applied_feedback_refs'))
            or not {row.ref.key()[:2] for row in old['history']} <= {row.ref.key()[:2] for row in current['history']}):
        raise TaskConflict('Learning execution query rewrites original business/capability or drops observed history')
    current_by_id = {row.ref.key()[:2]: row for row in current['history']}
    if engineer:
        from src.coordination.engineer_learning_execution_query import preserve_engineer_query_qualifications
        preserve_engineer_query_qualifications(raw, current_raw, old, current, read)
    if qs:
        from src.coordination.qs_learning_execution_query import preserve_qs_query_forecasts
        preserve_qs_query_forecasts(raw, current_raw, old, current, read)
    for before in old['history']:
        after = current_by_id[before.ref.key()[:2]]
        if (before.model_dump(exclude=_SOURCE_METADATA | {'status'}) != after.model_dump(exclude=_SOURCE_METADATA | {'status'})
                or before.status in _TERMINAL and before.status != after.status):
            raise TaskConflict('Learning execution query rewrites retained execution content/disposition')
    if selected.execution_query is None:
        return 'waiting', None
    query = query_type.model_validate(deepcopy(selected.execution_query))
    if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
            or query.organization_id != source['organization_id'] or query.execution_ref != first.ref
            or query.business_key != first.business_key or query.decision_sha256 != first.decision_sha256
            or query.queried_at != context.business_time
            or query.execution.model_dump(exclude=_SOURCE_METADATA | {'status'}) != first.model_dump(exclude=_SOURCE_METADATA | {'status'})
            or query.execution.available_at.clock_ref != context.business_time.clock_ref
            or query.execution.available_at.offset > context.business_time.offset
            or first.status in _TERMINAL and query.execution.status != first.status):
        raise TaskConflict('Learning execution lookup replaces original execution identity/decision or actual observation time')
    if query.execution.status not in _TERMINAL:
        return 'waiting', None
    if terminal:
        if not same_business:
            raise TaskConflict('Only the same original learning business execution can resolve this wait terminally')
    else:
        if same_business:
            return 'waiting', None
        if current_by_id[first.ref.key()[:2]] != query.execution:
            raise TaskConflict('Current learning execution history conflicts with actual native query')
        if any(row.business_key == current['decision'].business_key or row.status not in _TERMINAL for row in current['history']):
            return 'waiting', None
    proof_refs.extend([*query.evidence_refs, *(ref for ref in walk_references(query.execution) if ref.kind == 'Evidence')])
    evidence = {}
    for ref in proof_refs:
        row = reading.resolve(ref)
        if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Learning execution query requires observed original sources and actual query evidence')
        evidence[ref.key()] = row.model_dump(mode='json')
    resolution = dict(schema_version='qs-learning-execution-resolution.v1' if qs else 'engineer-learning-execution-resolution.v1' if engineer else 'architect-learning-execution-resolution.v1', disposition=query.execution.status,
        query=query.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        learning_sources=deepcopy(selected.learning_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
        evidence=list(evidence.values()))
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE,
            terminal_execution=terminal, resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Learning execution query lacks native current authorization and original execution/history authentication')
    return 'ready', resolution


def architect_original_learning_execution_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Learning execution recovery requires guarded sources and native query authentication')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_learning_execution(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ARCHITECT-A12', EXECUTION_CODE, '2', frozenset({'dependency_change'}), evaluate)
