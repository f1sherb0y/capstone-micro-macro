"""Recover original QS training waits while preserving private forecast and cost-error history."""
from src.actions.contracts.common import ScopeRef, StrictRecord, ref_type
from src.actions.roles.qs_learning import prepare_qs_training_estimate_input
from src.coordination.architect_learning_conditions import _original_training_profile, _CODE, _CAPACITY_CODE
from src.coordination.tasks import TaskConflict


QS_TRAINING_FIELDS = frozenset({'scope', 'strategy_ref', 'forecast_refs', 'outcome_refs',
    'comparability_result_ref', 'feedback_refs', 'learning_profile_ref'})


class _QSTrainingInput(StrictRecord):
    scope: ScopeRef
    strategy_ref: ref_type('Strategy')
    forecast_refs: list[ref_type('CostPlan')]
    outcome_refs: list[ref_type('Outcome')]
    comparability_result_ref: ref_type('MethodResult') | None
    feedback_refs: list[ref_type('Feedback')]
    learning_profile_ref: ref_type('LearningProfile') | None


def validate_qs_training_sources(raw, context, reading, state, work):
    """Reuse the original prediction/access/author gates before training investment or scheduling."""
    action_input = _QSTrainingInput.model_validate(raw)
    if (set(action_input.forecast_refs) != set(state.forecast_refs)
            or set(action_input.outcome_refs) != set(state.outcome_refs)):
        raise TaskConflict('QS training recovery changes the complete original forecast/outcome inputs')
    prepared = prepare_qs_training_estimate_input(context, action_input, reading)
    if prepared['kind'] != 'prepared' or prepared['input'] != work.data:
        raise TaskConflict('QS training recovery bypasses original prediction, lawful outcome access or work preparation gates')


def qs_original_training_dependency_profile(read_current, validate_relation):
    return _original_training_profile(read_current, validate_relation, _CODE, qs=True)


def qs_original_training_capacity_profile(read_current, validate_relation):
    return _original_training_profile(read_current, validate_relation, _CAPACITY_CODE, qs=True)
