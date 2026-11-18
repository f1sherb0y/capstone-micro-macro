"""Original final contract terms and current contractor commitment snapshots."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Money, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_amendment_objects import ContractorAmendmentBidView, ContractorAmendmentSubmissionView
from src.actions.contracts.contractor_bid_objects import ContractorBidReferenceView, contractor_bid_schemas
from src.actions.contracts.qs_cost_objects import CostSource


class ContractorFormationOfferView(CostSource):
    ref: ref_type('ContractOffer')
    bid_ref: ref_type('Bid')
    package_ref: ref_type('ProcurementPackage')
    round_ref: ref_type('TenderRound')
    contractor_id: TextId
    client_id: TextId
    terms_ref: ref_type('ContractTerms')
    response_window_ref: ref_type('TimeWindow')
    status: Literal['active', 'withdrawn', 'superseded']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['OWN-A09', 'OWN-A10']


class ContractorFormationTermsView(CostSource):
    ref: ref_type('ContractTerms')
    offer_ref: ref_type('ContractOffer')
    bid_ref: ref_type('Bid')
    package_ref: ref_type('ProcurementPackage')
    round_ref: ref_type('TenderRound')
    contractor_id: TextId
    client_id: TextId
    required_party_ids: Annotated[list[TextId], Field(min_length=2)]
    price: Money
    scope_keys: Annotated[list[TextId], Field(min_length=1)]
    programme_ref: ref_type('ProgrammeProposal')
    deliverable_refs: list[ref_type('ReleasedDeliverable')]
    exclusion_refs: list[ref_type('Requirement')]
    clause_refs: Annotated[list[ref_type('ContractClause')], Field(min_length=1)]
    condition_refs: list[ref_type('Requirement')]
    payment_refs: list[ref_type('ContractPayment')]
    work_window: TimeWindow
    contract_template_ref: ref_type('ContractTemplate')
    amendment_refs: list[ref_type('ContractChangeRequest')]


def contractor_agreement_digest(terms):
    raw = terms.model_dump(mode='json', exclude={'evidence_refs', 'available_at', 'effective_window'})
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class ContractorFormationProfileView(CostSource):
    ref: ref_type('ContractFormationProfile')
    organization_id: TextId
    offer_ref: ref_type('ContractOffer')
    terms_ref: ref_type('ContractTerms')
    authority_ref: ref_type('Authorization')
    choice: Literal['accept', 'revise', 'reject']
    explicit_acceptance: ValueState[bool]
    reviewed_agreement_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    reviewed_clause_refs: list[ref_type('ContractClause')]
    cash_plan_ref: ref_type('ContractFundingPlan') | None
    requirement_changes: list[ref_type('ContractChangeRequest')]
    note: TextId


class ContractorFormationAcceptanceView(CostSource):
    ref: ref_type('PartyAcceptance')
    run_id: TextId
    offer_ref: ref_type('ContractOffer')
    terms_ref: ref_type('ContractTerms')
    bid_ref: ref_type('Bid')
    party_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    agreement_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    choice: Literal['accept', 'revise', 'reject']
    explicit_acceptance: ValueState[bool]
    status: Literal['active', 'withdrawn']
    decided_at: TimePoint


class ContractorFormationReferenceView(CostSource):
    ref: ref_type('ContractClause') | ref_type('ContractChangeRequest') | ref_type('ContractTemplate')
    offer_ref: ref_type('ContractOffer')
    terms_ref: ref_type('ContractTerms')
    bid_ref: ref_type('Bid')
    allowed: ValueState[bool]
    changed_field_codes: list[Literal['price']]
    stage: Literal['acceptance', 'signature', 'effectiveness', 'construction']
    satisfied: ValueState[bool]


class ContractorFormationConditionBinding(StrictRecord):
    offer_ref: ref_type('ContractOffer')
    terms_ref: ref_type('ContractTerms')
    bid_ref: ref_type('Bid')
    stage: Literal['acceptance', 'signature', 'effectiveness', 'construction']
    satisfied: ValueState[bool]


class ContractorFormationRequirementView(ContractorBidReferenceView):
    ref: ref_type('Requirement')
    formation: ContractorFormationConditionBinding | None


class ContractorFormationFundingView(CostSource):
    ref: ref_type('FundingPosition')
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    source_refs: list[ref_type('FundingSource')]
    existing_payment_refs: list[ref_type('FundingCommitment')]
    inflow_refs: list[ref_type('FundingCommitment')]


class ContractorFormationCashSourceView(CostSource):
    ref: ref_type('FundingSource')
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    allowed_offer_refs: list[ref_type('ContractOffer')]
    permission_basis_ref: ref_type('Evidence')


class ContractorFormationCashPaymentView(CostSource):
    ref: ref_type('FundingCommitment')
    organization_id: TextId
    source_ref: ref_type('FundingSource')
    offer_ref: ref_type('ContractOffer') | None
    terms_ref: ref_type('ContractTerms') | None
    contract_payment_ref: ref_type('ContractPayment') | None
    component_refs: Annotated[list[ref_type('SettlementComponent')], Field(min_length=1)]
    time: TimePoint
    amount: ValueState[Money]
    direction: Literal['inflow', 'outflow']
    status: Literal['committed', 'released', 'received', 'paid']
    planning_available: ValueState[bool]
    disposition_basis_ref: ref_type('Evidence')


class ContractorFormationContractPaymentView(CostSource):
    ref: ref_type('ContractPayment')
    offer_ref: ref_type('ContractOffer')
    terms_ref: ref_type('ContractTerms')
    payer_id: TextId
    payee_id: TextId
    time: TimePoint
    amount: ValueState[Money]


class ContractorFormationCashPlanView(CostSource):
    ref: ref_type('ContractFundingPlan')
    organization_id: TextId
    offer_ref: ref_type('ContractOffer')
    terms_ref: ref_type('ContractTerms')
    coverage: Literal['complete', 'partial', 'unknown']
    proposed_outflow_refs: list[ref_type('FundingCommitment')]
    proposed_inflow_refs: list[ref_type('FundingCommitment')]
    cost_basis_refs: list[ref_type('CostBasis')]


class ContractorFormationCashComponentView(CostSource):
    ref: ref_type('SettlementComponent')
    organization_id: TextId
    source_ref: ref_type('FundingSource')
    time: TimePoint
    direction: Literal['inflow', 'outflow']
    amount: ValueState[Money]
    cost_basis_ref: ref_type('CostBasis') | None


def contractor_formation_schemas():
    return contractor_bid_schemas({
        'ContractOffer': ContractorFormationOfferView, 'ContractTerms': ContractorFormationTermsView,
        'Bid': ContractorAmendmentBidView, 'SubmissionExecution': ContractorAmendmentSubmissionView,
        'ContractFormationProfile': ContractorFormationProfileView,
        'PartyAcceptance': ContractorFormationAcceptanceView,
        'FundingPosition': ContractorFormationFundingView, 'FundingSource': ContractorFormationCashSourceView,
        'FundingCommitment': ContractorFormationCashPaymentView, 'ContractFundingPlan': ContractorFormationCashPlanView,
        'ContractPayment': ContractorFormationContractPaymentView,
        **{kind: ContractorFormationReferenceView for kind in ('ContractClause', 'ContractChangeRequest', 'ContractTemplate')},
        # Procurement exclusion Requirements retain their A02 scope mapping.
        'Requirement': ContractorFormationRequirementView,
        'SettlementComponent': ContractorFormationCashComponentView,
    })
