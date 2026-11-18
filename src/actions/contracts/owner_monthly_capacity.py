"""Monthly review of an independently declared complete private cash portfolio."""
from typing import Literal
from src.actions.contracts.common import Measured,ScopeRef,StrictRecord,TextId,TimePoint,ref_type


class MonthlyOwnerCapacityObservation(StrictRecord):
    ref:ref_type('MonthlyOwnerCapacityObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    actual_financing_index:Measured
    independent_watch_threshold:Measured
    private_portfolio_coverage:Literal['complete_declared_synthetic_initial_portfolio']
    prior_own_reviews:list[dict]
    evidence_refs:list[ref_type('Evidence')]


class MonthlyOwnerCapacityJudgment(StrictRecord):
    schema_version:Literal['owner-monthly-capacity-judgment.v1']='owner-monthly-capacity-judgment.v1'
    operation:Literal['review_financing_capacity']='review_financing_capacity'
    original_choice:Literal['own_funds','no_finance']
    cash_feasible:bool
    currency:TextId
    minimum_available:str
    actual_financing_index:Measured
    independent_watch_threshold:Measured
    environment_watch:bool
    financing_watch:bool
    prior_review_count:int
    previous_minimum_available:str|None
    change_in_minimum_available:str|None
    previous_environment_index:str|None
    change_in_environment_index:str|None
    monitoring_transition:Literal['initial_clear','initial_watch','clear_continues','watch_continues','watch_started','watch_resolved']
    consumed_event_ids:list[TextId]
    consumed_review_sha256:list[TextId]
    interpretation:TextId
