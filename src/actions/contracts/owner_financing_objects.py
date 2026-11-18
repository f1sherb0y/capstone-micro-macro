"""Closed received projections for OWN-A05 funding choices.

Amounts here are sourced facts or explicitly proposed plans. These projections
do not create an application, acceptance, arrangement, loan, cash or payment.
Cross-object identity, authority, currency/path and cash-calendar checks belong
to the authorized processor; a structurally valid offer is not an eligible one.
"""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.bank_objects import (
    BorrowerOrganizationView, FinanceApplicationView, FinanceProductProfileView,
    FundingPurposeView,
)
from src.actions.contracts.common import Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, Unknown, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_objects import SourcedOwnerProjection
from src.actions.contracts.owner_study_objects import StudyScopeChoice, unique_refs
from src.methods.models import Digest


FundingChoice = Literal['own_funds', 'apply', 'accept_offer', 'negotiate', 'resize', 'no_finance']


def nonnegative(value):
    if value.state == 'known' and Decimal(value.value.value) < 0:
        raise ValueError('Known funding amounts cannot be negative')


class FinancingLine(StrictRecord):
    """Source OwnerFundingLine, preserving forecasts and unknown amounts."""
    window_ref: ref_type('TimeWindow')
    source_ref: ref_type('FundingSource')
    available: ValueState[Money]
    planned_use: ValueState[Money]
    restriction_refs: list[ref_type('FundingRestriction')]

    @model_validator(mode='after')
    def declared_amounts(self):
        nonnegative(self.available)
        nonnegative(self.planned_use)
        unique_refs(self.restriction_refs)
        return self


class FinancingApplicationDraft(StrictRecord):
    """Exact system-interface draft, with additional local business checks."""
    borrower_id: TextId
    lender_id: TextId
    scope_ref: ScopeRef
    requested: Money
    purpose_ref: ref_type('FundingPurpose')
    product_candidates: list[ref_type('FinanceProductProfile')]
    disclosure_refs: list[ref_type('Evidence')]
    applicant_authority_ref: ref_type('Authorization')

    @model_validator(mode='after')
    def bounded_application(self):
        if Decimal(self.requested.value) <= 0:
            raise ValueError('Financing application amount must be positive')
        unique_refs(self.product_candidates)
        unique_refs(self.disclosure_refs)
        return self


class FinancingTerms(StrictRecord):
    """Exact BankTermDraft stored inside one immutable FinanceOffer version."""
    borrower_id: TextId
    product_ref: ref_type('FinanceProductProfile')
    principal_limit: Money
    purpose_ref: ref_type('FundingPurpose')
    tenor_ref: ref_type('TimeWindow')
    pricing_ref: ref_type('PricingRule')
    fee_rule_refs: list[ref_type('FeeRule')]
    repayment_rule_ref: ref_type('RepaymentRule')
    validity_ref: ref_type('TimeWindow')
    condition_refs: list[ref_type('Requirement')]

    @model_validator(mode='after')
    def exact_terms(self):
        if Decimal(self.principal_limit.value) <= 0:
            raise ValueError('Financing offer principal must be positive')
        unique_refs(self.fee_rule_refs)
        unique_refs(self.condition_refs)
        return self


class FinancingOfferView(SourcedOwnerProjection):
    ref: ref_type('FinanceOffer')
    lender_id: TextId
    application_ref: ref_type('FinanceApplication')
    scope_ref: ScopeRef
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    originating_action_id: Literal['BANK-A04']
    terms: FinancingTerms
    priority: ValueState[int]
    status: Literal['offered', 'withdrawn', 'expired', 'superseded']
    issued_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow
    proposed_releases: list['FinancingPayment']


