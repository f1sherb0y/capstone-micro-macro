"""Service transitions retain authorship, licensed uses and residual obligations."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.actions.contracts.qs_cost_objects import CostSource
from src.methods.capacity import CapacityCommitment


class ArchitectTransitionEngagementView(CostSource):
    ref: ref_type('Engagement')
    organization_id: TextId
    client_id: TextId
    task_refs: list[ref_type('Task')]
    allocation_refs: list[ref_type('ResourceAllocation')]
    usable_deliverable_refs: list[ref_type('Deliverable')]
    residual_obligation_refs: list[ref_type('Obligation')]
    execution_refs: list[ref_type('ServiceTransitionExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class ArchitectRecallItem(StrictRecord):
    task_ref: ref_type('Task')
    resource_ids: list[TextId]
    window: TimeWindow
    effort: Measured
    dependency_refs: list[ref_type('Dependency')]
    existing_allocation_ref: ref_type('ResourceAllocation') | None


class ArchitectRecallPlan(StrictRecord):
    work_profile_ref: ref_type('WorkProfile')
    items: list[ArchitectRecallItem]


class ArchitectTransitionPackage(StrictRecord):
    engagement_ref: ref_type('Engagement')
    recipient_ids: list[TextId]
    deliverable_refs: list[ref_type('Deliverable')]
    access_basis_refs: list[ref_type('AccessBasis')]
    release_allocation_refs: list[ref_type('ResourceAllocation')]
    retain_allocation_refs: list[ref_type('ResourceAllocation')]
    remaining_task_refs: list[ref_type('Task')]
    remaining_obligation_refs: list[ref_type('Obligation')]
    basis_ref: ref_type('ServiceTransitionBasis')


class ArchitectTransitionBasisView(GovReviewAuthored):
    ref: ref_type('ServiceTransitionBasis')
    engagement_ref: ref_type('Engagement')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['pause','recall','handover','exit']
    permitted: ValueState[bool]
    business_key: TextId
    selected_task_refs: list[ref_type('Task')]
    recall_plan: ArchitectRecallPlan | None
    package: ArchitectTransitionPackage | None
    recipient_acceptance_refs: list[ref_type('HandoverAcceptance')]
    defer_until: TimePoint | None
    note: TextId


class ArchitectTransitionTaskView(GovReviewAuthored):
    ref: ref_type('Task')
    engagement_ref: ref_type('Engagement')
    organization_id: TextId
    work_profile_ref: ref_type('WorkProfile')
    remaining_effort: ValueState[Measured]
    method_remaining_effort: ValueState[Measured]
    function_code: TextId
    resource_effort_shares: dict[TextId,DecimalString]
    dependency_refs: list[ref_type('Dependency')]
    allocation_ref: ref_type('ResourceAllocation') | None
    permitted: ValueState[bool]
    status: Literal['active','paused','waiting','complete','cancelled']


class ArchitectTransitionAllocationView(CostSource):
    ref: ref_type('ResourceAllocation')
    engagement_ref: ref_type('Engagement')
    organization_id: TextId
    task_ref: ref_type('Task')
    commitment_refs: list[ref_type('ResourceCommitment')]
    physical_allocation_key: TextId
    release_permission_ref: ref_type('AllocationReleasePermission')
    status: Literal['held','released','unknown']
    as_of: TimePoint


class ArchitectAllocationReleaseView(GovReviewAuthored):
    ref: ref_type('AllocationReleasePermission')
    allocation_ref: ref_type('ResourceAllocation')
    permitted: ValueState[bool]
    effect: Literal['after_actual_transition_only']


class ArchitectTransitionDeliverableView(GovReviewAuthored):
    ref: ref_type('Deliverable')
    engagement_ref: ref_type('Engagement')
    content_sha256: Digest
    historical_author_id: TextId
    rights_controller_organization_id: TextId
    existing_use_right_refs: list[ref_type('DeliverableUseRight')]
    status: Literal['available','unavailable','unknown']


class ArchitectTransitionAccessView(GovReviewAuthored):
    ref: ref_type('AccessBasis')
    deliverable_ref: ref_type('Deliverable')
    recipient_id: TextId
    permitted: ValueState[bool]
    content_kind: Literal['licensed_deliverable_only']


class ArchitectExistingUseRightView(GovReviewAuthored):
    ref: ref_type('DeliverableUseRight')
    deliverable_ref: ref_type('Deliverable')
    holder_id: TextId
    permitted: ValueState[bool]


class ArchitectHandoverAcceptanceView(GovReviewAuthored):
    ref: ref_type('HandoverAcceptance')
    engagement_ref: ref_type('Engagement')
    package_sha256: Digest
    recipient_id: TextId
    accepted: ValueState[bool]
    independent_review_scope: ScopeRef


class ArchitectRecallResourceView(CostSource):
    ref: ref_type('ResourcePool')
    organization_id: TextId
    personnel_ids: list[TextId]
    function_codes: list[TextId]
    qualified: ValueState[bool]
    total: Measured
    region_id: TextId
    effort_per_capacity_tick: Measured


class ArchitectRecallWorkProfileView(GovReviewAuthored):
    ref: ref_type('WorkProfile')
    engagement_ref: ref_type('Engagement')
    organization_id: TextId
    resources: list[ArchitectRecallResourceView]
    commitments: list[CapacityCommitment]
    commitment_allocation_refs: dict[TextId, ref_type('ResourceAllocation')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint
    method: Literal['constant_capacity_over_half_open_window_v1']


class ArchitectRecallDependencyView(CostSource):
    ref: ref_type('Dependency')
    task_ref: ref_type('Task')
    predecessor_task_ref: ref_type('Task') | None
    satisfied: ValueState[bool]


class ArchitectTransitionExecutionView(CostSource):
    ref: ref_type('ServiceTransitionExecution')
    engagement_ref: ref_type('Engagement')
    organization_id: TextId
    run_id: TextId
    business_key: TextId
    basis_ref: ref_type('ServiceTransitionBasis')
    basis_sha256: Digest
    status: Literal['pending','unknown','succeeded','failed','rejected']


def architect_transition_types():
    return {
        'Engagement':ArchitectTransitionEngagementView,'ServiceTransitionBasis':ArchitectTransitionBasisView,
        'Task':ArchitectTransitionTaskView,'ResourceAllocation':ArchitectTransitionAllocationView,
        'AllocationReleasePermission':ArchitectAllocationReleaseView,'Deliverable':ArchitectTransitionDeliverableView,
        'AccessBasis':ArchitectTransitionAccessView,'DeliverableUseRight':ArchitectExistingUseRightView,
        'HandoverAcceptance':ArchitectHandoverAcceptanceView,'WorkProfile':ArchitectRecallWorkProfileView,
        'ResourcePool':ArchitectRecallResourceView,'Dependency':ArchitectRecallDependencyView,
        'ServiceTransitionExecution':ArchitectTransitionExecutionView,'Obligation':OwnerPaymentObligationView,
    }


def architect_transition_schemas():
    return contractor_bid_schemas(architect_transition_types())
