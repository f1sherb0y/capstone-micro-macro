"""Sourced new-business strategy inputs, never a second bank book."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.bank_credit_objects import (
    CreditBankPortfolioView, CreditCommitmentView, CreditLendingCapacityView,
    CreditMeasuredInterval, nonnegative_money, unique_identities,
)
from src.actions.contracts.bank_objects import SourcedBankProjection
from src.actions.contracts.common import Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas


class StrategyPortfolioView(CreditBankPortfolioView):
    obligation_refs: list[ref_type('Obligation')]

    @model_validator(mode='after')
    def original_obligations(self):
        unique_identities(self.obligation_refs)
        return self


class StrategyObligationView(SourcedBankProjection):
    ref: ref_type('Obligation')
    lender_id: TextId
    actual_due: ValueState[Money]
    actual_paid: ValueState[Money]
    due_at: TimePoint
    as_of: TimePoint

    @model_validator(mode='after')
    def actual_amounts(self):
        nonnegative_money(self.actual_due);nonnegative_money(self.actual_paid)
        if self.actual_due.state==self.actual_paid.state=='known':
            from src.methods.pricing import decimal_fraction
            if (self.actual_due.value.currency!=self.actual_paid.value.currency
                    or decimal_fraction(self.actual_paid.value.value)>decimal_fraction(self.actual_due.value.value)):
                raise ValueError('Original bank obligation has inconsistent paid amount or currency')
        return self


class StrategyObservationView(SourcedBankProjection):
    ref: ref_type('Observation')
    recipient_lender_id: TextId
    scope_ref: ScopeRef
    interval: ValueState[CreditMeasuredInterval]
    observed_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow


class StrategyMarketView(SourcedBankProjection):
    ref: ref_type('MarketObservation')
    recipient_lender_id: TextId
    observation_ref: ref_type('Observation')
    effective_window: TimeWindow


class StrategyPolicyView(SourcedBankProjection):
    ref: ref_type('PolicyObservation')
    lender_id: TextId
    observation_ref: ref_type('Observation')
    allowed_strategy_refs: ValueState[list[ref_type('LendingStrategyProfile')]]
    applies_to: Literal['new_business']
    modifies_existing_terms: Literal[False]
    effective_window: TimeWindow


class StrategySignalTest(StrictRecord):
    observation_ref: ref_type('Observation')
    predicate: Literal['at_most', 'at_least']
    threshold: Measured


class LendingStrategyView(SourcedBankProjection):
    ref: ref_type('LendingStrategyProfile')
    lender_id: TextId
    scope_ref: ScopeRef
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    originating_action_id: Literal['BANK-A01', 'BANK-A12']
    maximum_new_commitment: ValueState[Money]
    maximum_due_obligations: ValueState[Money]
    obligation_horizon: TimeWindow
    signal_tests: list[StrategySignalTest]
    selection_priority: ValueState[int]
    modifies_existing_terms: Literal[False]
    effective_window: TimeWindow

    @model_validator(mode='after')
    def explicit_strategy(self):
        nonnegative_money(self.maximum_new_commitment);nonnegative_money(self.maximum_due_obligations)
        unique_identities([test.observation_ref for test in self.signal_tests])
        return self


class StrategySpaceView(SourcedBankProjection):
    monthly_risk_policy_ref: ref_type('MonthlyBorrowerRiskPolicy') | None = None
    monthly_risk_observation_ref: ref_type('MonthlyBorrowerRiskObservation') | None = None
    ref: ref_type('LendingStrategySpace')
    lender_id: TextId
    scope_ref: ScopeRef
    current_strategy_ref: ValueState[ref_type('LendingStrategyProfile')]
    candidate_refs: ValueState[list[ref_type('LendingStrategyProfile')]]
    market_refs: list[ref_type('MarketObservation')]
    policy_refs: list[ref_type('PolicyObservation')]
    investigation_issue_refs: Annotated[list[ref_type('Issue')], Field(min_length=1)]
    selection_rule: Literal['retain_if_eligible_else_lowest_priority']
    effective_window: TimeWindow

    @model_validator(mode='after')
    def complete_source_sets(self):
        for refs in (self.market_refs,self.policy_refs,self.investigation_issue_refs):unique_identities(refs)
        if self.candidate_refs.state=='known':unique_identities(self.candidate_refs.value)
        return self


class StrategyIssueView(SourcedBankProjection):
    ref: ref_type('Issue')
    lender_id: TextId
    scope_ref: ScopeRef
    subject_refs: Annotated[list[Reference], Field(min_length=1)]
    status: Literal['open', 'closed']
    effective_window: TimeWindow


class StrategyOrganizationView(SourcedBankProjection):
    ref: ref_type('Organization')


def bank_strategy_schemas():
    from src.actions.contracts.bank_monthly_risk_objects import MonthlyBorrowerRiskPolicy, MonthlyBorrowerRiskObservation
    registry=common_projection_schemas()
    for kind,schema in (
        ('FinancePortfolio',StrategyPortfolioView),('LendingCapacity',CreditLendingCapacityView),
        ('FinanceCommitment',CreditCommitmentView),('Obligation',StrategyObligationView),
        ('Observation',StrategyObservationView),('MarketObservation',StrategyMarketView),
        ('PolicyObservation',StrategyPolicyView),('LendingStrategyProfile',LendingStrategyView),
        ('LendingStrategySpace',StrategySpaceView),('Issue',StrategyIssueView),
        ('Organization',StrategyOrganizationView),
        ('MonthlyBorrowerRiskPolicy',MonthlyBorrowerRiskPolicy),('MonthlyBorrowerRiskObservation',MonthlyBorrowerRiskObservation),
    ):registry.register_kind(kind,schema,str)
    return registry
