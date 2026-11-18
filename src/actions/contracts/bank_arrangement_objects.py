"""Received arrangement inputs; formal commitment remains host-owned."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.bank_credit_objects import (
    CreditBankPortfolioView, CreditCaseView, CreditCommitmentView, CreditLendingCapacityView,
    CreditProjectView, CreditWorkView,
    nonnegative_money, unique_identities,
)
from src.actions.contracts.bank_objects import FinanceApplicationView, SourcedBankProjection
from src.actions.contracts.bank_quote_objects import QuoteConditionView, QuoteReservationView
from src.actions.contracts.common import Money, ScopeRef, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_financing_objects import FinancingOfferView, FinancingTerms
from src.methods.models import Digest


def accepted_offer_digest(offer):
    fields = ('ref', 'application_ref', 'lender_id', 'scope_ref', 'terms', 'reservation_policy_ref')
    data = offer.model_dump(mode='json') if hasattr(offer, 'model_dump') else offer
    return hashlib.sha256(json.dumps({key: data[key] for key in fields}, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class ArrangementOfferView(FinancingOfferView):
    reservation_policy_ref: ref_type('ReservationPolicy')


class ArrangementAcceptanceView(SourcedBankProjection):
    ref: ref_type('PartyAcceptance')
    offer_ref: ref_type('FinanceOffer')
    scope_ref: ScopeRef
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    action_id: Literal['OWN-A05', 'CONTRACTOR-A10', 'SUPPLIER-A10']
    decision: Literal['accept', 'reject', 'revise', 'withdrawn']
    accepted_terms: FinancingTerms
    agreement_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    recorded_decision_ref: ref_type('RecordedDecision')
    accepted_at: TimePoint
    available_at: TimePoint


class ArrangementBorrowerDecisionView(SourcedBankProjection):
    ref: ref_type('RecordedDecision')
    offer_ref: ref_type('FinanceOffer')
    scope_ref: ScopeRef
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    action_id: Literal['OWN-A05', 'CONTRACTOR-A10', 'SUPPLIER-A10']
    decision: Literal['accept', 'reject', 'revise', 'withdrawn']
    accepted_terms: FinancingTerms
    agreement_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    decided_at: TimePoint


class OwnerFinancingAcceptanceReceiptView(SourcedBankProjection):
    """Actual independent Owner acceptance received by the bank, never formed here."""
    ref: ref_type('FinancingAcceptanceReceipt')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    offer_ref: ref_type('FinanceOffer')
    acceptance_ref: ref_type('PartyAcceptance')
    acceptance_sha256: Digest
    recorded_decision_ref: ref_type('RecordedDecision')
    recorded_decision_sha256: Digest
    scope: ScopeRef
    received_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class ArrangementFormationView(SourcedBankProjection):
    ref: ref_type('FinanceFormationProfile')
    offer_ref: ref_type('FinanceOffer')
    borrower_id: TextId
    lender_id: TextId
    scope_ref: ScopeRef
    authority_ref: ref_type('Authorization')
    maximum_principal: ValueState[Money]
    allowed_product_refs: list[ref_type('FinanceProductProfile')]
    allowed_pricing_refs: list[ref_type('PricingRule')]
    formation_condition_refs: list[ref_type('Requirement')]
    requote_requirement_refs: Annotated[list[ref_type('Requirement')], Field(min_length=1)]
    allow_signed_pending_conditions: bool
    time_rule_ref: ref_type('FinanceTimeRule')
    effective_window: TimeWindow

    @model_validator(mode='after')
    def original_limits(self):
        nonnegative_money(self.maximum_principal)
        for refs in (self.allowed_product_refs, self.allowed_pricing_refs,
                     self.formation_condition_refs, self.requote_requirement_refs):
            unique_identities(refs)
        return self


class ArrangementTimeRuleView(SourcedBankProjection):
    ref: ref_type('FinanceTimeRule')
    lender_id: TextId
    product_ref: ref_type('FinanceProductProfile')
    equality_rule: Literal['expiry_first', 'acceptance_first']
    effective_window: TimeWindow


class ArrangementCommitmentView(CreditCommitmentView):
    origin_offer_ref: ref_type('FinanceOffer') | None
    origin_arrangement_ref: ref_type('FinanceArrangement') | None


def bank_arrangement_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ('FinanceOffer', ArrangementOfferView), ('PartyAcceptance', ArrangementAcceptanceView),
        ('RecordedDecision', ArrangementBorrowerDecisionView), ('FinanceFormationProfile', ArrangementFormationView),
        ('FinancingAcceptanceReceipt', OwnerFinancingAcceptanceReceiptView),
        ('FinanceTimeRule', ArrangementTimeRuleView), ('Requirement', QuoteConditionView),
        ('ReservationPolicy', QuoteReservationView), ('FinanceApplication', FinanceApplicationView),
        ('FinancePortfolio', CreditBankPortfolioView), ('LendingCapacity', CreditLendingCapacityView),
        ('FinanceCommitment', ArrangementCommitmentView),
        ('OwnerCase', CreditCaseView), ('Project', CreditProjectView), ('WorkScope', CreditWorkView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
