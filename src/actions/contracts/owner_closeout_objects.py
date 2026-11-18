"""Scoped owner acceptance and settlement decisions preserve actual residual duties."""
from typing import Literal

from src.actions.contracts.common import Money, Reference, ScopeRef, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.contractor_closeout_objects import (
    ContractorAsBuiltView, ContractorCloseoutVerificationView, ContractorCloseoutMethodView,
    ContractorCloseoutRequirementView, ContractorCloseoutIssueView, ContractorContinuingResponsibilityView,
    ContractorHandoverRequestView, ContractorAsBuiltDesignView, ContractorAsBuiltBatchView,
    ContractorVisibleDefectView, ContractorInspectionEvidenceView, ContractorWorkRecordView,
)
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_design_objects import OwnerDesignScopeChoice
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView, OwnerPaymentComponentView
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView
from src.actions.contracts.architect_review_objects import Digest


class OwnerCloseoutOrganizationView(ServiceScopeOrganizationView):
    closeout_state_ref: ref_type('OwnerCloseoutState')


class OwnerCloseoutCaseView(ServiceScopeCaseView):
    closeout_state_ref: ref_type('OwnerCloseoutState')


class OwnerCloseoutProjectView(ServiceScopeProjectView):
    closeout_state_ref: ref_type('OwnerCloseoutState')


