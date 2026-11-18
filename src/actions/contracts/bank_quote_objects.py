"""Received BANK-A04 assessment projections, without creating an assessment.

The host must supply a real source object or explicitly synthetic fixture.
Schema validation does not prove authorship, dependency freshness, professional
work registration or quote eligibility. Those require authorized source reads.
"""
from decimal import Decimal
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.bank_credit_objects import (
    CreditConditionView, bank_credit_schemas, nonnegative_money, unique_identities,
)
from src.actions.contracts.bank_objects import (
    BorrowerOrganizationView, FinanceApplicationView, FinanceProductProfileView,
    FundingPurposeView, SourcedBankProjection,
)
from src.actions.contracts.catalog import ContractCatalog
from src.actions.contracts.common import (
    DecimalString, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type,
    walk_references,
)
from src.actions.contracts.domain import common_projection_schemas
from src.methods.models import Digest


# Reuse the frozen public A03 field and branch definitions, rather than invent
# a second interpretation of the review output at the quotation boundary.
_REVIEW = ContractCatalog().get('BANK-A03')
CreditReviewInput = _REVIEW.input_model
CreditReviewPayload = _REVIEW.payload_type


class QuoteAssessmentDependency(StrictRecord):
    """Exact source version plus digest to be rechecked by a future processor."""
    ref: Reference
    projection_sha256: Digest


class QuoteCreditAssessmentView(SourcedBankProjection):
    ref: ref_type('CreditAssessment')
    application_ref: ref_type('FinanceApplication')
    product_ref: ref_type('FinanceProductProfile')
    borrower_id: TextId
    lender_id: TextId
    scope_ref: ScopeRef
    recorded_decision_ref: ref_type('RecordedDecision')
    source_run_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    authority_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    originating_action_id: Literal['BANK-A03']
    review_input: CreditReviewInput
    review_payload: CreditReviewPayload
    source_dependencies: Annotated[list[QuoteAssessmentDependency], Field(min_length=1)]
    dependency_coverage: Literal['complete', 'partial', 'unknown']
    method_audit_refs: list[ref_type('Evidence')]
    reviewed_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow
    status: Literal['recorded', 'withdrawn', 'superseded']

    @model_validator(mode='after')
    def retained_review(self):
        _REVIEW.validate_decision(self.review_input, self.review_payload.model_dump(mode='python'))
        if (self.application_ref != self.review_input.application_ref
                or self.product_ref != self.review_input.product_ref):
            raise ValueError('Received assessment changes its reviewed application or product version')
        clocks = (self.reviewed_at.clock_ref, self.available_at.clock_ref,
                  self.effective_window.start.clock_ref)
        if len(set(clocks)) != 1 or self.reviewed_at.offset > self.available_at.offset:
            raise ValueError('Received assessment requires ordered points on one exact business clock')
        if not self.effective_window.contains(self.reviewed_at):
            raise ValueError('Received assessment validity excludes its review point')
        unique_identities(self.authority_refs)
        unique_identities(self.method_audit_refs)
        unique_identities(self.evidence_refs)
        unique_identities([row.ref for row in self.source_dependencies])
        dependencies = {row.ref.key() for row in self.source_dependencies}
        if self.ref.key() in dependencies:
            raise ValueError('An assessment cannot be a source of its own review')
        required = {ref.key() for value in (
            self.review_input, self.review_payload, self.scope_ref,
            self.recorded_decision_ref, self.author_function_ref, self.authority_refs,
            self.method_audit_refs, self.evidence_refs,
        ) for ref in walk_references(value)}
        if not required <= dependencies:
            raise ValueError('Received assessment omits an explicitly referenced source dependency')
        if self.review_payload.assessed_amount.state == 'known' and not self.method_audit_refs:
            raise ValueError('Known assessment amount must retain source method audit evidence')
        return self


def bank_quote_assessment_schemas():
    """Only supported received projections; remaining quote kinds stay absent."""
    registry = common_projection_schemas()
    for kind, schema in (
        ('CreditAssessment', QuoteCreditAssessmentView),
        ('FinanceApplication', FinanceApplicationView),
        ('FinanceProductProfile', FinanceProductProfileView),
        ('FundingPurpose', FundingPurposeView),
        ('Organization', BorrowerOrganizationView),
    ):
        registry.register_kind(kind, schema, str)
    return registry