class OwnerFinancingOfferReceiptView(SourcedOwnerProjection):
    """Observed registered Bank quotation received by the Owner, without acceptance."""
    ref: ref_type('FinanceOfferReceipt')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    offer_ref: ref_type('FinanceOffer')
    offer_sha256: Digest
    reservation_policy_ref: ref_type('ReservationPolicy')
    scope: ScopeRef
    received_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class FinancingConditionView(SourcedOwnerProjection):
    ref: ref_type('Requirement')
    scope_ref: ScopeRef
    borrower_id: TextId
    lender_id: TextId
    offer_ref: ref_type('FinanceOffer') | None
    arrangement_ref: ref_type('FinanceArrangement') | None
    permitted: ValueState[bool]
    verifier_actor_id: TextId
    verifier_function_ref: ref_type('FunctionAssignment')
    verifier_authority_ref: ref_type('Authorization')
    verifier_action_id: TextId
    verified_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def exact_stage(self):
        if (self.offer_ref is None) == (self.arrangement_ref is None):
            raise ValueError('Financing condition binds exactly one offer or arrangement stage')
        return self


class FinancingArrangementView(SourcedOwnerProjection):
    ref: ref_type('FinanceArrangement')
    offer_ref: ref_type('FinanceOffer')
    borrower_id: TextId
    lender_id: TextId
    scope_ref: ScopeRef
    source_ref: ref_type('FundingSource')
    borrower_acceptance_ref: ref_type('PartyAcceptance')
    lender_confirmation_ref: ref_type('PartyAcceptance')
    undrawn_amount: ValueState[Money]
    condition_refs: list[ref_type('Requirement')]
    status: Literal['signed_pending', 'active', 'suspended', 'expired', 'closed']
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def actual_arrangement(self):
        nonnegative(self.undrawn_amount)
        unique_refs(self.condition_refs)
        if self.borrower_acceptance_ref == self.lender_confirmation_ref:
            raise ValueError('Financing arrangement requires independent party decisions')
        return self


class FinancingRelease(StrictRecord):
    ref: ref_type('FundingRelease')
    source_ref: ref_type('FundingSource')
    time: TimePoint
    amount: ValueState[Money]
    state: Literal['committed', 'forecast', 'received', 'cancelled']
    approval_ref: ref_type('Authorization') | ref_type('FinanceArrangement') | ref_type('FundingApproval') | None
    condition_refs: list[ref_type('Requirement')]
    available_at: TimePoint

    @model_validator(mode='after')
    def approved_is_not_cash(self):
        nonnegative(self.amount)
        unique_refs(self.condition_refs)
        if self.state == 'committed' and self.approval_ref is None:
            raise ValueError('Committed funding requires an explicit approval or arrangement')
        return self


class FinancingSourceView(SourcedOwnerProjection):
    ref: ref_type('FundingSource')
    organization_id: TextId
    account_ref: ref_type('Account')
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    restriction_refs: list[ref_type('FundingRestriction')]
    releases: list[FinancingRelease]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']

    @model_validator(mode='after')
    def one_source(self):
        nonnegative(self.actual_cash)
        nonnegative(self.restricted_cash)
        unique_refs(self.restriction_refs)
        unique_refs([release.ref for release in self.releases])
        if any(release.source_ref != self.ref for release in self.releases):
            raise ValueError('Funding release changes its exact source version')
        return self


class FinancingRestrictionView(SourcedOwnerProjection):
    ref: ref_type('FundingRestriction')
    source_ref: ref_type('FundingSource')
    organization_id: TextId
    scope_ref: ScopeRef
    purpose_ref: ref_type('FundingPurpose')
    permitted: ValueState[bool]
    effective_window: TimeWindow


class FinancingObligationView(SourcedOwnerProjection):
    ref: ref_type('Obligation')
    debtor_id: TextId
    payee_id: TextId
    source_ref: ref_type('FundingSource')
    origin_scope: ScopeRef
    debt_ref: ref_type('Debt') | None
    component_refs: Annotated[list[ref_type('SettlementComponent')], Field(min_length=1)]
    actual_due: ValueState[Money]
    actual_paid: ValueState[Money]
    due_at: TimePoint
    as_of: TimePoint

    @model_validator(mode='after')
    def actual_unpaid(self):
        nonnegative(self.actual_due)
        nonnegative(self.actual_paid)
        unique_refs(self.component_refs)
        if self.actual_due.state == self.actual_paid.state == 'known':
            due, paid = self.actual_due.value, self.actual_paid.value
            if due.currency != paid.currency or Decimal(paid.value) > Decimal(due.value):
                raise ValueError('Paid debt cannot change currency or exceed actual due amount')
        return self