class OwnerCloseoutStateView(CostSource):
    ref: ref_type('OwnerCloseoutState')
    organization_id: TextId
    decision_profile_ref: ref_type('OwnerCloseoutProfile')
    contract_refs: list[ref_type('Contract')]
    handover_refs: list[ref_type('HandoverSubmission')]
    verification_refs: list[ref_type('Verification')]
    permit_refs: list[ref_type('Permit')]
    defect_refs: list[ref_type('Defect')]
    settlement_refs: list[ref_type('SettlementProposal')]
    obligation_refs: list[ref_type('Obligation')]
    responsibility_refs: list[ref_type('ContinuingResponsibility')]
    decision_history_refs: list[ref_type('OwnerCloseoutDecision')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class OwnerCloseoutProfileView(CostSource):
    ref: ref_type('OwnerCloseoutProfile')
    state_ref: ref_type('OwnerCloseoutState')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    contract_ref: ref_type('Contract')
    choice: Literal['accept_scope','request_rectification','agree_settlement','dispute_settlement','release_retention']
    business_key: TextId
    handover_ref: ref_type('HandoverSubmission') | None
    accepted_scope: OwnerDesignScopeChoice | None
    remaining_issue_refs: list[ref_type('Issue')]
    defect_refs: list[ref_type('Defect')]
    component_refs: list[ref_type('SettlementComponent')]
    basis_refs: list[ref_type('Evidence')]
    note: TextId


class OwnerCloseoutContractView(CostSource):
    ref: ref_type('Contract')
    owner_id: TextId
    contractor_id: TextId
    currency: TextId
    procedure_ref: ref_type('OwnerCloseoutProcedure')
    handover_refs: list[ref_type('HandoverSubmission')]
    settlement_refs: list[ref_type('SettlementProposal')]
    component_refs: list[ref_type('SettlementComponent')]
    issue_refs: list[ref_type('Issue')]
    defect_refs: list[ref_type('Defect')]
    responsibility_refs: list[ref_type('ContinuingResponsibility')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class OwnerCloseoutProcedureView(GovReviewAuthored):
    ref: ref_type('OwnerCloseoutProcedure')
    contract_ref: ref_type('Contract')
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    allowed_acceptance_scopes: list[ScopeRef]
    allow_conditional_acceptance: bool
    allow_partial_settlement: bool
    recipient_ids: list[TextId]


class OwnerHandoverSubmissionView(GovReviewAuthored):
    ref: ref_type('HandoverSubmission')
    contract_ref: ref_type('Contract')
    request_ref: ref_type('HandoverRequest')
    as_built_refs: list[ref_type('AsBuiltRecord')]
    requirement_refs: list[ref_type('Requirement')]
    required_permit_refs: list[ref_type('Permit')]
    issue_refs: list[ref_type('Issue')]
    independent_use: ValueState[bool]
    status: Literal['submitted','pending','accepted','withdrawn','rejected']


class OwnerCloseoutPermitView(GovReviewAuthored):
    ref: ref_type('Permit')
    contract_ref: ref_type('Contract')
    authorized_scope: ScopeRef
    purpose: Literal['handover','use','other']
    status: Literal['issued','suspended','revoked','expired','unknown']


class OwnerSettlementProposalView(GovReviewAuthored):
    ref: ref_type('SettlementProposal')
    contract_ref: ref_type('Contract')
    component_refs: list[ref_type('SettlementComponent')]
    status: Literal['proposed','pending','disputed','agreed','withdrawn']


class OwnerCloseoutComponentView(GovReviewAuthored):
    ref: ref_type('SettlementComponent')
    contract_ref: ref_type('Contract')
    proposal_ref: ref_type('SettlementProposal')
    physical_component_key: TextId
    debtor_id: TextId
    payee_id: TextId
    kind: Literal['final_account','retention','adjustment']
    proposed_amount: ValueState[Money]
    existing_component_ref: ref_type('ActualSettlementComponent') | None
    assessment_refs: list[ref_type('SettlementAssessment')]
    issue_refs: list[ref_type('Issue')]
    retention_rule_ref: ref_type('RetentionReleaseRule') | None


class OwnerSettlementAssessmentView(GovReviewAuthored):
    ref: ref_type('SettlementAssessment')
    component_ref: ref_type('SettlementComponent')
    component_sha256: Digest
    amount: ValueState[Money]
    supported: ValueState[bool]
    status: Literal['ok','unknown','failed','unsupported']
    source_refs: list[Reference]


class OwnerActualSettlementComponentView(OwnerPaymentComponentView):
    ref: ref_type('ActualSettlementComponent')
    original_component_ref: ref_type('SettlementComponent')


class OwnerRetentionRuleView(GovReviewAuthored):
    ref: ref_type('RetentionReleaseRule')
    contract_ref: ref_type('Contract')
    component_ref: ref_type('SettlementComponent')
    due_at: TimePoint
    permitted: ValueState[bool]
    condition_refs: list[ref_type('RetentionCondition')]
    retained_responsibility_refs: list[ref_type('ContinuingResponsibility')]


class OwnerRetentionConditionView(GovReviewAuthored):
    ref: ref_type('RetentionCondition')
    rule_ref: ref_type('RetentionReleaseRule')
    satisfied: ValueState[bool]
    status: Literal['ok','unknown','failed','unsupported']
    source_refs: list[Reference]


class OwnerCloseoutDecisionView(GovReviewAuthored):
    ref: ref_type('OwnerCloseoutDecision')
    state_ref: ref_type('OwnerCloseoutState')
    contract_ref: ref_type('Contract')
    business_key: TextId
    profile_ref: ref_type('OwnerCloseoutProfile')
    profile_sha256: Digest
    choice: TextId
    status: Literal['submitted','pending','unknown','accepted','rejected']


def owner_closeout_schemas():
    return contractor_bid_schemas({
        'Organization':OwnerCloseoutOrganizationView,'OwnerCase':OwnerCloseoutCaseView,'Project':OwnerCloseoutProjectView,
        'OwnerCloseoutState':OwnerCloseoutStateView,'OwnerCloseoutProfile':OwnerCloseoutProfileView,
        'Contract':OwnerCloseoutContractView,'OwnerCloseoutProcedure':OwnerCloseoutProcedureView,
        'HandoverSubmission':OwnerHandoverSubmissionView,'HandoverRequest':ContractorHandoverRequestView,
        'AsBuiltRecord':ContractorAsBuiltView,'Deliverable':ContractorAsBuiltDesignView,'ProductBatch':ContractorAsBuiltBatchView,
        'Verification':ContractorCloseoutVerificationView,'VerificationMethod':ContractorCloseoutMethodView,
        'Requirement':ContractorCloseoutRequirementView,'Issue':ContractorCloseoutIssueView,
        'Defect':ContractorVisibleDefectView,'InspectionEvidence':ContractorInspectionEvidenceView,'WorkRecord':ContractorWorkRecordView,
        'Permit':OwnerCloseoutPermitView,'SettlementProposal':OwnerSettlementProposalView,
        'SettlementComponent':OwnerCloseoutComponentView,'ActualSettlementComponent':OwnerActualSettlementComponentView,
        'SettlementAssessment':OwnerSettlementAssessmentView,'RetentionReleaseRule':OwnerRetentionRuleView,
        'RetentionCondition':OwnerRetentionConditionView,'Obligation':OwnerPaymentObligationView,
        'ContinuingResponsibility':ContractorContinuingResponsibilityView,'OwnerCloseoutDecision':OwnerCloseoutDecisionView,
    })
