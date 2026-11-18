"""Authenticate actual original engineering service execution queries."""
from copy import deepcopy

from src.coordination.architect_transition_execution_query import (
    EXECUTION_CODE, ArchitectTransitionExecutionQueryRecord, check_transition_execution,
)
from src.coordination.continuations import ConditionProfile


class EngineerTransitionExecutionQueryRecord(ArchitectTransitionExecutionQueryRecord):
    """Actual original engineering execution with retained basis/run/business digest."""


def check_engineer_transition_execution(check, selected, validate_relation, *, terminal=False):
    return check_transition_execution(check, selected, validate_relation, terminal=terminal, engineer=True)


def engineer_original_transition_execution_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Engineering service query requires guarded history and native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_engineer_transition_execution(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ENGINEER-A11', EXECUTION_CODE, '2', frozenset({'dependency_change'}), evaluate)
