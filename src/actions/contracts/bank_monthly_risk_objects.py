"""Monthly monitoring of received financing-case risk estimates, never loan facts."""
from typing import Literal

from pydantic import Field

from src.actions.contracts.common import Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type


class MonthlyBorrowerRiskPolicy(StrictRecord):
    ref: ref_type('MonthlyBorrowerRiskPolicy')
    organization_id: TextId
    scope: ScopeRef
    authority_ref: ref_type('Authorization')
    effective_window: TimeWindow
    market_stress_weight: Measured
    borrower_weakness_weight: Measured
    monitoring_threshold: Measured
    maximum_prior_monitoring: int = Field(ge=1)
    evidence_refs: list[ref_type('Evidence')]


class MonthlyBorrowerRiskObservation(StrictRecord):
    ref: ref_type('MonthlyBorrowerRiskObservation')
    organization_id: TextId
    scope: ScopeRef
    as_of: TimePoint
    financing_condition: Measured
    received_cases: list[dict]
    prior_own_operations: list[dict]
    evidence_refs: list[ref_type('Evidence')]


class MonthlyBorrowerRiskJudgment(StrictRecord):
    schema_version: Literal['monthly-borrower-risk-judgment.v1'] = 'monthly-borrower-risk-judgment.v1'
    operation: Literal['review_credit_pipeline', 'adjust_credit_terms', 'monitor_borrower_risk']
    original_strategy_choice: Literal['retain_strategy', 'revise_strategy']
    original_strategy_note: TextId
    financing_condition: Measured
    market_stress: str
    case_scores: list[dict]
    maximum_risk_score: str | None
    prior_actual_monitoring_count: int = Field(ge=0)
    monitoring_threshold: Measured
    monitored_case_count: int = Field(ge=0)
    interpretation: TextId
