"""Closed, disclosed BANK-A03 review projections; never a second loan ledger.

Host projections bind the original public method kinds to registered local
calculators explicitly. Financial forecasts remain forecasts, and completeness
is a sourced assertion about the borrower's disclosed portfolio, not permission
to discover private records at another lender.
"""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.bank_objects import (
    BorrowerOrganizationView, FinanceApplicationView, FinanceProductProfileView,
    FundingPurposeView, SourcedBankProjection,
)
from src.actions.contracts.common import (
    DecimalString, Measured, Money, ScopeRef, StrictRecord, TextId, TimePoint,
    TimeWindow, ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas


def unique_identities(refs):
    """Different versions of one physical object cannot be counted twice."""
    if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
        raise ValueError('Credit review repeats an object identity across versions')


def nonnegative_money(state):
    if state.state == 'known' and Decimal(state.value.value) < 0:
        raise ValueError('Actual credit-review balances must be nonnegative')


class CreditMeasuredInterval(StrictRecord):
    lower: Measured
    upper: Measured

    @model_validator(mode='after')
    def ordered_same_unit(self):
        if self.lower.unit != self.upper.unit or Decimal(self.lower.value) > Decimal(self.upper.value):
            raise ValueError('Risk interval requires ordered endpoints in one explicit unit')
        return self


class CreditMoneyInterval(StrictRecord):
    lower: Money
    upper: Money

    @model_validator(mode='after')
    def ordered_same_currency(self):
        if (self.lower.currency != self.upper.currency or Decimal(self.lower.value) < 0
                or Decimal(self.lower.value) > Decimal(self.upper.value)):
            raise ValueError('Forecast interval requires ordered nonnegative amounts in one currency')
        return self


class CreditRiskDimensionView(SourcedBankProjection):
    ref: ref_type('RiskDimension')
    risk_method_ref: ref_type('RiskMethod')
    predicate: Literal['at_most', 'at_least']
    threshold: Measured
    hard: bool
    failure_rule_ref: ref_type('Rule')
    remedial_condition_ref: ref_type('Requirement') | None
    effective_window: TimeWindow


class CreditRiskObservationView(SourcedBankProjection):
    ref: ref_type('RiskObservation')
    application_ref: ref_type('FinanceApplication')
    borrower_id: TextId
    scope_ref: ScopeRef
    dimension_ref: ref_type('RiskDimension')
    category: Literal['financial', 'permit']
    interval: ValueState[CreditMeasuredInterval]
    observed_at: TimePoint
    effective_window: TimeWindow


class CreditRiskMethodView(SourcedBankProjection):
    ref: ref_type('RiskMethod')
    host_method_ref: ref_type('Method')
    lender_id: TextId
    product_ref: ref_type('FinanceProductProfile')
    capacity_ref: ref_type('LendingCapacity')
    dimension_refs: Annotated[list[ref_type('RiskDimension')], Field(min_length=1, max_length=64)]
    feasibility_method_ref: ref_type('FinanceFeasibilityMethod')
    decline_rule_ref: ref_type('Rule')
    effective_window: TimeWindow

    @model_validator(mode='after')
    def complete_dimensions(self):
        unique_identities(self.dimension_refs)
        return self


class CreditLoanFactor(StrictRecord):
    """Hypothetical amount per unit principal, supplied as an assumption."""
    local_key: TextId
    time: TimePoint
    kind: Literal['draw', 'principal', 'cost']
    factor: DecimalString
    assumption_ref: ref_type('Assumption')

    @model_validator(mode='after')
    def positive_factor(self):
        if Decimal(self.factor) <= 0:
            raise ValueError('Loan factors must be strictly positive')
        return self


class CreditFeasibilityMethodView(SourcedBankProjection):
    ref: ref_type('FinanceFeasibilityMethod')
    host_method_ref: ref_type('Method')
    lender_id: TextId
    product_ref: ref_type('FinanceProductProfile')
    currency: TextId
    minor_places: Annotated[int, Field(ge=0, le=8)]
    schedule: Annotated[list[CreditLoanFactor], Field(min_length=2, max_length=256)]
    assumption_refs: Annotated[list[ref_type('Assumption')], Field(min_length=1)]
    effective_window: TimeWindow

    @model_validator(mode='after')
    def declared_assumptions(self):
        unique_identities(self.assumption_refs)
        keys = [row.local_key for row in self.schedule]
        if len(set(keys)) != len(keys):
            raise ValueError('Hypothetical loan schedule repeats a payment')
        if {row.assumption_ref for row in self.schedule} != set(self.assumption_refs):
            raise ValueError('Schedule must retain its exact complete set of assumptions')
        return self


class CreditAssumptionView(SourcedBankProjection):
    ref: ref_type('Assumption')
    method_ref: ref_type('FinanceFeasibilityMethod')
    description: TextId
    effective_window: TimeWindow


class CreditRuleView(SourcedBankProjection):
    ref: ref_type('Rule')
    lender_id: TextId
    product_ref: ref_type('FinanceProductProfile')
    description: TextId
    effective_window: TimeWindow


class CreditPortfolioView(SourcedBankProjection):
    ref: ref_type('BorrowerPortfolio')
    borrower_id: TextId
    account_refs: Annotated[list[ref_type('Account')], Field(min_length=1, max_length=64)]
    debt_refs: list[ref_type('Debt')]
    obligation_refs: list[ref_type('Obligation')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint

    @model_validator(mode='after')
    def complete_identity_sets(self):
        for refs in (self.account_refs, self.debt_refs, self.obligation_refs):
            unique_identities(refs)
        return self


class CreditBankPortfolioView(SourcedBankProjection):
    ref: ref_type('FinancePortfolio')
    lender_id: TextId
    commitment_refs: list[ref_type('FinanceCommitment')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint

    @model_validator(mode='after')
    def original_commitments(self):
        unique_identities(self.commitment_refs)
        return self


class CreditLendingCapacityView(SourcedBankProjection):
    ref: ref_type('LendingCapacity')
    lender_id: TextId
    portfolio_ref: ref_type('FinancePortfolio')
    currency: TextId
    commitment_limit: ValueState[Money]
    as_of: TimePoint

    @model_validator(mode='after')
    def explicit_limit(self):
        nonnegative_money(self.commitment_limit)
        if self.commitment_limit.state == 'known' and self.commitment_limit.value.currency != self.currency:
            raise ValueError('Bank capacity limit changes its original currency')
        return self


class CreditCommitmentView(SourcedBankProjection):
    ref: ref_type('FinanceCommitment')
    lender_id: TextId
    borrower_id: TextId
    scope_ref: ScopeRef
    amount: ValueState[Money]
    status: Literal['reserved', 'committed', 'released']
    release_evidence_ref: ref_type('Evidence') | None
    as_of: TimePoint

    @model_validator(mode='after')
    def actual_occupancy(self):
        nonnegative_money(self.amount)
        if self.status == 'released' and self.release_evidence_ref is None:
            raise ValueError('Released commitment requires explicit source evidence')
        return self


class CreditAccountView(SourcedBankProjection):
    ref: ref_type('Account')
    borrower_id: TextId
    currency: TextId
    region_id: TextId
    permitted_project_region_ids: ValueState[list[TextId]]
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    as_of: TimePoint

    @model_validator(mode='after')
    def actual_balance(self):
        for state in (self.actual_cash, self.restricted_cash):
            nonnegative_money(state)
            if state.state == 'known' and state.value.currency != self.currency:
                raise ValueError('Account balance must use its original currency')
        if (self.actual_cash.state == self.restricted_cash.state == 'known'
                and Decimal(self.restricted_cash.value.value) > Decimal(self.actual_cash.value.value)):
            raise ValueError('Restricted account balance exceeds actual cash')
        return self


class CreditDebtView(SourcedBankProjection):
    ref: ref_type('Debt')
    borrower_id: TextId
    lender_id: TextId
    origin_scope: ScopeRef
    component_refs: Annotated[list[ref_type('DebtComponent')], Field(min_length=1)]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint

    @model_validator(mode='after')
    def original_components(self):
        unique_identities(self.component_refs)
        return self


class CreditDebtComponentView(SourcedBankProjection):
    ref: ref_type('DebtComponent')
    debt_ref: ref_type('Debt')
    borrower_id: TextId
    payee_id: TextId
    origin_scope: ScopeRef
    account_ref: ref_type('Account')
    kind: Literal['principal', 'interest', 'fee', 'other']
    actual_due: ValueState[Money]
    actual_paid: ValueState[Money]
    due_at: TimePoint
    as_of: TimePoint

    @model_validator(mode='after')
    def actual_remaining(self):
        check_due_paid(self.actual_due, self.actual_paid)
        return self


def check_due_paid(due, paid):
    nonnegative_money(due)
    nonnegative_money(paid)
    if due.state == paid.state == 'known':
        if due.value.currency != paid.value.currency or Decimal(paid.value.value) > Decimal(due.value.value):
            raise ValueError('Paid amount cannot exceed due amount or change currency')


class CreditObligationView(SourcedBankProjection):
    ref: ref_type('Obligation')
    borrower_id: TextId
    payee_id: TextId
    origin_scope: ScopeRef
    account_ref: ref_type('Account')
    debt_component_ref: ref_type('DebtComponent') | None
    actual_due: ValueState[Money]
    actual_paid: ValueState[Money]
    due_at: TimePoint
    as_of: TimePoint

    @model_validator(mode='after')
    def actual_remaining(self):
        check_due_paid(self.actual_due, self.actual_paid)
        return self


class CreditForecastFlow(StrictRecord):
    local_key: TextId
    account_ref: ref_type('Account')
    time: TimePoint
    direction: Literal['inflow', 'outflow']
    amount: ValueState[CreditMoneyInterval]
    assumption_ref: ref_type('Assumption')


class CreditFinancialForecastView(SourcedBankProjection):
    ref: ref_type('FinancialForecast')
    application_ref: ref_type('FinanceApplication')
    borrower_id: TextId
    scope_ref: ScopeRef
    portfolio_ref: ref_type('BorrowerPortfolio')
    review_forecast_refs: Annotated[list[ref_type('FinancialForecast')], Field(min_length=1)]
    loan_account_ref: ref_type('Account')
    flows: list[CreditForecastFlow]
    ordinary_flows_exclude_debt_and_new_financing: Literal[True]
    risk_observation_refs: list[ref_type('RiskObservation')]
    coverage: Literal['complete', 'partial', 'unknown']
    horizon: TimeWindow
    as_of: TimePoint

    @model_validator(mode='after')
    def one_disclosed_forecast(self):
        unique_identities(self.risk_observation_refs)
        unique_identities(self.review_forecast_refs)
        if self.ref not in self.review_forecast_refs:
            raise ValueError('Forecast must retain its own exact version in the declared review set')
        keys = [row.local_key for row in self.flows]
        if len(set(keys)) != len(keys):
            raise ValueError('Forecast repeats a local cash-flow identity')
        if any(not self.horizon.contains(row.time) for row in self.flows):
            raise ValueError('Forecast cash flows must remain inside the declared horizon')
        return self


class CreditVerification(StrictRecord):
    authority_ref: ref_type('Authorization')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    organization_id: TextId
    action_id: TextId
    verified_at: TimePoint


class CreditConditionView(SourcedBankProjection):
    ref: ref_type('Requirement')
    product_ref: ref_type('FinanceProductProfile')
    application_ref: ref_type('FinanceApplication')
    scope_ref: ScopeRef
    responsible_id: TextId
    authorized_verifier_organization_ids: ValueState[list[TextId]]
    authorized_verifier_action_ids: ValueState[list[TextId]]
    dependency_refs: list[ref_type('Requirement')]
    outcome: ValueState[Literal['satisfied', 'unsatisfied']]
    verification: CreditVerification | None
    effective_window: TimeWindow

    @model_validator(mode='after')
    def preserve_dependencies(self):
        unique_identities(self.dependency_refs)
        if self.outcome.state == 'known' and self.outcome.value == 'satisfied' and self.verification is None:
            raise ValueError('Satisfied credit condition requires an explicit authorized verification')
        return self


class CreditCaseView(SourcedBankProjection):
    ref: ref_type('OwnerCase')
    borrower_id: TextId
    available_at: TimePoint
    status: Literal['active', 'closed']


class CreditProjectView(SourcedBankProjection):
    ref: ref_type('Project')
    borrower_id: TextId
    region_id: TextId
    available_at: TimePoint
    status: Literal['active', 'suspended', 'closed']


class CreditWorkView(SourcedBankProjection):
    ref: ref_type('WorkScope')
    scope_ref: ScopeRef
    borrower_id: TextId
    effective_window: TimeWindow


def bank_credit_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ('FinanceApplication', FinanceApplicationView), ('Organization', BorrowerOrganizationView),
        ('FundingPurpose', FundingPurposeView), ('FinanceProductProfile', FinanceProductProfileView),
        ('RiskMethod', CreditRiskMethodView), ('FinanceFeasibilityMethod', CreditFeasibilityMethodView),
        ('RiskDimension', CreditRiskDimensionView), ('RiskObservation', CreditRiskObservationView),
        ('BorrowerPortfolio', CreditPortfolioView), ('Account', CreditAccountView),
        ('FinancePortfolio', CreditBankPortfolioView), ('LendingCapacity', CreditLendingCapacityView),
        ('FinanceCommitment', CreditCommitmentView),
        ('Debt', CreditDebtView), ('DebtComponent', CreditDebtComponentView),
        ('Obligation', CreditObligationView), ('FinancialForecast', CreditFinancialForecastView),
        ('Requirement', CreditConditionView), ('Assumption', CreditAssumptionView), ('Rule', CreditRuleView),
        ('OwnerCase', CreditCaseView), ('Project', CreditProjectView), ('WorkScope', CreditWorkView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
