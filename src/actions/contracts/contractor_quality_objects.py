"""Visible defects, scoped inspection requests and original remedy plans."""
from typing import Literal

from src.actions.contracts.common import TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.contractor_bid_objects import ContractorBidTask, ContractorBidMethodView, contractor_bid_schemas
from src.actions.contracts.contractor_execution_objects import ContractorWorkRecordView
from src.methods.capacity import CapacityInput, CapacityReport


class ContractorInspectionProfileView(CostSource):
    ref: ref_type('InspectionProfile')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    choice: Literal['self_check', 'request_external_check', 'isolate', 'rectify', 'request_recheck']
    work_record_refs: list[ref_type('WorkRecord')]
    requirement_refs: list[ref_type('InspectionRequirement')]
    defect_refs: list[ref_type('Defect')]
    evidence_refs_received: list[ref_type('InspectionEvidence')]
    method_ref: ref_type('InspectionMethod') | None
    prior_inspection_ref: ref_type('InspectionResult') | None
    remedy_plan_ref: ref_type('RemedyPlan') | None
    isolation_authority_ref: ref_type('IsolationAuthority') | None
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    note: TextId


class ContractorInspectionRequirementView(CostSource):
    ref: ref_type('InspectionRequirement')
    work_record_refs: list[ref_type('WorkRecord')]
    allowed_method_refs: list[ref_type('InspectionMethod')]
    external_verification_required: bool


class ContractorInspectionMethodView(CostSource):
    ref: ref_type('InspectionMethod')
    supported: ValueState[bool]
    requirement_refs: list[ref_type('InspectionRequirement')]
    executor_organization_id: TextId
    executor_actor_id: TextId
    executor_function_ref: ref_type('FunctionAssignment')
    executor_authority_ref: ref_type('Authorization')
    executor_action_id: TextId
    requires_actual_evidence: bool
    observation_method_ref: ref_type('Method')


class ContractorInspectionObservationMethodView(CostSource):
    """Actual observation support, independent of a procurement reference."""
    ref: ref_type('Method')
    supported: ValueState[bool]
    allowed_author_action_ids: list[TextId]


class ContractorInspectionEvidenceView(GovReviewAuthored):
    ref: ref_type('InspectionEvidence')
    work_record_ref: ref_type('WorkRecord')
    physical_work_key: TextId
    defect_refs: list[ref_type('Defect')]
    kind: Literal['actual_observation', 'actual_remedy', 'statement', 'assumption']
    observed_at: TimePoint
    event_id: TextId


class ContractorVisibleDefectView(CostSource):
    ref: ref_type('Defect')
    work_record_ref: ref_type('WorkRecord')
    physical_work_key: TextId
    observation_ref: ref_type('InspectionEvidence')
    requirement_refs: list[ref_type('InspectionRequirement')]
    status: Literal['observed', 'confirmed', 'under_remedy', 'awaiting_recheck', 'closed']
    technical_acceptance: ValueState[bool]
    responsible_organization_id: ValueState[TextId]
    cost_bearer_id: ValueState[TextId]


class ContractorInspectionResultView(GovReviewAuthored):
    ref: ref_type('InspectionResult')
    method_ref: ref_type('InspectionMethod')
    work_record_refs: list[ref_type('WorkRecord')]
    defect_refs: list[ref_type('Defect')]
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


class ContractorIsolationAuthorityView(CostSource):
    ref: ref_type('IsolationAuthority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    defect_refs: list[ref_type('Defect')]
    permitted: ValueState[bool]
    restriction: Literal['own_work_isolation']


class ContractorRemedyPlanView(GovReviewAuthored):
    ref: ref_type('RemedyPlan')
    defect_refs: list[ref_type('Defect')]
    tasks: list[ContractorBidTask]
    task_defect_refs: dict[TextId, list[ref_type('Defect')]]
    capacity_result_ref: ref_type('RemedyCapacityEvaluation')
    object_type: TextId
    work_type: TextId
    required_qualification_codes: list[TextId]
    work_kind: Literal['rework']
    inventory_effect: Literal['none']


class ContractorRemedyDependencyView(CostSource):
    ref: ref_type('Dependency')
    plan_ref: ref_type('RemedyPlan')
    dependent_task_key: TextId
    predecessor_task_keys: list[TextId]
    responsible_organization_id: ValueState[TextId]
    planning_permitted: ValueState[bool]


class ContractorRemedyCapacityView(GovReviewAuthored):
    ref: ref_type('RemedyCapacityEvaluation')
    plan_ref: ref_type('RemedyPlan')
    capacity_ref: ref_type('ContractorCapacity')
    plan_sha256: Digest
    method_ref: ref_type('Method')
    data: CapacityInput
    report: CapacityReport | None
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


def contractor_quality_schemas():
    return contractor_bid_schemas({
        'InspectionProfile': ContractorInspectionProfileView, 'InspectionRequirement': ContractorInspectionRequirementView,
        'InspectionMethod': ContractorInspectionMethodView, 'InspectionEvidence': ContractorInspectionEvidenceView,
        'Method': ContractorInspectionObservationMethodView,
        'Defect': ContractorVisibleDefectView, 'InspectionResult': ContractorInspectionResultView,
        'IsolationAuthority': ContractorIsolationAuthorityView, 'RemedyPlan': ContractorRemedyPlanView,
        'RemedyCapacityEvaluation': ContractorRemedyCapacityView, 'WorkRecord': ContractorWorkRecordView,
        'Dependency': ContractorRemedyDependencyView,
    })