class FinancingDebtView(SourcedOwnerProjection):
    ref: ref_type('Debt')
    borrower_id: TextId
    lender_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    origin_scope: ScopeRef
    outstanding_principal: ValueState[Money]
    obligation_refs: list[ref_type('Obligation')]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']

    @model_validator(mode='after')
    def preserve_debt(self):
        nonnegative(self.outstanding_principal)
        unique_refs(self.obligation_refs)
        return self


class FinancingRevisionView(SourcedOwnerProjection):
    ref: ref_type('FundingPlan')
    organization_id: TextId
    borrower_id: TextId
    prior_profile_ref: ref_type('FundingProfile')
    revised_lines: list[FinancingLine]
    change_scope: StudyScopeChoice
    authority_ref: ref_type('Authorization')
    available_at: TimePoint
    effective_window: TimeWindow


class FinancingProfileView(SourcedOwnerProjection):
    monthly_capacity_observation_ref: ref_type('MonthlyOwnerCapacityObservation') | None = None
    ref: ref_type('FundingProfile')
    organization_id: TextId
    borrower_id: TextId
    borrower_ref: ref_type('Organization')
    scope_ref: ScopeRef
    purpose_ref: ref_type('FundingPurpose')
    authority_ref: ref_type('Authorization')
    borrower_authority_ref: ref_type('Authorization')
    policy: ValueState[Literal['evaluate', 'own_funds', 'apply', 'accept_offer', 'negotiate', 'resize', 'no_finance', 'defer']]
    on_unavailable: ValueState[Literal['apply', 'resize', 'no_finance', 'defer']]
    source_refs: list[ref_type('FundingSource')]
    debt_refs: list[ref_type('Debt')]
    obligation_refs: list[ref_type('Obligation')]
    arrangement_refs: list[ref_type('FinanceArrangement')]
    selected_offer_ref: ref_type('FinanceOffer') | None
    application: FinancingApplicationDraft | None
    revision_ref: ref_type('FundingPlan') | None
    question_refs: list[ref_type('Issue')]
    required_condition_refs: list[ref_type('Requirement')]
    currency: TextId
    funding_lines: list[FinancingLine]
    financing_cost_cap: ValueState[Money]
    cash_method_ref: ref_type('Method')
    selection_method_ref: ref_type('Method')
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    effective_window: TimeWindow

    @model_validator(mode='after')
    def one_portfolio(self):
        if self.borrower_ref.id != self.borrower_id:
            raise ValueError('Funding profile changes its borrower identity')
        for refs in (self.source_refs, self.debt_refs, self.obligation_refs, self.arrangement_refs,
                     self.question_refs, self.required_condition_refs):
            unique_refs(refs)
        return self


class FinancingAccountView(SourcedOwnerProjection):
    ref: ref_type('Account')
    organization_id: TextId
    source_ref: ref_type('FundingSource')
    currency: TextId
    region_id: TextId
    permitted_project_region_ids: ValueState[list[TextId]] = Field(default_factory=lambda: Unknown(
        state='unknown',reason_code='project_region_permission_not_supplied',missing_refs=[]))
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    debt_refs: list[ref_type('Debt')]
    obligation_refs: list[ref_type('Obligation')]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']

    @model_validator(mode='after')
    def actual_account(self):
        nonnegative(self.actual_cash)
        nonnegative(self.restricted_cash)
        unique_refs(self.debt_refs)
        unique_refs(self.obligation_refs)
        return self


class FinancingPayment(StrictRecord):
    local_key: TextId
    source_ref: ref_type('FundingSource')
    time: TimePoint
    amount: Money

    @model_validator(mode='after')
    def positive(self):
        if Decimal(self.amount.value) <= 0:
            raise ValueError('Financing schedule payments must be positive')
        return self


class FinancingRuleView(SourcedOwnerProjection):
    offer_ref: ref_type('FinanceOffer')
    borrower_id: TextId
    lender_id: TextId
    scope_ref: ScopeRef
    schedule: ValueState[list[FinancingPayment]]
    coverage: Literal['complete', 'partial', 'unknown']
    available_at: TimePoint
    effective_window: TimeWindow


