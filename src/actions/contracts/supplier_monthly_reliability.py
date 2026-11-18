"""Nonbinding backup sourcing review; no physical inventory or logistics facts."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import StrictRecord,TextId,Measured,ScopeRef,TimePoint,TimeWindow,ref_type


class SupplyReliabilityPolicy(StrictRecord):
    ref:ref_type('SupplyReliabilityPolicy')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    effective_window:TimeWindow
    target_native_reliability:Measured
    minimum_shortfall:Measured
    minimum_free_ratio:Measured
    maximum_prior_reviews:int=Field(ge=1)
    purpose:Literal['private_own_risk_backup_sourcing_review']
    evidence_refs:list[ref_type('Evidence')]


class SupplyReliabilityObservation(StrictRecord):
    ref:ref_type('SupplyReliabilityObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    native_reliability:Measured
    native_free_ratio:Measured
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]


class SupplyReliabilityJudgment(StrictRecord):
    schema_version:Literal['supplier-monthly-reliability-judgment.v1']='supplier-monthly-reliability-judgment.v1'
    operation:Literal['improve_supply_reliability']='improve_supply_reliability'
    participate:bool
    native_reliability:Measured
    native_free_ratio:Measured
    target_native_reliability:Measured
    reliability_shortfall:str
    prior_actual_review_count:int=Field(ge=0)
    consumed_event_ids:list[TextId]
    consumed_micro_result_sha256:list[TextId]
    prior_backup_requests:list[dict]
    current_backup_request:dict
    interpretation:TextId
