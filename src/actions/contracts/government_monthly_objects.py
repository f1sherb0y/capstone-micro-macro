"""Authorized background regulatory analysis, separate from legal publication."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import StrictRecord,TextId,ScopeRef,TimePoint,TimeWindow,Measured,ref_type

MonthlyOperation=Literal['adjust_regulatory_focus','monitor_compliance','publish_guidelines','review_policy_feedback']
OPERATIONS={'adjust_regulatory_focus','monitor_compliance','publish_guidelines','review_policy_feedback'}


class GovMonthlyPolicy(StrictRecord):
    ref: ref_type('MonthlyRegulatoryPolicy')
    organization_id: TextId
    scope: ScopeRef
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    effective_window: TimeWindow
    allowed_operations: list[MonthlyOperation]
    minimum_demand_for_focus: Measured
    maximum_focus_operations: int=Field(ge=1)
    maximum_guidance_operations: int=Field(ge=1)
    guidance_principles: list[TextId]=Field(min_length=1)
    evidence_refs: list[ref_type('Evidence')]=Field(min_length=1)


class GovMonthlyObservation(StrictRecord):
    ref: ref_type('MonthlyRegulatoryObservation')
    organization_id: TextId
    scope: ScopeRef
    as_of: TimePoint
    market_demand: Measured
    prior_own_operations: list[dict]
    prior_own_approval_outcomes: list[dict]
    evidence_refs: list[ref_type('Evidence')]=Field(min_length=1)


class GovMonthlyJudgment(StrictRecord):
    schema_version: Literal['government-monthly-judgment.v1']='government-monthly-judgment.v1'
    operation: MonthlyOperation
    market_demand: Measured
    threshold: Measured
    own_prior_operation_counts: dict[MonthlyOperation,int]
    prior_own_approval_count: int=Field(ge=0)
    prior_actual_rectification_count: int=Field(ge=0)
    interpretation: TextId
    guidance: str | None=None
    evidence_refs: list[ref_type('Evidence')]