def projection_digest(value):
    """Canonical digest of the received projection, including its exact refs."""
    return hashlib.sha256(json.dumps(value.model_dump(mode='json'), sort_keys=True,
                                    separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class QuoteRecordedReviewView(SourcedBankProjection):
    ref: ref_type('RecordedDecision')
    action_id: Literal['BANK-A03']
    source_run_id: TextId
    actor_id: TextId
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    scope_ref: ScopeRef
    business_time: TimePoint
    input: CreditReviewInput
    payload: CreditReviewPayload

    @model_validator(mode='after')
    def valid_review(self):
        _REVIEW.validate_decision(self.input, self.payload.model_dump(mode='python'))
        unique_identities(self.authority_refs)
        return self


class QuoteProductView(FinanceProductProfileView):
    quote_policy_ref: ref_type('QuoteProductPolicy')


class QuoteProductPolicyView(SourcedBankProjection):
    ref: ref_type('QuoteProductPolicy')
    product_ref: ref_type('FinanceProductProfile')
    lender_id: TextId
    pricing_refs: list[ref_type('PricingRule')]
    selection_rule: Literal['lowest_declared_priority']
    amount_rule: Literal['largest_feasible_authorized_amount']
    effective_window: TimeWindow

    @model_validator(mode='after')
    def distinct_prices(self):
        unique_identities(self.pricing_refs)
        return self


class QuoteAuthorityPolicyView(SourcedBankProjection):
    ref: ref_type('QuoteAuthorityPolicy')
    authority_ref: ref_type('Authorization')
    application_ref: ref_type('FinanceApplication')
    product_ref: ref_type('FinanceProductProfile')
    lender_id: TextId
    scope_ref: ScopeRef
    maximum_principal: ValueState[Money]
    permits_terms_reassessment: Literal[True]
    allowed_pricing_refs: list[ref_type('PricingRule')]
    allowed_reservation_refs: list[ref_type('ReservationPolicy')]
    effective_window: TimeWindow

    @model_validator(mode='after')
    def declared_limits(self):
        nonnegative_money(self.maximum_principal)
        unique_identities(self.allowed_pricing_refs)
        unique_identities(self.allowed_reservation_refs)
        return self


class QuotePayment(StrictRecord):
    local_key: TextId
    time: TimePoint
    principal_factor: DecimalString

    @model_validator(mode='after')
    def nonnegative_factor(self):
        if Decimal(self.principal_factor) < 0:
            raise ValueError('Quote payment factor cannot be negative')
        return self


class QuoteTermsSource(SourcedBankProjection):
    application_ref: ref_type('FinanceApplication')
    product_ref: ref_type('FinanceProductProfile')
    borrower_id: TextId
    lender_id: TextId
    effective_window: TimeWindow


class QuotePricingView(QuoteTermsSource):
    ref: ref_type('PricingRule')
    priority: ValueState[int]
    status: Literal['available', 'withdrawn']
    currency: TextId
    tenor_ref: ref_type('TimeWindow')
    validity_ref: ref_type('TimeWindow')
    fee_rule_refs: list[ref_type('FeeRule')]
    repayment_rule_ref: ref_type('RepaymentRule')
    reservation_policy_ref: ref_type('ReservationPolicy')
    funding_path_ref: ref_type('FundingPath')
    condition_refs: list[ref_type('Requirement')]
    assumption_ref: ref_type('Assumption')
    interest_payments: ValueState[list[QuotePayment]]

    @model_validator(mode='after')
    def complete_terms(self):
        unique_identities(self.fee_rule_refs)
        unique_identities(self.condition_refs)
        if self.interest_payments.state == 'known':
            keys = [p.local_key for p in self.interest_payments.value]
            if len(keys) != len(set(keys)):
                raise ValueError('Interest schedule repeats a payment')
        return self


class QuoteFeeView(QuoteTermsSource):
    ref: ref_type('FeeRule')
    time: TimePoint
    fixed_amount: ValueState[Money]
    principal_factor: ValueState[DecimalString]

    @model_validator(mode='after')
    def nonnegative_charge(self):
        nonnegative_money(self.fixed_amount)
        if self.principal_factor.state == 'known' and Decimal(self.principal_factor.value) < 0:
            raise ValueError('Fee factor cannot be negative')
        return self


class QuoteRepaymentView(QuoteTermsSource):
    ref: ref_type('RepaymentRule')
    payments: ValueState[list[QuotePayment]]


class QuoteReservationView(QuoteTermsSource):
    ref: ref_type('ReservationPolicy')
    binding: bool
    reserves_capacity: bool
    quantity_rule: Literal['offered_principal', 'none']
    expiry_ref: ref_type('TimeWindow')
    conversion_rule_ref: ref_type('Rule') | None
    release_rule_ref: ref_type('Rule') | None
    acceptance_action_id: Literal['OWN-A05', 'CONTRACTOR-A10', 'SUPPLIER-A10']

    @model_validator(mode='after')
    def explicit_reservation_lifecycle(self):
        if self.reserves_capacity != (self.quantity_rule == 'offered_principal'):
            raise ValueError('Reservation quantity rule contradicts the explicit reservation flag')
        if self.reserves_capacity and (self.conversion_rule_ref is None or self.release_rule_ref is None):
            raise ValueError('Reserved quote needs explicit conversion and release rules')
        return self


class QuoteFundingPathView(QuoteTermsSource):
    ref: ref_type('FundingPath')
    currency: TextId
    beneficiary_id: TextId
    destination_ref: ref_type('Account')
    funding_account_ref: ref_type('Account')
    permitted_region_ids: ValueState[list[TextId]]
    kind: Literal['borrower_account', 'direct_payment']


class QuoteConditionView(CreditConditionView):
    stage: Literal['arrangement_effective', 'per_draw']


def bank_quote_schemas():
    registry = common_projection_schemas()
    credit = bank_credit_schemas()
    replacements = {'FinanceProductProfile': QuoteProductView, 'Requirement': QuoteConditionView}
    for kind in sorted(credit.registered_kinds - registry.registered_kinds):
        schema, version_type = credit.schema_for(kind)
        registry.register_kind(kind, replacements.get(kind, schema), version_type)
    for kind, schema in (
        ('CreditAssessment', QuoteCreditAssessmentView), ('RecordedDecision', QuoteRecordedReviewView),
        ('QuoteProductPolicy', QuoteProductPolicyView), ('QuoteAuthorityPolicy', QuoteAuthorityPolicyView),
        ('PricingRule', QuotePricingView), ('FeeRule', QuoteFeeView),
        ('RepaymentRule', QuoteRepaymentView), ('ReservationPolicy', QuoteReservationView),
        ('FundingPath', QuoteFundingPathView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
