"""Disclosed, versioned BANK-A13 consultation projections."""
from typing import Literal

from pydantic import model_validator

from src.actions.contracts.bank_credit_objects import (
    CreditLoanFactor, CreditMoneyInterval, CreditMeasuredInterval,
    CreditRiskDimensionView, unique_identities, nonnegative_money,
)
from src.actions.contracts.bank_objects import SourcedBankProjection
from src.actions.contracts.common import Money, Reference, ScopeRef, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas


class AdviceBriefView(SourcedBankProjection):
    ref: ref_type('OwnerBrief')
    owner_id: TextId
    case_ref: ref_type('OwnerCase')
    scope_ref: ScopeRef
    borrower: ValueState[TextId]
    option_refs: list[ref_type('ProjectOption')]
    demand_refs: list[ref_type('DemandEvidence')]
    cashflow_refs: list[ref_type('FinancialForecast')]
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def distinct_inputs(self):
        for refs in (self.option_refs, self.demand_refs, self.cashflow_refs):
            unique_identities(refs)
        return self


class AdviceIdentityView(SourcedBankProjection):
    ref: Reference


class AdviceSubjectView(SourcedBankProjection):
    ref: Reference
    owner_id: TextId
    brief_ref: ref_type('OwnerBrief')
    scope_ref: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow


class AdviceFlow(SourcedBankProjection):
    local_key: TextId
    time: TimePoint
    direction: Literal['inflow', 'outflow']
    amount: CreditMoneyInterval


class AdviceForecastView(AdviceSubjectView):
    ref: ref_type('FinancialForecast')
    subject_ref: Reference
    scenario_account_ref: ref_type('Account')
    opening_cash: ValueState[Money]
    flows: list[AdviceFlow]
    funding_plan: ValueState[ref_type('FundingPlan')]
    horizon: TimeWindow
    coverage: Literal['complete', 'partial', 'unknown']
    excludes_hypothetical_financing: Literal[True]
    assumption_refs: list[ref_type('Assumption')]

    @model_validator(mode='after')
    def hypothetical_calendar(self):
        nonnegative_money(self.opening_cash)
        unique_identities(self.assumption_refs)
        if len({row.local_key for row in self.flows}) != len(self.flows):
            raise ValueError('Advisory forecast repeats a cash event')
        return self


class AdviceMethodView(SourcedBankProjection):
    ref: ref_type('FinanceFeasibilityMethod')
    lender_id: TextId
    host_method_ref: ref_type('Method')
    risk_method_ref: ref_type('RiskMethod')
    currency: TextId
    minimum: Money
    maximum: Money
    requested: Money
    minor_places: int
    loan_schedule: list[CreditLoanFactor]
    assumption_refs: list[ref_type('Assumption')]
    infeasible_rule_ref: ref_type('Rule')
    effective_window: TimeWindow

    @model_validator(mode='after')
    def explicit_financing_assumptions(self):
        unique_identities(self.assumption_refs)
        if {row.assumption_ref.key() for row in self.loan_schedule} != {ref.key() for ref in self.assumption_refs}:
            raise ValueError('Advisory financing schedule must retain all original assumptions')
        return self


class AdviceRiskMethodView(SourcedBankProjection):
    ref: ref_type('RiskMethod')
    lender_id: TextId
    host_method_ref: ref_type('Method')
    dimension_refs: list[ref_type('RiskDimension')]
    observation_refs: list[ref_type('RiskObservation')]
    effective_window: TimeWindow


class AdviceRiskObservationView(SourcedBankProjection):
    ref: ref_type('RiskObservation')
    subject_ref: Reference
    dimension_ref: ref_type('RiskDimension')
    interval: ValueState[CreditMeasuredInterval]
    available_at: TimePoint
    effective_window: TimeWindow


class AdviceAuthorizationView(SourcedBankProjection):
    ref: ref_type('AdvisoryAuthorization')
    lender_id: TextId
    owner_id: TextId
    brief_ref: ref_type('OwnerBrief')
    scope_ref: ScopeRef
    subject_ref: Reference
    authority_ref: ref_type('Authorization')
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    decision: ValueState[Literal['advise', 'decline']]
    permitted_use_ref: ref_type('PermittedUse')
    condition_refs: list[ref_type('Requirement')]
    unresolved_refs: list[ref_type('Issue')]
    effective_window: TimeWindow


class AdviceUseView(SourcedBankProjection):
    ref: ref_type('PermittedUse')
    brief_ref: ref_type('OwnerBrief')
    subject_ref: Reference
    scope_ref: ScopeRef
    use: Literal['option_comparison_only']
    reserves_capacity: Literal[False]
    creates_funds: Literal[False]
    effective_window: TimeWindow


class AdviceConditionView(SourcedBankProjection):
    ref: ref_type('Requirement')
    brief_ref: ref_type('OwnerBrief')
    scope_ref: ScopeRef
    responsible_id: TextId
    dependency_refs: list[ref_type('Requirement')]
    outcome: ValueState[Literal['satisfied', 'unsatisfied']]
    verifier_authority_ref: ref_type('Authorization') | None
    verifier_actor_id: TextId | None
    verifier_function_ref: ref_type('FunctionAssignment') | None
    verifier_action_id: TextId | None
    verified_at: TimePoint | None
    issue_ref: ref_type('Issue')
    effective_window: TimeWindow


class AdviceIssueView(AdviceSubjectView):
    ref: ref_type('Issue')
    subject_ref: Reference
    status: Literal['open', 'closed']


class AdviceAssumptionView(SourcedBankProjection):
    ref: ref_type('Assumption')
    brief_ref: ref_type('OwnerBrief')
    description: TextId
    effective_window: TimeWindow


class AdviceRuleView(SourcedBankProjection):
    ref: ref_type('Rule')
    lender_id: TextId
    scope_ref: ScopeRef
    description: TextId
    effective_window: TimeWindow


def bank_advice_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ('Organization', AdviceIdentityView), ('OwnerCase', AdviceIdentityView), ('Account', AdviceIdentityView),
        ('OwnerBrief', AdviceBriefView), ('ProjectOption', AdviceSubjectView),
        ('DemandEvidence', AdviceSubjectView), ('FundingPlan', AdviceSubjectView),
        ('FinancialForecast', AdviceForecastView), ('FinanceFeasibilityMethod', AdviceMethodView),
        ('RiskMethod', AdviceRiskMethodView), ('RiskDimension', CreditRiskDimensionView),
        ('RiskObservation', AdviceRiskObservationView), ('AdvisoryAuthorization', AdviceAuthorizationView),
        ('PermittedUse', AdviceUseView), ('Requirement', AdviceConditionView),
        ('Issue', AdviceIssueView), ('Assumption', AdviceAssumptionView), ('Rule', AdviceRuleView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
