"""Recover original engineering handover while retaining independent review duties."""
from src.actions.contracts.common import ScopeRef, StrictRecord, ref_type
from src.coordination.architect_transition_conditions import (
    _CODE, _EXECUTION_CODE, _WINDOW_CODE, _ALLOCATION_CODES, _DEPENDENCY_CODE, _CAPACITY_CODE,
    _handover_acceptance_profile, _recall_profile,
)
from src.coordination.architect_transition_allocation_query import _allocation_profile


_CODES = (_CODE, _EXECUTION_CODE, _WINDOW_CODE, *_ALLOCATION_CODES, _DEPENDENCY_CODE, _CAPACITY_CODE)


class _EngineerTransitionInput(StrictRecord):
    scope: ScopeRef
    engagement_ref: ref_type('Engagement')
    transition_basis_ref: ref_type('ServiceTransitionBasis')
    task_refs: list[ref_type('Task')]
    allocation_refs: list[ref_type('ResourceAllocation')]
    deliverable_refs: list[ref_type('Deliverable')]
    residual_obligation_refs: list[ref_type('Obligation')]


def engineer_original_handover_acceptance_profile(read_current, validate_relation):
    return _handover_acceptance_profile(read_current, validate_relation, engineer=True)


def engineer_original_recall_window_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _WINDOW_CODE, engineer=True)


def engineer_original_recall_allocation_profile(read_current, validate_relation):
    return _allocation_profile(read_current, validate_relation, _ALLOCATION_CODES[0], engineer=True)


def engineer_original_handover_allocation_profile(read_current, validate_relation):
    return _allocation_profile(read_current, validate_relation, _ALLOCATION_CODES[1], engineer=True)


def engineer_original_recall_dependency_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _DEPENDENCY_CODE, engineer=True)


def engineer_original_recall_capacity_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _CAPACITY_CODE, engineer=True)