class FinancingPricingView(FinancingRuleView):
    ref: ref_type('PricingRule')


class FinancingFeeView(FinancingRuleView):
    ref: ref_type('FeeRule')


class FinancingRepaymentView(FinancingRuleView):
    ref: ref_type('RepaymentRule')


class FinancingAcceptanceView(SourcedOwnerProjection):
    ref: ref_type('PartyAcceptance')
    offer_ref: ref_type('FinanceOffer')
    scope_ref: ScopeRef
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    action_id: Literal['OWN-A05', 'BANK-A05']
    decision: Literal['accept', 'reject', 'withdrawn']
    accepted_at: TimePoint


class FinancingApprovalView(SourcedOwnerProjection):
    ref: ref_type('FundingApproval')
    source_ref: ref_type('FundingSource')
    organization_id: TextId
    scope_ref: ScopeRef
    purpose_ref: ref_type('FundingPurpose')
    amount: Money
    release_time: TimePoint
    approved: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow


class FinancingIssueView(SourcedOwnerProjection):
    ref: ref_type('Issue')
    profile_ref: ref_type('FundingProfile')
    offer_ref: ref_type('FinanceOffer')
    subject_ref: ref_type('BusinessObject')
    scope_ref: ScopeRef
    local_key: TextId
    request: TextId
    requirement_refs: list[ref_type('Requirement')]
    status: Literal['unresolved', 'resolved', 'withdrawn']
    available_at: TimePoint
    effective_window: TimeWindow


class FinancingSubjectView(SourcedOwnerProjection):
    ref: ref_type('BusinessObject')
    offer_ref: ref_type('FinanceOffer')
    scope_ref: ScopeRef


class FinancingCaseView(SourcedOwnerProjection):
    ref: ref_type('OwnerCase')
    organization_id: TextId
    available_at: TimePoint
    status: Literal['active', 'closed']


class FinancingProjectView(SourcedOwnerProjection):
    ref: ref_type('Project')
    owner_organization_id: TextId
    available_at: TimePoint
    status: Literal['active', 'suspended', 'closed']


class FinancingWorkView(SourcedOwnerProjection):
    ref: ref_type('WorkScope')
    scope_ref: ScopeRef
    organization_id: TextId
    purpose_ref: ref_type('FundingPurpose')
    available_at: TimePoint
    effective_window: TimeWindow


FinancingOfferView.model_rebuild()


def owner_financing_schemas():
    from src.actions.contracts.bank_quote_objects import QuoteAuthorityPolicyView
    from src.actions.contracts.owner_monthly_capacity import MonthlyOwnerCapacityObservation
    registry = common_projection_schemas()
    for kind, schema in (
        ('Organization', BorrowerOrganizationView), ('FundingPurpose', FundingPurposeView),
        ('FinanceProductProfile', FinanceProductProfileView), ('FinanceApplication', FinanceApplicationView),
        ('FinanceOffer', FinancingOfferView), ('FinanceArrangement', FinancingArrangementView),
        ('FinanceOfferReceipt', OwnerFinancingOfferReceiptView),
        ('FundingProfile', FinancingProfileView), ('FundingSource', FinancingSourceView),
        ('FundingRestriction', FinancingRestrictionView), ('Requirement', FinancingConditionView),
        ('Debt', FinancingDebtView), ('Obligation', FinancingObligationView),
        ('FundingPlan', FinancingRevisionView),
        ('Account', FinancingAccountView), ('PartyAcceptance', FinancingAcceptanceView),
        ('PricingRule', FinancingPricingView), ('FeeRule', FinancingFeeView),
        ('RepaymentRule', FinancingRepaymentView), ('FundingApproval', FinancingApprovalView),
        ('Issue', FinancingIssueView),
        ('BusinessObject', FinancingSubjectView),
        ('OwnerCase', FinancingCaseView), ('Project', FinancingProjectView),
        ('WorkScope', FinancingWorkView),
        ('QuoteAuthorityPolicy', QuoteAuthorityPolicyView),
        ('MonthlyOwnerCapacityObservation', MonthlyOwnerCapacityObservation),
    ):
        registry.register_kind(kind, schema, str)
    return registry
