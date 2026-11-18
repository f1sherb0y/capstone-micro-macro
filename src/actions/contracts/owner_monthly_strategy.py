"""Finite authorized investment preferences, selected in micro and adopted after native execution."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import Measured,ScopeRef,StrictRecord,TextId,TimePoint,TimeWindow,ref_type


class MonthlyInvestmentPolicy(StrictRecord):
    ref:ref_type('MonthlyInvestmentPolicy')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    effective_window:TimeWindow
    financing_watch_threshold:Measured
    normal_preference_ref:ref_type('OwnerPreferenceProfile')
    watch_preference_ref:ref_type('OwnerPreferenceProfile')
    minimum_weight_change:str
    maximum_updates:int=Field(ge=1)
    effect:Literal['future_private_investment_criteria_only']
    evidence_refs:list[ref_type('Evidence')]


class MonthlyInvestmentObservation(StrictRecord):
    ref:ref_type('MonthlyInvestmentObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    financing_index:Measured
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]


class MonthlyInvestmentJudgment(StrictRecord):
    schema_version:Literal['monthly-owner-investment-strategy-judgment.v1']='monthly-owner-investment-strategy-judgment.v1'
    original_choice:Literal['revise_preferences','retain_policy']
    participate:bool
    financing_index:Measured
    financing_watch:bool
    current_preference_ref:ref_type('OwnerPreferenceProfile')
    proposed_preference_ref:ref_type('OwnerPreferenceProfile')
    effective_preference_ref:ref_type('OwnerPreferenceProfile')
    proposed_scores:dict[str,str]
    effective_scores:dict[str,str]
    maximum_weight_change:str
    prior_actual_update_count:int=Field(ge=0)
    consumed_event_ids:list[TextId]
    interpretation:TextId
