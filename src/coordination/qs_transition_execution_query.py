"""Authenticate actual original QS service execution queries."""
from copy import deepcopy

from src.coordination.architect_transition_execution_query import (
    EXECUTION_CODE, ArchitectTransitionExecutionQueryRecord, check_transition_execution,
)
from src.coordination.continuations import ConditionProfile


class QSTransitionExecutionQueryRecord(ArchitectTransitionExecutionQueryRecord):
    """Actual original QS execution retaining run/business/basis identity."""


def check_qs_transition_execution(check, selected, validate_relation, *, terminal=False):
    return check_transition_execution(check, selected, validate_relation, terminal=terminal, qs=True)


def qs_original_transition_execution_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS service execution query requires guarded sources and native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_qs_transition_execution(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('QS-A11', EXECUTION_CODE, '2', frozenset({'dependency_change'}), evaluate)
