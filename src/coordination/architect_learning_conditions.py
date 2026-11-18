"""Recover an original private Architect training dependency without granting capability."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, ref_type, walk_references
from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningStrategyView, ArchitectLearningStateView, ArchitectLearningDecisionView,
    ArchitectLearningCapabilityView, ArchitectLearningProfileView, ArchitectLearningFeedbackView,
    ArchitectTrainingProfileView, ArchitectTrainingWorkView, ArchitectTrainingEstimateView,
    ArchitectTrainingAuthorityView, ArchitectTrainingDependencyView, ArchitectLearningExecutionView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination.architect_learning_execution_query import EXECUTION_CODE
from src.coordination.architect_learning_applied_feedback import APPLIED_CODE, JUDGMENT_CODE
from src.methods.architect_learning import TRAINING_METHOD
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'training_dependency_not_ready'
_CAPACITY_CODE = 'training_investment_capacity_unavailable'
_CODES = (_CODE, EXECUTION_CODE, _CAPACITY_CODE, APPLIED_CODE, JUDGMENT_CODE)
_FIELDS = frozenset({'scope', 'strategy_ref', 'capability_ref', 'feedback_refs', 'learning_profile_ref'})


@dataclass(frozen=True)
class ArchitectLearningConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    original_context: ActionContext
    learning_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None
    execution_query: dict | None = None
    applied_feedback_query: dict | None = None
    qualification_application_query: dict | None = None


def architect_original_training_dependency_profile(read_current, validate_relation):
    return _original_training_profile(read_current, validate_relation, _CODE)


def architect_original_training_capacity_profile(read_current, validate_relation):
    return _original_training_profile(read_current, validate_relation, _CAPACITY_CODE)


def _original_training_profile(read_current, validate_relation, condition_code, *, engineer=False, qs=False):
    action_id, role = ('ENGINEER-A12', 'Engineer') if engineer else ('ARCHITECT-A12', 'Architect')
    fields = frozenset({'scope', 'strategy_ref', 'qualification_refs', 'feedback_refs', 'learning_profile_ref'}) if engineer else _FIELDS
    strategy_type, state_type, decision_type, execution_type = (
        ArchitectLearningStrategyView, ArchitectLearningStateView, ArchitectLearningDecisionView, ArchitectLearningExecutionView)
    if engineer:
        from src.actions.contracts.engineer_learning_objects import (
            EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView, EngineerLearningExecutionView,
        )
        strategy_type, state_type, decision_type, execution_type = (
            EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView, EngineerLearningExecutionView)
    if qs:
        if engineer:
            raise TaskConflict('Training recovery requires one original role route')
        from src.actions.contracts.qs_learning_objects import (
            QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView, QSLearningExecutionView,
        )
        from src.coordination.qs_training_conditions import QS_TRAINING_FIELDS
        action_id, role, fields = 'QS-A12', 'QS', QS_TRAINING_FIELDS
        strategy_type, state_type, decision_type, execution_type = (
            QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView, QSLearningExecutionView)
    capacity_wait = condition_code == _CAPACITY_CODE
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Architect training recovery requires actual private sources and native validation')

    def physical(value):
        if isinstance(value, dict):
            return {key: physical(item) for key, item in value.items()
                if not (key == 'version' and set(value) == {'kind', 'id', 'version'})}
        if isinstance(value, list):
            return [physical(item) for item in value]
        return value

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Architect training recovery duplicates a physical private source')
        return keys

    def true(state):
        return isinstance(state, Known) and state.value is True

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != (('Authority',) if capacity_wait else ('Dependency',))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Architect training recovery replaces original dependency wait/firm/action')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, ArchitectLearningConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.original_context, ActionContext) or not isinstance(selected.reading, ActionReadView)):
            raise TaskConflict('Architect training recovery requires typed original/current invocation sources')
        reading, context = selected.reading, selected.context.model_copy(deep=True)
        raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(raw) != fields or set(current_raw) != fields or task_digest(raw) != source['input_sha256']
                    or task_digest(selected.original_context.model_dump(mode='json')) != source['context_sha256']
                    or raw['scope'] != current_raw['scope'] or context.scope != selected.original_context.scope
                    or context.run_id != source['run_id'] or context.contract_ref.id != action_id
                    or context.execution_mode != 'llm' or context.operation_id == source['request_id']
                    or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time
                    or context.business_time.clock_ref != selected.original_context.business_time.clock_ref
                    or context.business_time.offset < selected.original_context.business_time.offset):
                raise TaskConflict('Architect training recovery changes original scope/snapshot or current invocation')
            reading.check_method_context(context, action_id)
            versions, proof_rows, proof_refs, capacity_snapshots = [], [], [], []

            def read(ref, schema, *, linked=False):
                row = reading.resolve(ref)
                if (not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref
                        or not linked and not scope_covers(context.scope, row.scope)):
                    raise TaskConflict('Architect training recovery lacks exact private scoped source versions')
                proof_rows.append(row)
                return row

            for action_input, invocation in ((raw, selected.original_context), (current_raw, context)):
                strategy = read(ref_type('Strategy').model_validate(action_input['strategy_ref']), strategy_type)
                state = read(strategy.learning_state_ref, state_type)
                decision = read(strategy.decision_profile_ref, decision_type)
                capability = read(state.capability_ref if engineer or qs else ref_type('Capability').model_validate(action_input['capability_ref']), ArchitectLearningCapabilityView)
                if action_input['learning_profile_ref'] is None or decision.training_profile_ref is None:
                    raise TaskConflict('Architect training recovery loses original learning/training declaration')
                profile = read(ref_type('LearningProfile').model_validate(action_input['learning_profile_ref']), ArchitectLearningProfileView)
                training = read(decision.training_profile_ref, ArchitectTrainingProfileView)
                authority = read(training.authority_ref, ArchitectTrainingAuthorityView)
                request = training.request
                if (any(row.organization_id != source['organization_id'] for row in (strategy, state, decision, capability, profile, training, authority))
                        or state.strategy_ref != strategy.ref or state.capability_ref != capability.ref
                        or state.learning_profile_ref != profile.ref or state.as_of != invocation.business_time or state.coverage != 'complete'
                        or decision.strategy_ref != strategy.ref or decision.choice != 'propose_training'
                        or decision.actor_id != invocation.actor_id or decision.function_ref != invocation.function_ref
                        or profile.strategy_ref != strategy.ref or not true(profile.enabled)
                        or training.ref not in profile.training_profile_refs or training.learning_profile_ref != profile.ref
                        or training.capability_ref != capability.ref or capability.status != 'current'
                        or request.scope != invocation.scope or request.work_profile_ref is None
                        or request.authority_basis_refs != [authority.ref] or authority.training_profile_ref != training.ref
                        or authority.capability_ref != capability.ref or authority.actor_id != invocation.actor_id
                        or authority.function_ref != invocation.function_ref or authority.as_of != invocation.business_time
                        or authority.coverage != 'complete' or not true(authority.permitted)):
                    raise TaskConflict('Architect training recovery changes original private strategy/capability/request or independent permission')
                grant, function = reading.resolve(decision.authority_ref), reading.resolve(invocation.function_ref)
                if (decision.authority_ref not in invocation.authorization_refs or not isinstance(grant, Authorization)
                        or grant.ref != decision.authority_ref or not isinstance(function, RoleAssignment)
                        or function.function_ref != invocation.function_ref or function.role != role
                        or grant.actor_id != invocation.actor_id or grant.organization_id != source['organization_id']
                        or grant.function_ref != invocation.function_ref or action_id not in grant.action_ids
                        or not grant.validity.contains(invocation.business_time)
                        or not any(scope_covers(covered, invocation.scope) for covered in grant.scopes)):
                    raise TaskConflict('Architect training recovery lacks original/current private working authority')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])
                refs = [ref_type('Feedback').model_validate(ref) for ref in action_input['feedback_refs']]
                if ({ref.key() for ref in refs} != {ref.key() for ref in decision.feedback_refs}
                        or not {ref.key() for ref in refs} <= {ref.key() for ref in state.received_feedback_refs}):
                    raise TaskConflict('Architect training recovery replaces actually received private feedback')
                identities(refs)
                feedback = [read(ref, ArchitectLearningFeedbackView) for ref in refs]
                executions = [read(ref, execution_type) for ref in state.execution_refs]
                identities(state.execution_refs)
                if (len({row.business_key for row in executions}) != len(executions)
                        or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                            or row.strategy_ref.key()[:2] != strategy.ref.key()[:2] for row in executions)):
                    raise TaskConflict('Architect training recovery borrows or duplicates private execution history')
                if any(row.business_key == decision.business_key or row.status in {'pending', 'unknown'} for row in executions):
                    raise TaskConflict('Architect training dependency recovery bypasses the original execution-query gate')
                work = read(request.work_profile_ref, ArchitectTrainingWorkView)
                if engineer:
                    from src.coordination.engineer_learning_conditions import validate_engineer_training_qualifications
                    validate_engineer_training_qualifications(action_input, invocation, reading, state, capability, work)
                if qs:
                    from src.coordination.qs_training_conditions import validate_qs_training_sources
                    validate_qs_training_sources(action_input, invocation, reading, state, work)
                estimate = read(training.estimate_ref, ArchitectTrainingEstimateView)
                if (work.organization_id != source['organization_id'] or work.training_profile_ref != training.ref
                        or work.calculation_method_ref != TRAINING_METHOD or not true(work.supported)
                        or estimate.organization_id != source['organization_id'] or estimate.work_profile_ref != work.ref
                        or estimate.input_sha256 != content_digest(work.data) or estimate.status != 'ok' or estimate.report is None
                        or estimate.executed_at.clock_ref != invocation.business_time.clock_ref
                        or estimate.executed_at.offset > estimate.authored_at.offset
                        or not isinstance(request.effort_estimate, Known) or request.effort_estimate.value != estimate.report.effort):
                    raise TaskConflict('Architect training recovery rewrites original sourced work/effort/cost estimate')
                costs = [authority.budget_limit, authority.actual_spent, authority.reserved_cost, estimate.report.estimated_cost]
                if (len({row.currency for row in costs}) != 1 or any(decimal_fraction(row.value) < 0 for row in costs)
                        or authority.available_effort.unit != estimate.report.effort.unit or decimal_fraction(authority.available_effort.value) < 0):
                    raise TaskConflict('Architect training recovery changes original budget/effort units or sourced capacity')
                available = decimal_fraction(authority.budget_limit.value) - decimal_fraction(authority.actual_spent.value) - decimal_fraction(authority.reserved_cost.value)
                insufficient = (decimal_fraction(estimate.report.estimated_cost.value) > available
                    or decimal_fraction(estimate.report.effort.value) > decimal_fraction(authority.available_effort.value))
                if action_input is raw and capacity_wait:
                    if tuple(check.condition.object_refs) != (authority.ref,) or not insufficient:
                        raise TaskConflict('Architect training capacity wait differs from its original authority/actual shortfall')
                elif insufficient:
                    if action_input is raw:
                        raise TaskConflict('Architect training dependency wait bypasses original investment-capacity gate')
                    return 'waiting'
                capacity_snapshots.append(dict(authority=authority.model_dump(mode='json'),
                    estimate=estimate.model_dump(mode='json'), insufficient=insufficient))
                if not isinstance(request.desired_window, Known) and not capacity_wait:
                    raise TaskConflict('Architect training recovery loses original future authorized window')
                if isinstance(request.desired_window, Known):
                    window = request.desired_window.value
                    if (any(point.clock_ref != invocation.business_time.clock_ref for point in
                            (window.start, window.end, authority.allowed_window.start, authority.allowed_window.end))
                            or window.start.offset < invocation.business_time.offset
                            or window.bounds != 'closed_open' or window.end.offset <= window.start.offset
                            or authority.allowed_window.bounds != 'closed_open'
                            or window.start.offset < authority.allowed_window.start.offset or window.end.offset > authority.allowed_window.end.offset):
                        if action_input is raw and not capacity_wait:
                            raise TaskConflict('Original training wait has no authorized future window')
                        if action_input is not raw or not capacity_wait:
                            return 'waiting'
                # An unknown original window stays unknown. Resolving capacity
                # permits another judgment, whose original processor requests
                # the missing window before proposing any training.
                identities(request.dependency_refs)
                # Capacity waits occur before dependency reads. Preserve every
                # actually observed dependency; later missing sources stay
                # explicit in the reader's unavailable_targets for native checks.
                dependencies = [read(ref, ArchitectTrainingDependencyView) for ref in request.dependency_refs
                    if not capacity_wait or ref.key() in reading._resolver._objects]
                if any(row.training_profile_ref != training.ref for row in dependencies):
                    raise TaskConflict('Architect training recovery borrows another training dependency')
                proof_refs.extend([authority.budget_limit.basis_ref, authority.actual_spent.basis_ref,
                    authority.reserved_cost.basis_ref, authority.available_effort.basis_ref,
                    work.data.per_participant_effort.basis_ref, work.data.cost_per_effort.basis_ref, work.data.fixed_cost.basis_ref])
                versions.append(dict(strategy=strategy, state=state, decision=decision, capability=capability,
                    profile=profile, training=training, authority=authority, work=work, estimate=estimate,
                    dependencies=dependencies, feedback=feedback))
            old, current = versions
            if qs:
                from src.coordination.qs_learning_execution_query import preserve_qs_query_forecasts
                preserve_qs_query_forecasts(raw, current_raw, old, current,
                    lambda ref, schema: read(ref, schema, linked=True), exact_inputs=False)
            first = next((row.ref for row in old['dependencies'] if not true(row.satisfied)), None)
            if not capacity_wait and tuple(check.condition.object_refs) != (first,):
                raise TaskConflict('Architect training recovery differs from original first unresolved dependency')
            if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field in old if field not in {'dependencies', 'feedback'})
                    or physical(old['training'].request.model_dump(mode='json')) != physical(current['training'].request.model_dump(mode='json'))
                    or old['decision'].business_key != current['decision'].business_key
                    or old['strategy'].judgments != current['strategy'].judgments
                    or old['decision'].interpretation != current['decision'].interpretation
                    or old['capability'].verified_capability_codes != current['capability'].verified_capability_codes
                    or identities(old['capability'].qualification_refs) != identities(current['capability'].qualification_refs)
                    or engineer and (old['state'].qualification_refs != current['state'].qualification_refs
                        or old['state'].applied_qualification_event_refs != current['state'].applied_qualification_event_refs)
                    or old['work'].data != current['work'].data or old['estimate'].report != current['estimate'].report
                    or old['estimate'].executed_at != current['estimate'].executed_at
                    or any(identities(getattr(old['state'], field)) - identities(getattr(current['state'], field))
                        for field in ('received_feedback_refs', 'applied_feedback_refs', 'execution_refs'))
                    or [row.model_dump(exclude={'ref'}) for row in old['feedback']] != [row.model_dump(exclude={'ref'}) for row in current['feedback']]):
                raise TaskConflict('Architect training recovery rewrites original request, capability, work or feedback/application history')
            current_dependencies = {row.ref.key()[:2]: row for row in current['dependencies']}
            for before in old['dependencies']:
                after = current_dependencies.get(before.ref.key()[:2])
                if after is None:
                    if true(before.satisfied):
                        return 'unavailable'
                    continue
                if before.scope != after.scope or true(before.satisfied) and not true(after.satisfied):
                    raise TaskConflict('Architect training recovery rewrites already satisfied dependency history')
            required_current = [current['training'], current['authority'], current['work']]
            if not capacity_wait:
                target = next(row for row in current['dependencies'] if row.ref.key()[:2] == first.key()[:2])
                if not true(target.satisfied):
                    return 'waiting'
                required_current.append(target)
            if any(row.available_at.clock_ref != context.business_time.clock_ref or row.available_at.offset > context.business_time.offset
                    or not row.effective_window.contains(context.business_time)
                    for row in required_current):
                return 'unavailable'
            result = reading.calculate(TRAINING_METHOD, current['work'].data)
            if result.kind != 'ok':
                return 'unavailable'
            if result.value != current['estimate'].report:
                raise TaskConflict('Architect training recovery conflicts with original actual method estimate')
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Architect training recovery requires observed original request/authority/dependency evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            capacity_proof = {'capacity_snapshots': deepcopy(capacity_snapshots)} if capacity_wait else {}
            if validate_relation(source_identity=deepcopy(source), condition_code=condition_code, original_action_input=raw,
                    action_input=current_raw, original_context=selected.original_context.model_dump(mode='json'),
                    learning_sources=deepcopy(selected.learning_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                    evidence=list(evidence.values()), context=context.model_copy(deep=True), reading=reading,
                    **capacity_proof) is not True:
                raise TaskConflict('Architect training recovery lacks native actual original wait and preserved private history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile(action_id, condition_code, '1', frozenset({'dependency_change'}), evaluate)
