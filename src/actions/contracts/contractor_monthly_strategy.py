"""Bounded future private bid policy; not firm finances or a submitted tender."""
from typing import Literal
from src.actions.contracts.common import Measured,ScopeRef,StrictRecord,TextId,TimePoint,TimeWindow,ref_type


class MonthlyBidStrategyPolicy(StrictRecord):
    ref:ref_type('MonthlyBidStrategyPolicy')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    effective_window:TimeWindow
    material_index_threshold:Measured
    base_markup:str
    risk_markup_increment:str
    evidence_refs:list[ref_type('Evidence')]


class MonthlyBidStrategyObservation(StrictRecord):
    ref:ref_type('MonthlyBidStrategyObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    material_index:Measured
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]


class MonthlyBidStrategyJudgment(StrictRecord):
    schema_version:Literal['contractor-monthly-bid-strategy.v1']='contractor-monthly-bid-strategy.v1'
    operation:Literal['adjust_bid_strategy']='adjust_bid_strategy'
    material_index:Measured
    threshold:Measured
    high_material_risk:bool
    next_private_markup:str
    consumed_event_ids:list[TextId]
    consumed_result_sha256:list[TextId]
    interpretation:TextId
