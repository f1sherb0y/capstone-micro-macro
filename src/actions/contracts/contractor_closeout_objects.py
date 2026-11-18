"""Actual configurations, pending handover and itemized final-account requests."""
from typing import Literal

from src.actions.contracts.common import TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import ContractorBidTask, ContractorBidMethodView, ContractorBidResourceView, contractor_bid_schemas
from src.actions.contracts.contractor_execution_objects import ContractorWorkRecordView
from src.actions.contracts.contractor_quality_objects import ContractorVisibleDefectView, ContractorInspectionEvidenceView
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.actions.contracts.contractor_payment_objects import ContractorRequestableComponentView
from src.actions.contracts.qs_cost_objects import CostSource


class ContractorCloseoutContractView(CostSource):
    ref: ref_type('Contract')
    contractor_id: TextId
    client_id: TextId
    currency: TextId
    as_built_refs: list[ref_type('AsBuiltRecord')]
    verification_refs: list[ref_type('Verification')]
    defect_refs: list[ref_type('Defect')]
    issue_refs: list[ref_type('Issue')]
    obligation_refs: list[ref_type('Obligation')]
    settlement_component_refs: list[ref_type('SettlementComponent')]
    continuing_responsibility_refs: list[ref_type('ContinuingResponsibility')]
    handover_request_refs: list[ref_type('HandoverRequest')]
    final_account_refs: list[ref_type('FinalAccount')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class ContractorHandoverProfileView(CostSource):
    ref: ref_type('HandoverProfile')
    contract_ref: ref_type('Contract')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    procedure_ref: ref_type('HandoverProcedure')
    choice: Literal['submit_handover', 'rectify', 'propose_final_account', 'respond_settlement']
    business_key: TextId
    remaining_issue_refs: list[ref_type('Issue')]
    evidence_refs_received: list[ref_type('Evidence')]
    remedy_plan_ref: ref_type('CloseoutRemedyPlan') | None
    final_account_ref: ref_type('FinalAccount') | None
    component_refs: list[ref_type('SettlementComponent')]
    disputed_refs: list[ref_type('SettlementComponent')]
    note: TextId


class ContractorHandoverProcedureView(CostSource):
    ref: ref_type('HandoverProcedure')
    contract_ref: ref_type('Contract')
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    recipient_ids: list[TextId]
    required_as_built_scope_refs: list[ref_type('WorkScope')]
    required_requirement_refs: list[ref_type('Requirement')]
    require_independent_verification: bool
    allow_pending_handover: bool


class ContractorAsBuiltView(GovReviewAuthored):
    ref: ref_type('AsBuiltRecord')
    contract_ref: ref_type('Contract')
    content_sha256: Digest
    configuration_key: TextId
    design_ref: ref_type('Deliverable')
    product_batch_refs: list[ref_type('ProductBatch')]
    work_record_refs: list[ref_type('WorkRecord')]
    actual: ValueState[bool]


class ContractorAsBuiltDesignView(CostSource):
    ref: ref_type('Deliverable')
    contract_ref: ref_type('Contract')
    content_sha256: Digest


class ContractorAsBuiltBatchView(CostSource):
    ref: ref_type('ProductBatch')
    contract_ref: ref_type('Contract')
    configuration_refs: list[ref_type('AsBuiltRecord')]
    content_sha256: Digest


class ContractorCloseoutVerificationView(GovReviewAuthored):
    ref: ref_type('Verification')
    contract_ref: ref_type('Contract')
    as_built_ref: ref_type('AsBuiltRecord')
    as_built_sha256: Digest
    requirement_ref: ref_type('Requirement')
    method_ref: ref_type('VerificationMethod')
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    passed: ValueState[bool]


class ContractorCloseoutMethodView(CostSource):
    ref: ref_type('VerificationMethod')
    supported: ValueState[bool]
    requirement_refs: list[ref_type('Requirement')]
    allowed_author_action_ids: list[TextId]


class ContractorCloseoutRequirementView(CostSource):
    ref: ref_type('Requirement')
    contract_ref: ref_type('Contract')
    as_built_refs: list[ref_type('AsBuiltRecord')]


class ContractorCloseoutIssueView(CostSource):
    ref: ref_type('Issue')
    contract_ref: ref_type('Contract')
    as_built_refs: list[ref_type('AsBuiltRecord')]
    defect_refs: list[ref_type('Defect')]
    requirement_refs: list[ref_type('Requirement')]
    component_refs: list[ref_type('SettlementComponent')]
    status: Literal['open', 'disputed', 'resolved']


class ContractorContinuingResponsibilityView(CostSource):
    ref: ref_type('ContinuingResponsibility')
    contract_ref: ref_type('Contract')
    organization_id: TextId
    kind: Literal['defect', 'guarantee', 'unpaid_debt', 'other']
    remaining: ValueState[bool]
    obligation_refs: list[ref_type('Obligation')]
    defect_refs: list[ref_type('Defect')]


class ContractorHandoverRequestView(GovReviewAuthored):
    ref: ref_type('HandoverRequest')
    contract_ref: ref_type('Contract')
    business_key: TextId
    as_built_refs: list[ref_type('AsBuiltRecord')]
    status: Literal['submitted', 'pending', 'accepted', 'withdrawn', 'rejected']


class ContractorFinalAccountView(GovReviewAuthored):
    ref: ref_type('FinalAccount')
    contract_ref: ref_type('Contract')
    business_key: TextId
    component_refs: list[ref_type('SettlementComponent')]
    status: Literal['proposed', 'pending', 'determined', 'disputed', 'withdrawn']


class ContractorCloseoutRemedyPlanView(GovReviewAuthored):
    ref: ref_type('CloseoutRemedyPlan')
    contract_ref: ref_type('Contract')
    task_authority_ref: ref_type('CloseoutTaskAuthority')
    tasks: list[ContractorBidTask]
    task_defect_refs: dict[TextId, list[ref_type('Defect')]]
    work_kind: Literal['rework']
    effect: Literal['draft_tasks_only']


class ContractorCloseoutTaskAuthorityView(CostSource):
    ref: ref_type('CloseoutTaskAuthority')
    contract_ref: ref_type('Contract')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    permitted: ValueState[bool]
    defect_refs: list[ref_type('Defect')]
    allowed_method_refs: list[ref_type('WorkMethod')]


class ContractorCloseoutDependencyView(CostSource):
    ref: ref_type('Dependency')
    plan_ref: ref_type('CloseoutRemedyPlan')
    dependent_task_key: TextId
    predecessor_task_keys: list[TextId]


def contractor_closeout_schemas():
    return contractor_bid_schemas({
        'Contract': ContractorCloseoutContractView, 'HandoverProfile': ContractorHandoverProfileView,
        'HandoverProcedure': ContractorHandoverProcedureView, 'AsBuiltRecord': ContractorAsBuiltView,
        'Deliverable': ContractorAsBuiltDesignView, 'ProductBatch': ContractorAsBuiltBatchView,
        'Verification': ContractorCloseoutVerificationView, 'VerificationMethod': ContractorCloseoutMethodView,
        'Requirement': ContractorCloseoutRequirementView, 'Issue': ContractorCloseoutIssueView,
        'Defect': ContractorVisibleDefectView, 'InspectionEvidence': ContractorInspectionEvidenceView,
        'WorkRecord': ContractorWorkRecordView, 'ContinuingResponsibility': ContractorContinuingResponsibilityView,
        'Obligation': OwnerPaymentObligationView, 'SettlementComponent': ContractorRequestableComponentView,
        'HandoverRequest': ContractorHandoverRequestView, 'FinalAccount': ContractorFinalAccountView,
        'CloseoutRemedyPlan': ContractorCloseoutRemedyPlanView,
        'CloseoutTaskAuthority': ContractorCloseoutTaskAuthorityView,
        'Dependency': ContractorCloseoutDependencyView,
    })
