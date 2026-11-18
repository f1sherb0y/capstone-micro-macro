"""Recover Engineer unchanged-judgment waits with independent qualification gates."""
from copy import deepcopy

from src.coordination.architect_learning_applied_feedback import JUDGMENT_CODE, check_applied_feedback
from src.coordination.continuations import ConditionProfile


def engineer_original_judgment_change_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Engineer judgment-change recovery requires guarded sources and independent native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_applied_feedback(check, selected, validate_relation, judgment_change=True, engineer=True)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ENGINEER-A12', JUDGMENT_CODE, '1', frozenset({'dependency_change'}), evaluate)
