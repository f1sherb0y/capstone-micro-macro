"""Native global demand analysis; private case/finance histories stay unknown."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import Measured,ScopeRef,StrictRecord,TextId,TimePoint,ref_type


class MonthlyOwnerDemandObservation(StrictRecord):
    ref:ref_type('MonthlyOwnerDemandObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    current_market_index:Measured
    native_available_resource:Measured
    prior_own_outcomes:list[dict]
    private_case_and_finance_history_coverage:Literal['unknown']='unknown'
    evidence_refs:list[ref_type('Evidence')]


class MonthlyOwnerDemandJudgment(StrictRecord):
    schema_version:Literal['owner-monthly-demand-judgment.v1']='owner-monthly-demand-judgment.v1'
    operation:Literal['evaluate_market_demand']='evaluate_market_demand'
    original_choice:Literal['propose','ignore']
    current_market_index:Measured
    declared_screening_threshold:Measured
    meets_screening_threshold:bool
    prior_actual_analysis_count:int=Field(ge=0)
    previous_actual_index:str|None
    change_from_previous_actual_analysis:str|None
    trend:Literal['initial','rising','falling','flat']
    consumed_event_ids:list[TextId]
    consumed_analysis_sha256:list[TextId]
    interpretation:TextId
