"""Recover QS private feedback and unchanged judgments while retaining original prediction history."""
from copy import deepcopy
from pydantic import Field

from src.actions.contracts.common import ResumeCondition, ref_type
from src.actions.roles.qs_learning import prepare_qs_learning_assessment_input
from src.coordination.architect_learning_applied_feedback import (
    APPLIED_CODE, JUDGMENT_CODE, ArchitectAppliedFeedbackQueryRecord, check_applied_feedback,
)
from src.coordination.qs_learning_execution_query import preserve_qs_query_forecasts
from src.coordination.qs_training_conditions import _QSTrainingInput
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


class QSAppliedFeedbackQueryRecord(ArchitectAppliedFeedbackQueryRecord):
    original_state_ref: ref_type('QSLearningState')
    current_state_ref: ref_type('QSLearningState')
    application_execution_refs: list[ref_type('QSLearningExecution')] = Field(min_length=1)


def preserve_qs_feedback_history(raw, current_raw, old, current, read, selected, *, terminal=False, judgment_change=False):
    preserve_qs_query_forecasts(raw, current_raw, old, current, read,
        exact_inputs=False, preserve_comparability=False)
    if judgment_change:
        # The shared judgment checker reconstructs both exact QS assessment
        # inputs and independently verifies their saved reports below.
        return 'ready'
    original = prepare_qs_learning_assessment_input(selected.original_context, _QSTrainingInput.model_validate(raw), selected.reading)
    if original['kind'] != 'deferred':
        raise TaskConflict('QS applied-feedback wait bypasses original forecast/comparable-error/application gates')
    condition = ResumeCondition.model_validate(original['resume_condition'])
    if (condition.condition_code != APPLIED_CODE or condition.trigger != 'dependency_change'
            or tuple(condition.object_refs) != (old['state'].ref,)):
        raise TaskConflict('QS applied-feedback wait differs from its original received/applied feedback state')
    if not terminal:
        prepared = prepare_qs_learning_assessment_input(selected.context, _QSTrainingInput.model_validate(current_raw), selected.reading)
        if prepared['kind'] != 'prepared':
            return 'waiting'
    return 'ready'


def check_qs_applied_feedback(check, selected, validate_relation, *, terminal=False):
    return check_applied_feedback(check, selected, validate_relation, terminal=terminal, qs=True)


def _qs_feedback_profile(read_current, validate_relation, *, judgment_change=False):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS feedback recovery requires guarded sources and independent native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_applied_feedback(check, selected, validate_relation, judgment_change=judgment_change, qs=True)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('QS-A12', JUDGMENT_CODE if judgment_change else APPLIED_CODE, '1',
        frozenset({'dependency_change'}), evaluate)


def qs_original_applied_feedback_profile(read_current, validate_relation):
    return _qs_feedback_profile(read_current, validate_relation)


def qs_original_judgment_change_profile(read_current, validate_relation):
    return _qs_feedback_profile(read_current, validate_relation, judgment_change=True)
