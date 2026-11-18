"""Visible batch evidence and scoped disposition rights preserve physical lineage."""
from typing import Literal

from src.actions.contracts.common import Measured, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_planning_objects import SupplierPlannedTask, SupplierPlanningMethodView, SupplierPlanningResourceView, SupplierPlanningRequirementView
from src.actions.contracts.supplier_planning_objects import SupplierWorkAuthorityView
from src.actions.contracts.supplier_execution_objects import SupplierActualInventoryAllocationView, SupplierActualMaterialView


class SupplierQualityBatchView(CostSource):
    ref: ref_type('ProductBatch')
    organization_id: TextId
    owner_id: TextId
    product_ref: ref_type('ProductSpecification')
    physical_batch_key: TextId
    actual_quantity: Measured
    state: Literal['pending_inspection', 'usable', 'partially_isolated', 'isolated', 'awaiting_rework', 'scrapped']
    lineage_ledger_ref: ref_type('BatchLineageLedger')
    requirement_refs: list[ref_type('InspectionRequirement')]
    known_defect_refs: list[ref_type('Defect')]
    core_event_id: TextId
    as_of: TimePoint


class SupplierQualityProfileView(CostSource):
    ref: ref_type('InspectionProfile')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    batch_ref: ref_type('ProductBatch')
    choice: Literal['self_check', 'request_external_check', 'isolate', 'rework', 'scrap', 'propose_deviation']
    requirement_refs: list[ref_type('InspectionRequirement')]
    evidence_refs_received: list[ref_type('InspectionEvidence')]
    known_defect_refs: list[ref_type('Defect')]
    method_ref: ref_type('InspectionMethod') | None
    disposition_right_ref: ref_type('BatchDispositionRight') | None
    quantity: Measured | None
    business_key: TextId
    remedy_plan_ref: ref_type('BatchRemedyPlan') | None
    deviation_refs: list[ref_type('SpecificationDeviation')]
    basis_refs: list[ref_type('Evidence')]
    note: TextId


class SupplierQualityRequirementView(CostSource):
    ref: ref_type('InspectionRequirement')
    batch_ref: ref_type('ProductBatch')
    product_ref: ref_type('ProductSpecification')
    use_codes: list[TextId]
    allowed_method_refs: list[ref_type('InspectionMethod')]
    external_verification_required: bool


class SupplierQualityMethodView(CostSource):
    ref: ref_type('InspectionMethod')
    supported: ValueState[bool]
    requirement_refs: list[ref_type('InspectionRequirement')]
    observation_method_ref: ref_type('Method')
    executor_organization_id: TextId
    executor_actor_id: TextId
    executor_function_ref: ref_type('FunctionAssignment')
    executor_authority_ref: ref_type('Authorization')
    executor_action_id: TextId
    requires_actual_evidence: bool


class SupplierQualityObservationMethodView(CostSource):
    ref: ref_type('Method')
    supported: ValueState[bool]
    allowed_author_action_ids: list[TextId]


class SupplierQualityEvidenceView(GovReviewAuthored):
    ref: ref_type('InspectionEvidence')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    kind: Literal['actual_observation', 'actual_test', 'actual_remedy', 'statement', 'assumption']
    observed_at: TimePoint
    sample_quantity: Measured
    use_codes: list[TextId]
    defect_refs: list[ref_type('Defect')]
    event_id: TextId


class SupplierVisibleDefectView(CostSource):
    ref: ref_type('Defect')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    observation_ref: ref_type('InspectionEvidence')
    requirement_refs: list[ref_type('InspectionRequirement')]
    status: Literal['observed', 'confirmed', 'under_rework', 'awaiting_recheck', 'closed']
    responsible_organization_id: ValueState[TextId]
    cost_bearer_id: ValueState[TextId]


class SupplierBatchDispositionRightView(GovReviewAuthored):
    ref: ref_type('BatchDispositionRight')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    organization_id: TextId
    owner_id: TextId
    authority_kind: Literal['own_title', 'custody_isolation', 'delegated_disposition']
    permitted_choices: list[Literal['isolate', 'scrap', 'rework']]
    permitted: ValueState[bool]
    maximum_quantity: Measured


