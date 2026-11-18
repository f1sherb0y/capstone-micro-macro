"""Resume private QS cost learning without applying an original pair twice."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, walk_references, ref_type
from src.actions.contracts.qs_learning_objects import (
    QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView, QSLearningExecutionView,
    QSHistoricalCostPlanView, QSReceivedOutcomeView, QSOriginalOutcomeFacts,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'original_qs_cost_error_already_applied'
_FIELDS = frozenset({'scope', 'forecast_refs', 'outcome_refs', 'feedback_refs',
    'comparability_result_ref', 'learning_profile_ref', 'strategy_ref'})


@dataclass(frozen=True)
class QSLearningConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    learning_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None


def qs_original_cost_error_application_profile(read_current, validate_relation):
    """A new sourced pair may be judged while all original applications remain."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS cost learning recovery requires actual sources and native application/history validation')

    def indexed(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('QS learning recovery repeats a physical source identity')
        return result

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A12' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(waited) != 1 or waited[0].kind != 'QSLearningState'):
            raise TaskConflict('QS cost learning recovery replaces its original applied-pair wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSLearningConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS cost learning recovery requires typed current reading and original input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256'] or original_input['scope'] != action_input['scope']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A12'
                    or context.execution_mode != 'llm' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']):
                raise TaskConflict('QS learning recovery changes its original snapshot, scope or current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if context.scope != scope:
                raise TaskConflict('QS learning recovery changes original private learning coverage')
            reading.check_method_context(context, 'QS-A12')
            proof_rows, versions = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('QS learning recovery lacks an exact original/current source')
                proof_rows.append(row)
                return row

            for raw in (original_input, action_input):
                strategy = read(ref_type('Strategy').model_validate(raw['strategy_ref']), QSLearningStrategyView)
                state = read(strategy.learning_state_ref, QSLearningStateView)
                decision = read(strategy.decision_profile_ref, QSLearningDecisionView)
                if (strategy.organization_id != source['organization_id'] or state.organization_id != source['organization_id']
                        or decision.organization_id != source['organization_id'] or state.strategy_ref != strategy.ref
                        or decision.strategy_ref != strategy.ref or state.scope != scope or decision.scope != scope
                        or decision.actor_id != context.actor_id or decision.choice not in {'analyze_error', 'update_judgment'}
                        or len(set(state.applied_error_pair_keys)) != len(state.applied_error_pair_keys)):
                    raise TaskConflict('QS learning recovery substitutes its original private strategy/state or cost-learning choice')
                forecasts = indexed([ref_type('CostPlan').model_validate(ref) for ref in raw['forecast_refs']])
                outcomes = indexed([ref_type('Outcome').model_validate(ref) for ref in raw['outcome_refs']])
                if set(forecasts.values()) != set(state.forecast_refs) or set(outcomes.values()) != set(state.outcome_refs):
                    raise TaskConflict('QS learning recovery omits its complete declared forecast/outcome history')
                forecasts = {key: read(ref, QSHistoricalCostPlanView) for key, ref in forecasts.items()}
                outcomes = {key: read(ref, QSReceivedOutcomeView) for key, ref in outcomes.items()}
                forecast = None if decision.forecast_ref is None else forecasts.get(decision.forecast_ref.key()[:2])
                outcome = None if decision.outcome_ref is None else outcomes.get(decision.outcome_ref.key()[:2])
                if (forecast is None or outcome is None or forecast.ref != decision.forecast_ref
                        or outcome.ref != decision.outcome_ref or outcome.forecast_ref != forecast.ref
                        or forecast.organization_id != source['organization_id']
                        or outcome.recipient_organization_id != source['organization_id']
                        or outcome.forecast_sha256 != content_digest(forecast)):
                    raise TaskConflict('QS learning recovery substitutes its selected original prediction/received-outcome pair')
                facts = QSOriginalOutcomeFacts.model_validate({name: getattr(outcome, name)
                    for name in QSOriginalOutcomeFacts.model_fields})
                executions = {key: read(ref, QSLearningExecutionView) for key, ref in indexed(state.execution_refs).items()}
                if (len({row.business_key for row in executions.values()}) != len(executions)
                        or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                            or row.strategy_ref.key()[:2] != strategy.ref.key()[:2] for row in executions.values())):
                    raise TaskConflict('QS learning recovery repeats or borrows another private business execution')
                versions.append(dict(strategy=strategy, state=state, decision=decision, forecasts=forecasts,
                    outcomes=outcomes, outcome=outcome, pair_key=content_digest(facts), executions=executions))
            old, current = versions
            if (old['state'].ref != waited[0] or old['pair_key'] not in old['state'].applied_error_pair_keys
                    or old['state'].ref.key()[:2] != current['state'].ref.key()[:2]
                    or old['strategy'].ref.key()[:2] != current['strategy'].ref.key()[:2]
                    or not set(old['state'].applied_error_pair_keys) <= set(current['state'].applied_error_pair_keys)):
                raise TaskConflict('QS learning recovery drops original applied pair history or replaces its original state')
            for field in ('forecasts', 'outcomes', 'executions'):
                if not old[field].keys() <= current[field].keys():
                    raise TaskConflict('QS learning recovery drops original prediction, outcome or execution history')
            for key, forecast in old['forecasts'].items():
                if forecast != current['forecasts'][key]:
                    raise TaskConflict('QS learning recovery rewrites an immutable original forecast')
            for key, outcome in old['outcomes'].items():
                after = current['outcomes'][key]
                if (any(getattr(outcome, field) != getattr(after, field) for field in QSOriginalOutcomeFacts.model_fields)
                        or outcome.recipient_organization_id != after.recipient_organization_id):
                    raise TaskConflict('QS learning recovery rewrites known original outcome facts or recipient')
            for key, execution in old['executions'].items():
                after = current['executions'][key]
                if (any(getattr(execution, field) != getattr(after, field) for field in (
                        'organization_id', 'run_id', 'strategy_ref', 'business_key', 'decision_ref', 'decision_sha256'))
                        or execution.status in {'succeeded', 'failed', 'rejected'} and execution.status != after.status):
                    raise TaskConflict('QS learning recovery rewrites an original business execution or known terminal outcome')
            for field in ('received_feedback_refs', 'applied_feedback_refs'):
                if not set(indexed(getattr(old['state'], field))) <= set(indexed(getattr(current['state'], field))):
                    raise TaskConflict('QS learning recovery drops original received/applied feedback history')
            if any(row.business_key == old['decision'].business_key or row.status in {'pending', 'unknown'}
                    for row in old['executions'].values()):
                raise TaskConflict('QS learning original wait precedes cost-error application with another execution query')
            state, decision, outcome = current['state'], current['decision'], current['outcome']
            if (current['pair_key'] in state.applied_error_pair_keys
                    or any(row.business_key == decision.business_key or row.status in {'pending', 'unknown'}
                        for row in current['executions'].values())):
                return 'waiting'
            now = context.business_time
            if (state.as_of != now or state.coverage != 'complete' or outcome.status != 'verified'
                    or outcome.verified.state != 'known' or outcome.verified.value is not True
                    or outcome.received_at.clock_ref != now.clock_ref or outcome.received_at.offset > now.offset
                    or any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or not row.effective_window.contains(now) for row in (current['strategy'], state, decision))):
                return 'unavailable'
            grant, function = reading.resolve(decision.authority_ref), reading.resolve(decision.function_ref)
            if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                    or function.role != 'QS' or function.function_ref != decision.function_ref
                    or decision.function_ref != context.function_ref or decision.authority_ref not in context.authorization_refs
                    or grant.actor_id != context.actor_id or grant.organization_id != source['organization_id']
                    or grant.function_ref != decision.function_ref or 'QS-A12' not in grant.action_ids
                    or not grant.validity.contains(now) or not any(scope_covers(s, scope) for s in grant.scopes)):
                raise TaskConflict('QS learning recovery lacks independently authorized current QS cost judgment')
            proof_refs = [*grant.basis_refs, *function.basis_refs]
            for row in proof_rows:
                proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('QS learning recovery requires observed native prediction/outcome/application evidence')
                evidence[ref.key()] = row.model_dump(mode='json')

            def history(version):
                return {field: [row.model_dump(mode='json') for row in value.values()] if isinstance(value, dict)
                    else value if isinstance(value, str) else value.model_dump(mode='json') for field, value in version.items()}

            if validate_relation(source_identity=deepcopy(source), original_action_input=original_input,
                    action_input=action_input, original_sources=history(old), current_sources=history(current),
                    learning_sources=deepcopy(selected.learning_sources),
                    unavailable_targets=deepcopy(selected.unavailable_targets),
                    evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS cost learning recovery lacks native immutable prediction/new-pair/full application history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A12', _CODE, '1', frozenset({'dependency_change'}), evaluate)
