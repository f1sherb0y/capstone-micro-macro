"""Original effective contracts, scoped instructions and pending change/claim decisions."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Money, Reference, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_design_objects import OwnerDesignScopeChoice
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView


class OwnerContractView(CostSource):
    ref: ref_type('Contract')
    owner_id: TextId
    contractor_id: TextId
    status: Literal['effective', 'suspended', 'terminated', 'closed', 'pending']
    terms_ref: ref_type('ContractTerms')
    decision_profile_ref: ref_type('OwnerContractDecisionProfile')
    issue_refs: list[ref_type('ContractIssue')]
    change_rule_ref: ref_type('ContractChangeRule')


class OwnerContractDecisionView(CostSource):
    ref: ref_type('OwnerContractDecisionProfile')
    organization_id: TextId
    contract_ref: ref_type('Contract')
    authority_ref: ref_type('Authorization')
    choice: Literal['instruct', 'verify', 'agree_change', 'dispute', 'accept_undisputed', 'remedy']
    scope_choice: OwnerDesignScopeChoice
    requested_requirement_refs: list[ref_type('Requirement')]
    change_ref: ref_type('ContractChangeProposal') | None
    terms_ref: ref_type('ContractTerms') | None
    component_refs: list[ref_type('ClaimComponent')]
    acknowledged_issue_refs: list[ref_type('ContractIssue')]
    reviewed_terms_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    note: TextId


class OwnerContractAuthoredView(CostSource):
    contract_ref: ref_type('Contract')
    terms_ref: ref_type('ContractTerms')
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class OwnerContractTermsView(CostSource):
    ref: ref_type('ContractTerms')
    contract_ref: ref_type('Contract')
    owner_id: TextId
    contractor_id: TextId
    scope_keys: list[TextId]
    price: Money
    work_window_ref: ref_type('TimeWindow')
    clause_refs: list[ref_type('ContractClause')]
    retained_obligation_refs: list[ref_type('Obligation')]
    prior_terms_ref: ref_type('ContractTerms') | None
    change_ref: ref_type('ContractChangeProposal') | None
    status: Literal['effective', 'proposed', 'superseded']


def contract_change_digest(terms):
    raw = terms.model_dump(mode='json', exclude={'evidence_refs', 'available_at', 'effective_window', 'status'})
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class OwnerContractRuleView(CostSource):
    ref: ref_type('ContractChangeRule')
    contract_ref: ref_type('Contract')
    terms_ref: ref_type('ContractTerms')
    permitted_choices: list[Literal['instruct', 'verify', 'agree_change', 'dispute', 'accept_undisputed', 'remedy']]
    allow_partial_undisputed: bool
    required_change_assessment_codes: list[TextId]
    required_acceptance_party_ids: list[TextId]


class OwnerContractIssueView(OwnerContractAuthoredView):
    ref: ref_type('ContractIssue')
    status: Literal['open', 'resolved']
    component_refs: list[ref_type('ClaimComponent')]
    change_refs: list[ref_type('ContractChangeProposal')]
    resolution_basis_ref: ref_type('Evidence') | None


class OwnerContractEvidenceView(CostSource):
    ref: ref_type('CommittedEvidence')
    contract_ref: ref_type('Contract')
    original_record_ref: Reference
    content_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    original_evidence_refs: list[ref_type('Evidence')]


class OwnerContractRecordView(OwnerContractAuthoredView):
    ref: Reference
    content_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    record_kind: Literal['work', 'inspection', 'certificate', 'instruction', 'event']
    status: Literal['recorded', 'unknown', 'failed']


class OwnerContractAssessmentView(OwnerContractAuthoredView):
    ref: ref_type('ProfessionalAssessment')
    target_ref: ref_type('ContractChangeProposal') | ref_type('ClaimComponent') | ref_type('Requirement')
    assessment_code: TextId
    committed_evidence_refs: list[ref_type('CommittedEvidence')]
    status: Literal['ok', 'failed', 'unsupported']
    accepted: ValueState[bool]
    approved_amount: ValueState[Money]


class OwnerContractRequirementView(OwnerContractAuthoredView):
    ref: ref_type('Requirement')
    permitted_choices: list[Literal['instruct', 'verify', 'remedy']]
    condition_kind: Literal['professional', 'regulatory', 'funding', 'rights', 'other']
    permitted: ValueState[bool]
    satisfied: ValueState[bool]
    requires_expenditure: bool
    expenditure_cap: ValueState[Money]
    funding_source_ref: ref_type('FundingSource') | None
    assessment_refs: list[ref_type('ProfessionalAssessment')]


class OwnerContractChangeView(OwnerContractAuthoredView):
    ref: ref_type('ContractChangeProposal')
    replacement_terms_ref: ref_type('ContractTerms')
    issue_refs: list[ref_type('ContractIssue')]
    basis_kind: Literal['authorized_change', 'contract_adjustment', 'cost_overrun_only']
    basis_evidence_refs: list[ref_type('CommittedEvidence')]
    assessment_refs: list[ref_type('ProfessionalAssessment')]
    acceptance_refs: list[ref_type('PartyAcceptance')]
    incremental_amount: ValueState[Money]
    funding_source_ref: ref_type('FundingSource') | None
    status: Literal['proposed', 'withdrawn', 'superseded']


class OwnerContractAcceptanceView(OwnerContractAuthoredView):
    ref: ref_type('PartyAcceptance')
    run_id: TextId
    party_id: TextId
    change_ref: ref_type('ContractChangeProposal')
    replacement_terms_ref: ref_type('ContractTerms')
    agreement_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    choice: Literal['accept', 'revise', 'reject']
    status: Literal['active', 'withdrawn']
    explicit_acceptance: ValueState[bool]


class OwnerContractClaimView(OwnerContractAuthoredView):
    ref: ref_type('ClaimComponent')
    claimant_id: TextId
    issue_ref: ref_type('ContractIssue')
    obligation_ref: ref_type('Obligation') | None
    basis_kind: Literal['certified_entitlement', 'contractual_claim', 'cost_overrun_only']
    claimed_amount: ValueState[Money]
    disputed: bool
    assessment_refs: list[ref_type('ProfessionalAssessment')]
    committed_evidence_refs: list[ref_type('CommittedEvidence')]


class OwnerContractFundingView(CostSource):
    ref: ref_type('FundingPosition')
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    source_refs: list[ref_type('FundingSource')]


class OwnerContractCashSourceView(CostSource):
    ref: ref_type('FundingSource')
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    reservation_refs: list[ref_type('CashReservation')]
    permitted_contract_refs: list[ref_type('Contract')]


class OwnerContractReservationView(CostSource):
    ref: ref_type('CashReservation')
    source_ref: ref_type('FundingSource')
    organization_id: TextId
    as_of: TimePoint
    amount: Money
    status: Literal['held', 'released', 'consumed']
    disposition_basis_ref: ref_type('Evidence')


class OwnerContractReferenceView(CostSource):
    ref: Reference
    contract_ref: ref_type('Contract')
    terms_ref: ref_type('ContractTerms')
    permitted: ValueState[bool]


def owner_contract_schemas():
    registry = common_projection_schemas()
    schemas = {
        'Contract': OwnerContractView, 'ContractTerms': OwnerContractTermsView,
        'OwnerContractDecisionProfile': OwnerContractDecisionView, 'ContractChangeRule': OwnerContractRuleView,
        'ContractIssue': OwnerContractIssueView, 'CommittedEvidence': OwnerContractEvidenceView,
        'ProfessionalAssessment': OwnerContractAssessmentView, 'Requirement': OwnerContractRequirementView,
        'ContractChangeProposal': OwnerContractChangeView, 'PartyAcceptance': OwnerContractAcceptanceView,
        'ClaimComponent': OwnerContractClaimView, 'FundingPosition': OwnerContractFundingView,
        'FundingSource': OwnerContractCashSourceView, 'CashReservation': OwnerContractReservationView,
        **{kind: OwnerContractRecordView for kind in ('WorkExecution', 'InspectionResult', 'PaymentCertificate', 'ContractInstruction', 'Event')},
        **{kind: OwnerContractReferenceView for kind in ('ContractClause', 'Obligation')},
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView, 'ClockProfile': ServiceClockView,
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