class SupplierBatchLineageLedgerView(CostSource):
    ref: ref_type('BatchLineageLedger')
    physical_batch_key: TextId
    organization_id: TextId
    original_quantity: Measured
    actual_remaining: Measured
    scrapped_quantity: Measured
    other_outflow: Measured
    isolated_quantity: Measured
    execution_refs: list[ref_type('BatchDispositionExecution')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    producer: Literal['core']


class SupplierBatchDispositionExecutionView(CostSource):
    ref: ref_type('BatchDispositionExecution')
    physical_batch_key: TextId
    organization_id: TextId
    operation_id: TextId
    business_key: TextId
    choice: Literal['isolate', 'scrap', 'release_isolation']
    quantity: Measured
    isolated_quantity_decrease: Measured
    status: Literal['submitted_unknown', 'recorded', 'rejected', 'failed']
    query_status: Literal['present', 'absent', 'unknown', 'not_queried']
    core_event_id: TextId | None
    release_basis_ref: ref_type('BatchRecheck') | None


class SupplierBatchRecheckView(GovReviewAuthored):
    ref: ref_type('BatchRecheck')
    physical_batch_key: TextId
    supported: ValueState[bool]
    passed: ValueState[bool]
    method_ref: ref_type('InspectionMethod')
    requirement_refs: list[ref_type('InspectionRequirement')]
    scope_of_release: Measured


class SupplierBatchRemedyPlanView(GovReviewAuthored):
    ref: ref_type('BatchRemedyPlan')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    tasks: list[SupplierPlannedTask]
    task_defect_refs: dict[TextId, list[ref_type('Defect')]]
    task_slice_refs: dict[TextId, list[ref_type('BatchReworkSlice')]]
    disposition_right_ref: ref_type('BatchDispositionRight')
    effect: Literal['draft_rework_tasks_only']


class SupplierBatchReworkSliceView(CostSource):
    ref: ref_type('BatchReworkSlice')
    plan_ref: ref_type('BatchRemedyPlan')
    physical_batch_key: TextId
    physical_slice_key: TextId
    quantity: Measured
    defect_refs: list[ref_type('Defect')]


class SupplierBatchRemedyDependencyView(CostSource):
    ref: ref_type('Dependency')
    plan_ref: ref_type('BatchRemedyPlan')
    dependent_task_key: TextId
    predecessor_task_keys: list[TextId]


class SupplierQualityProductRequirementView(CostSource):
    ref: ref_type('Requirement')
    batch_ref: ref_type('ProductBatch')
    product_ref: ref_type('ProductSpecification')


class SupplierQualityDeviationView(GovReviewAuthored):
    ref: ref_type('SpecificationDeviation')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    product_ref: ref_type('ProductSpecification')
    inspection_requirement_refs: list[ref_type('InspectionRequirement')]
    defect_refs: list[ref_type('Defect')]
    use_codes: list[TextId]
    description: TextId
    status: Literal['proposal', 'pending', 'approved', 'rejected']


def supplier_quality_schemas():
    return contractor_bid_schemas({
        'ProductBatch': SupplierQualityBatchView, 'InspectionProfile': SupplierQualityProfileView,
        'InspectionRequirement': SupplierQualityRequirementView, 'InspectionMethod': SupplierQualityMethodView,
        'Method': SupplierQualityObservationMethodView, 'InspectionEvidence': SupplierQualityEvidenceView,
        'Defect': SupplierVisibleDefectView, 'BatchDispositionRight': SupplierBatchDispositionRightView,
        'BatchLineageLedger': SupplierBatchLineageLedgerView, 'BatchDispositionExecution': SupplierBatchDispositionExecutionView,
        'BatchRecheck': SupplierBatchRecheckView, 'BatchRemedyPlan': SupplierBatchRemedyPlanView,
        'BatchReworkSlice': SupplierBatchReworkSliceView,
        'Dependency': SupplierBatchRemedyDependencyView, 'SupplyMethod': SupplierPlanningMethodView,
        'Requirement': SupplierQualityProductRequirementView, 'SpecificationDeviation': SupplierQualityDeviationView,
        'ResourcePool': SupplierPlanningResourceView, 'SupplyRequirement': SupplierPlanningRequirementView,
        'SupplyWorkAuthorization': SupplierWorkAuthorityView,
        'InventoryAllocation': SupplierActualInventoryAllocationView, 'MaterialBatch': SupplierActualMaterialView,
    })
