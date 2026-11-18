"""Recover Engineer training dependencies without changing issuer qualifications."""
from src.actions.contracts.common import ScopeRef, StrictRecord, ref_type
from src.actions.roles.engineer_learning import prepare_engineer_training_estimate_input
from src.coordination.architect_learning_conditions import ArchitectLearningConditionReading, _original_training_profile, _CAPACITY_CODE
from src.coordination.tasks import TaskConflict
from src.coordination.engineer_learning_execution_query import EXECUTION_CODE
from src.coordination.engineer_learning_applied_feedback import APPLIED_CODE
from src.coordination.architect_learning_applied_feedback import JUDGMENT_CODE
from src.coordination.engineer_qualification_conditions import QUALIFICATION_CODE


_CODE = 'training_dependency_not_ready'
_CODES = (_CODE, EXECUTION_CODE, _CAPACITY_CODE, APPLIED_CODE, JUDGMENT_CODE, QUALIFICATION_CODE)
EngineerLearningConditionReading = ArchitectLearningConditionReading


class _EngineerLearningInput(StrictRecord):
    scope: ScopeRef
    strategy_ref: ref_type('Strategy')
    qualification_refs: list[ref_type('Qualification')]
    feedback_refs: list[ref_type('Feedback')]
    learning_profile_ref: ref_type('LearningProfile') | None


def validate_engineer_training_qualifications(raw, context, reading, state, capability, work):
    """Reuse the original issuer/qualification gates without running training or a method."""
    action_input = _EngineerLearningInput.model_validate(raw)
    if (action_input.qualification_refs != state.qualification_refs
            or {ref.key() for ref in action_input.qualification_refs} != {ref.key() for ref in capability.qualification_refs}):
        raise TaskConflict('Engineer training recovery changes complete original credential inputs')
    prepared = prepare_engineer_training_estimate_input(context, action_input, reading)
    if prepared['kind'] != 'prepared' or prepared['input'] != work.data:
        raise TaskConflict('Engineer training recovery bypasses original issuer/qualification or training preparation gates')


def engineer_original_training_dependency_profile(read_current, validate_relation):
    return _original_training_profile(read_current, validate_relation, _CODE, engineer=True)


def engineer_original_training_capacity_profile(read_current, validate_relation):
    """Require original shortfall and actual current capacity without altering credentials."""
    return _original_training_profile(read_current, validate_relation, _CAPACITY_CODE, engineer=True)
