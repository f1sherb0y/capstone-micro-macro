"""Recover independent QS handover without transferring private client records."""
from src.actions.contracts.common import ScopeRef, StrictRecord, ref_type
from src.coordination.architect_transition_conditions import (
    _CODE, _EXECUTION_CODE, _WINDOW_CODE, _ALLOCATION_CODES, _DEPENDENCY_CODE, _CAPACITY_CODE,
    _handover_acceptance_profile, _recall_profile, _physical,
)
from src.coordination.architect_transition_allocation_query import _allocation_profile
from src.coordination.tasks import TaskConflict


_CODES = (_CODE, _EXECUTION_CODE, _WINDOW_CODE, *_ALLOCATION_CODES, _DEPENDENCY_CODE, _CAPACITY_CODE)


class _QSTransitionInput(StrictRecord):
    scope: ScopeRef
    engagement_ref: ref_type('Engagement')
    transition_basis_ref: ref_type('ServiceTransitionBasis')
    task_refs: list[ref_type('Task')]
    allocation_refs: list[ref_type('ResourceAllocation')]
    deliverable_refs: list[ref_type('Deliverable')]
    residual_obligation_refs: list[ref_type('Obligation')]


def qs_original_handover_acceptance_profile(read_current, validate_relation):
    return _handover_acceptance_profile(read_current, validate_relation, qs=True)


def qs_original_recall_window_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _WINDOW_CODE, qs=True)


def qs_original_recall_allocation_profile(read_current, validate_relation):
    return _allocation_profile(read_current, validate_relation, _ALLOCATION_CODES[0], qs=True)


def qs_original_handover_allocation_profile(read_current, validate_relation):
    return _allocation_profile(read_current, validate_relation, _ALLOCATION_CODES[1], qs=True)


def qs_original_recall_dependency_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _DEPENDENCY_CODE, qs=True)


def qs_original_recall_capacity_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _CAPACITY_CODE, qs=True)


def _preserve_qs_transition_links(before, after, reading, *, field, metadata):
    fields = ('work_estimate_ref',) if field == 'task_refs' else (
        'price_source_refs', 'measurement_trace_refs') if field == 'deliverable_refs' else (
        'contract_ref',) if field == 'residual_obligation_refs' else ()
    for name in fields:
        previous_refs, current_refs = getattr(before, name), getattr(after, name)
        previous_refs = previous_refs if isinstance(previous_refs, list) else [previous_refs]
        current_refs = current_refs if isinstance(current_refs, list) else [current_refs]
        current_by_id = {ref.key()[:2]: ref for ref in current_refs}
        if len(current_by_id) != len(current_refs) or {ref.key()[:2] for ref in previous_refs} != set(current_by_id):
            raise TaskConflict('QS transition recovery drops or aliases original estimate/source/contract')
        for ref in previous_refs:
            current_ref = current_by_id[ref.key()[:2]]
            if current_ref == ref:
                continue
            previous, current = reading.resolve(ref), reading.resolve(current_ref)
            if _physical(previous.model_dump(mode='json', exclude=metadata)) != _physical(current.model_dump(mode='json', exclude=metadata)):
                raise TaskConflict('QS transition recovery rewrites original quantity/price/estimate or debt contract')
