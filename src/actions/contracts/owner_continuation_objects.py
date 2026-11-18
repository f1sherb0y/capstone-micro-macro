"""Original scoped transition proposals; ledger and commitments remain core facts."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas, ContractorBidCommitmentView
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_design_objects import OwnerDesignScopeChoice
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView, OwnerPaymentSourceView
from src.actions.contracts.qs_cost_objects import CostSource


class OwnerContinuationProfileView(CostSource):
    ref: ref_type('ContinuationProfile')
    state_ref: ref_type('ContinuationState')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['suspend','reduce','remedy','replace','transfer','terminate','resume']
    business_key: TextId
    scope_choice: OwnerDesignScopeChoice
    retained_obligation_refs: list[ref_type('Obligation')]
    suspension_kind: Literal['reversible','irreversible'] | None
    protection_task_refs: list[ref_type('Task')]
    release_candidate_refs: list[ref_type('ResourceCommitment')]
    readiness_refs: list[ref_type('Verification')]
    successor_id: TextId | None
    successor_ref: ref_type('Organization') | None
    transfer_basis_refs: list[ref_type('Evidence')]
    transfer_plan_ref: ref_type('ContinuationTransferPlan') | None
    note: TextId


class OwnerContinuationStateView(CostSource):
    ref: ref_type('ContinuationState')
    organization_id: TextId
    scope_rule_ref: ref_type('ContinuationRule')
    status: Literal['effective','suspended','terminated','mixed']
    suspension_kind: Literal['reversible','irreversible'] | None
    risk_refs: list[ref_type('RiskObservation')]
    contract_refs: list[ref_type('Contract')]
    resource_refs: list[ref_type('ResourceCommitment')]
    obligation_refs: list[ref_type('Obligation')]
    retained_duty_refs: list[ref_type('ContinuingDuty')]
    right_refs: list[ref_type('ContinuationRight')]
    document_refs: list[ref_type('ContinuationDocument')]
    funding_refs: list[ref_type('FundingSource')]
    permit_refs: list[ref_type('Permit')]
    execution_refs: list[ref_type('ContinuationExecution')]
    sunk_cost: ValueState[Money]
    coverage: Literal['complete','partial','unknown']
    producer: Literal['core']
    as_of: TimePoint


class OwnerContinuationContractView(CostSource):
    ref: ref_type('Contract')
    owner_id: TextId
    counterparty_id: TextId
    rule_ref: ref_type('ContinuationRule')
    status: Literal['effective','suspended','terminated','closed']
    suspension_kind: Literal['reversible','irreversible'] | None
    retained_obligation_refs: list[ref_type('Obligation')]
    continuing_duty_refs: list[ref_type('ContinuingDuty')]
    as_of: TimePoint


class OwnerContinuationRuleView(GovReviewAuthored):
    ref: ref_type('ContinuationRule')
    contract_ref: ref_type('Contract') | None
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    condition_refs: list[ref_type('Verification')]
    protection_task_refs: list[ref_type('Task')]
    resume_permitted: ValueState[bool]
    allow_irreversible_suspension: bool
    recipient_ids: list[TextId]


class OwnerContinuationRiskView(GovReviewAuthored):
    ref: ref_type('RiskObservation')
    organization_id: TextId
    observed_at: TimePoint
    category: Literal['funding','rights','demand','safety','resource','counterparty','other']
    affected_contract_refs: list[ref_type('Contract')]
    status: Literal['open','resolved','unknown']


class OwnerContinuationDutyView(CostSource):
    ref: ref_type('ContinuingDuty')
    organization_id: TextId
    contract_ref: ref_type('Contract') | None
    kind: Literal['site_safety','storage','defect','debt','other']
    obligation_refs: list[ref_type('Obligation')]
    task_refs: list[ref_type('Task')]
    remains: ValueState[bool]


class OwnerCloseoutContinuationDisposition(StrictRecord):
    source_ref: Reference
    disposition: Literal['retained', 'settled', 'released', 'superseded']
    target_refs: list[Reference]
    basis_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class OwnerCloseoutContinuationBasisView(CostSource):
    ref: ref_type('CloseoutContinuationBasis')
    run_id: TextId
    organization_id: TextId
    source_task_sha256: Digest
    feedback_record_sha256: Digest
    source_result_sha256: Digest
    source_receipt_sha256: Digest
    decision_ref: ref_type('OwnerCloseoutDecision')
    continuation_state_ref: ref_type('ContinuationState')
    contract_refs: Annotated[list[ref_type('Contract')], Field(min_length=1)]
    dispositions: list[OwnerCloseoutContinuationDisposition]
    native_evidence_ref: ref_type('Evidence')


class OwnerContinuationSourceDigest(StrictRecord):
    source_ref: Reference
    content_sha256: Digest


class OwnerContinuationVerificationView(GovReviewAuthored):
    ref: ref_type('Verification')
    state_ref: ref_type('ContinuationState')
    state_sha256: Digest
    contract_ref: ref_type('Contract') | None
    family: Literal['funding','resources','permits','rights','versions','safety','exit','transfer']
    permitted_choices: list[TextId]
    checked_scope: ScopeRef
    supported: ValueState[bool]
    status: Literal['ok','unknown','failed','unsupported']
    source_digests: list[OwnerContinuationSourceDigest]
    as_of: TimePoint


class OwnerContinuationTaskView(GovReviewAuthored):
    ref: ref_type('Task')
    owner_id: TextId
    contract_ref: ref_type('Contract') | None
    kind: Literal['site_protection','storage','safety','remedy','other']
    permitted: ValueState[bool]
    status: Literal['planned','released','working','blocked','completed','cancelled']


class OwnerContinuationCommitmentView(ContractorBidCommitmentView):
    physical_commitment_key: TextId
    owner_id: TextId
    release_rule_ref: ref_type('ResourceReleaseRule')
    execution_refs: list[ref_type('ContinuationExecution')]
    status: Literal['held','committed','released','consumed','unknown']
    as_of: TimePoint


class OwnerResourceReleaseRuleView(GovReviewAuthored):
    ref: ref_type('ResourceReleaseRule')
    commitment_ref: ref_type('ResourceCommitment')
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    condition_refs: list[ref_type('Verification')]


class OwnerContinuationExecutionView(CostSource):
    ref: ref_type('ContinuationExecution')
    state_ref: ref_type('ContinuationState')
    organization_id: TextId
    run_id: TextId
    operation_id: TextId
    business_key: TextId
    profile_ref: ref_type('ContinuationProfile')
    profile_sha256: Digest
    resource_refs: list[ref_type('ResourceCommitment')]
    status: Literal['unknown','pending','succeeded','failed','rejected']
    core_event_id: TextId | None


class OwnerContinuationRightView(GovReviewAuthored):
    ref: ref_type('ContinuationRight')
    organization_id: TextId
    holder_id: TextId
    contract_ref: ref_type('Contract') | None
    transferable: ValueState[bool]
    permitted: ValueState[bool]


class OwnerContinuationDocumentView(GovReviewAuthored):
    ref: ref_type('ContinuationDocument')
    organization_id: TextId
    contract_ref: ref_type('Contract') | None
    content_sha256: Digest
    permitted: ValueState[bool]


class OwnerContinuationPermitView(GovReviewAuthored):
    ref: ref_type('Permit')
    authorized_scope: ScopeRef
    status: Literal['issued','suspended','revoked','expired','unknown']


class OwnerContinuationTransferItem(StrictRecord):
    source_ref: Reference
    disposition: Literal['retain','share','propose_transfer']
    basis_refs: list[ref_type('Evidence')]
    consent_refs: list[ref_type('PartyAcceptance')]


class OwnerContinuationConditionView(CostSource):
    ref: ref_type('Requirement')
    verification_ref: ref_type('Verification')


class OwnerContinuationConsentView(GovReviewAuthored):
    ref: ref_type('PartyAcceptance')
    plan_ref: ref_type('ContinuationTransferPlan')
    source_ref: Reference
    successor_ref: ref_type('Organization')
    party_id: TextId
    accepted: ValueState[bool]
    status: Literal['active','withdrawn']


class OwnerContinuationTransferPlanView(GovReviewAuthored):
    ref: ref_type('ContinuationTransferPlan')
    state_ref: ref_type('ContinuationState')
    successor_id: TextId
    choice: Literal['replace','transfer']
    items: list[OwnerContinuationTransferItem]
    verification_refs: list[ref_type('Verification')]
    status: Literal['proposal','pending','agreed','rejected']
    effect: Literal['proposal_only']


def owner_continuation_schemas():
    return contractor_bid_schemas({
        'ContinuationProfile':OwnerContinuationProfileView,'ContinuationState':OwnerContinuationStateView,
        'Contract':OwnerContinuationContractView,'ContinuationRule':OwnerContinuationRuleView,
        'RiskObservation':OwnerContinuationRiskView,'ContinuingDuty':OwnerContinuationDutyView,
        'Verification':OwnerContinuationVerificationView,'Task':OwnerContinuationTaskView,
        'ResourceCommitment':OwnerContinuationCommitmentView,'ResourceReleaseRule':OwnerResourceReleaseRuleView,
        'Obligation':OwnerPaymentObligationView,'ContinuationExecution':OwnerContinuationExecutionView,
        'ContinuationRight':OwnerContinuationRightView,'ContinuationDocument':OwnerContinuationDocumentView,
        'ContinuationTransferPlan':OwnerContinuationTransferPlanView,
        'FundingSource':OwnerPaymentSourceView,'Permit':OwnerContinuationPermitView,
        'Requirement':OwnerContinuationConditionView,'PartyAcceptance':OwnerContinuationConsentView,
        'CloseoutContinuationBasis':OwnerCloseoutContinuationBasisView,
    })
