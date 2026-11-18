"""Scoped remedies preserve original consumption, ownership and money histories."""
from typing import Literal

from src.actions.contracts.common import Measured, Money, ScopeRef, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_planning_objects import (
    SupplierPlannedTask, SupplierPlanningMethodView, SupplierPlanningResourceView, QuoteProductLine,
    SupplierInventoryAllocationView, SupplierPlanningRequirementView, SupplierWorkAuthorityView, QuoteInventoryView,
)
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView, SupplierVisibleDefectView, SupplierQualityEvidenceView
from src.methods.supplier_payment import SupplierClaimAmountInput, SupplierClaimAmountReport


class SupplierRemedyOrderView(CostSource):
    ref: ref_type('Order')
    supplier_id: TextId
    buyer_id: TextId
    currency: TextId
    line_refs: list[ref_type('OrderLine')]
    batch_refs: list[ref_type('ProductBatch')]
    material_use_refs: list[ref_type('MaterialUse')]
    change_refs: list[ref_type('SupplyChangeRequest')]
    defect_refs: list[ref_type('Defect')]
    transaction_refs: list[ref_type('Transaction')]
    request_history_refs: list[ref_type('SupplyRemedyRequest')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class SupplierRemedyOrderLineView(CostSource):
    ref: ref_type('OrderLine')
    order_ref: ref_type('Order')
    product: QuoteProductLine


class SupplierRemedyProfileView(CostSource):
    ref: ref_type('SupplyRemedyProfile')
    order_ref: ref_type('Order')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    procedure_ref: ref_type('SupplyRemedyProcedure')
    choice: Literal['propose_change','repair','replace','propose_refund','claim','decline_request']
    business_key: TextId
    request_ref: ref_type('SupplyChangeRequest') | None
    change_proposal_ref: ref_type('SupplyChangeProposal') | None
    remedy_plan_ref: ref_type('SupplyRemedyPlan') | None
    affected_line_refs: list[ref_type('OrderLine')]
    unaffected_line_refs: list[ref_type('OrderLine')]
    source_defect_refs: list[ref_type('Defect')]
    disposition_scope: ScopeRef | None
    right_refs: list[ref_type('SupplyRemedyRight')]
    transaction_refs: list[ref_type('Transaction')]
    proposed_amount: ValueState[Money]
    assessment_ref: ref_type('RemedyAmountAssessment') | None
    basis_refs: list[ref_type('Evidence')]
    note: TextId


class SupplierRemedyProcedureView(GovReviewAuthored):
    ref: ref_type('SupplyRemedyProcedure')
    order_ref: ref_type('Order')
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    recipient_ids: list[TextId]
    response_deadline: TimePoint | None
    late_response_permitted: ValueState[bool]


class SupplierSupplyChangeRequestView(GovReviewAuthored):
    ref: ref_type('SupplyChangeRequest')
    order_ref: ref_type('Order')
    affected_line_refs: list[ref_type('OrderLine')]
    defect_refs: list[ref_type('Defect')]
    requested_choices: list[TextId]
    supported: ValueState[bool]
    status: Literal['received','pending','withdrawn','resolved']


class SupplierSupplyChangeProposalView(GovReviewAuthored):
    ref: ref_type('SupplyChangeProposal')
    order_ref: ref_type('Order')
    lines: list[QuoteProductLine]
    line_order_refs: list[ref_type('OrderLine')]
    description: TextId
    status: Literal['proposal','pending','approved','rejected']


class SupplierInstalledUseView(CostSource):
    ref: ref_type('MaterialUse')
    order_ref: ref_type('Order')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    physical_use_key: TextId
    owner_id: TextId
    site_operator_id: TextId
    quantity: Measured
    location_ref: ref_type('Location')
    status: Literal['installed','removed','disposed']
    removal_record_refs: list[ref_type('MaterialRemoval')]
    core_event_id: TextId


class SupplierRemovalRecordView(CostSource):
    ref: ref_type('MaterialRemoval')
    material_use_ref: ref_type('MaterialUse')
    physical_use_key: TextId
    quantity: Measured
    core_event_id: TextId
    producer: Literal['core']


class SupplierRemedyRightView(GovReviewAuthored):
    ref: ref_type('SupplyRemedyRight')
    order_ref: ref_type('Order')
    organization_id: TextId
    batch_ref: ref_type('ProductBatch')
    owner_id: TextId
    material_use_ref: ref_type('MaterialUse') | None
    site_operator_id: TextId | None
    authority_kind: Literal['own_title','owner_delegation','site_disposition']
    permitted_choices: list[Literal['repair','replace']]
    permitted: ValueState[bool]
    maximum_quantity: Measured


class SupplierRemedyTaskPlanView(GovReviewAuthored):
    ref: ref_type('SupplyRemedyPlan')
    order_ref: ref_type('Order')
    tasks: list[SupplierPlannedTask]
    task_defect_refs: dict[TextId,list[ref_type('Defect')]]
    task_slice_refs: dict[TextId,list[ref_type('RemedyPhysicalSlice')]]
    task_step_refs: dict[TextId,list[ref_type('RemedyStep')]]
    effect: Literal['draft_tasks_only']


class SupplierRemedyPhysicalSliceView(CostSource):
    ref: ref_type('RemedyPhysicalSlice')
    plan_ref: ref_type('SupplyRemedyPlan')
    batch_ref: ref_type('ProductBatch')
    physical_slice_key: TextId
    material_use_ref: ref_type('MaterialUse') | None
    quantity: Measured
    owner_right_ref: ref_type('SupplyRemedyRight')
    site_right_ref: ref_type('SupplyRemedyRight') | None


class SupplierRemedyStepView(CostSource):
    ref: ref_type('RemedyStep')
    plan_ref: ref_type('SupplyRemedyPlan')
    task_key: TextId
    slice_ref: ref_type('RemedyPhysicalSlice')
    kind: Literal['repair','remove','return_transport','new_supply','install_replacement']
    predecessor_step_refs: list[ref_type('RemedyStep')]
    required_inventory_allocation_refs: list[ref_type('InventoryAllocation')]
    required_supply_requirement_refs: list[ref_type('SupplyRequirement')]


class SupplierRemedyDependencyView(CostSource):
    ref: ref_type('Dependency')
    plan_ref: ref_type('SupplyRemedyPlan')
    dependent_task_key: TextId
    predecessor_task_keys: list[TextId]


class SupplierRemedyProductRequirementView(CostSource):
    ref: ref_type('Requirement')
    order_ref: ref_type('Order')
    product_refs: list[ref_type('ProductSpecification')]


class SupplierRemedyDeviationView(GovReviewAuthored):
    ref: ref_type('SpecificationDeviation')
    order_ref: ref_type('Order')
    product_ref: ref_type('ProductSpecification')
    requirement_refs: list[ref_type('Requirement')]
    status: Literal['proposal','pending','approved','rejected']


class SupplierOriginalTransactionView(CostSource):
    ref: ref_type('Transaction')
    order_ref: ref_type('Order')
    payer_id: TextId
    payee_id: TextId
    amount: Money
    actual_received: ValueState[bool]
    core_event_id: TextId
    refund_execution_refs: list[ref_type('RefundExecution')]
    refund_history_complete: bool
    as_of: TimePoint


class SupplierRefundExecutionView(CostSource):
    ref: ref_type('RefundExecution')
    transaction_ref: ref_type('Transaction')
    business_key: TextId
    amount: Money
    status: Literal['unknown','pending','succeeded','failed','rejected']
    core_event_id: TextId | None


class SupplierRemedyAmountView(GovReviewAuthored):
    ref: ref_type('RemedyAmountAssessment')
    order_ref: ref_type('Order')
    purpose: Literal['refund','claim']
    affected_line_refs: list[ref_type('OrderLine')]
    transaction_refs: list[ref_type('Transaction')]
    defect_refs: list[ref_type('Defect')]
    method_ref: ref_type('Method')
    data: SupplierClaimAmountInput
    input_sha256: Digest
    report: SupplierClaimAmountReport | None
    status: Literal['ok','unknown','failed','unsupported']
    classification: Literal['proposed_estimate']


class SupplierRemedyRequestView(GovReviewAuthored):
    ref: ref_type('SupplyRemedyRequest')
    order_ref: ref_type('Order')
    business_key: TextId
    choice: TextId
    profile_ref: ref_type('SupplyRemedyProfile')
    status: Literal['submitted','pending','accepted','rejected','withdrawn','unknown']


def supplier_remedy_schemas():
    return contractor_bid_schemas({
        'Order':SupplierRemedyOrderView,'OrderLine':SupplierRemedyOrderLineView,'SupplyRemedyProfile':SupplierRemedyProfileView,
        'SupplyRemedyProcedure':SupplierRemedyProcedureView,'SupplyChangeRequest':SupplierSupplyChangeRequestView,
        'SupplyChangeProposal':SupplierSupplyChangeProposalView,'ProductBatch':SupplierQualityBatchView,
        'MaterialUse':SupplierInstalledUseView,'MaterialRemoval':SupplierRemovalRecordView,'SupplyRemedyRight':SupplierRemedyRightView,
        'SupplyRemedyPlan':SupplierRemedyTaskPlanView,'RemedyPhysicalSlice':SupplierRemedyPhysicalSliceView,'RemedyStep':SupplierRemedyStepView,
        'Dependency':SupplierRemedyDependencyView,'SupplyMethod':SupplierPlanningMethodView,'ResourcePool':SupplierPlanningResourceView,
        'Requirement':SupplierRemedyProductRequirementView,'SpecificationDeviation':SupplierRemedyDeviationView,
        'Defect':SupplierVisibleDefectView,'InspectionEvidence':SupplierQualityEvidenceView,
        'Transaction':SupplierOriginalTransactionView,'RefundExecution':SupplierRefundExecutionView,
        'RemedyAmountAssessment':SupplierRemedyAmountView,'SupplyRemedyRequest':SupplierRemedyRequestView,
        'InventoryAllocation':SupplierInventoryAllocationView,'SupplyRequirement':SupplierPlanningRequirementView,
        'SupplyWorkAuthorization':SupplierWorkAuthorityView,'InventorySnapshot':QuoteInventoryView,
    })
