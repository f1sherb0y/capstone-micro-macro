"""Private simulation-index knowledge; never a price quote or actual project cost."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import Measured,ScopeRef,StrictRecord,TextId,TimePoint,TimeWindow,ref_type


class MonthlyCostPolicy(StrictRecord):
    ref:ref_type('MonthlyCostPolicy')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    effective_window:TimeWindow
    baseline_material_index:Measured
    pressure_threshold:Measured
    minimum_relative_change:Measured
    maximum_updates:int=Field(ge=1)
    evidence_refs:list[ref_type('Evidence')]


class MonthlyCostObservation(StrictRecord):
    ref:ref_type('MonthlyCostObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    material_index:Measured
    prior_own_outcomes:list[dict]
    registered_indices:list[dict]
    evidence_refs:list[ref_type('Evidence')]


class MonthlyCostJudgment(StrictRecord):
    schema_version:Literal['qs-monthly-cost-market-judgment.v1']='qs-monthly-cost-market-judgment.v1'
    operation:Literal['review_cost_market','update_cost_database']
    material_index:Measured
    baseline_material_index:Measured
    positive_cost_pressure:str
    pressure_priority:Literal['urgent','routine']
    relative_change_from_registered:str|None
    prior_actual_update_count:int=Field(ge=0)
    consumed_event_ids:list[TextId]
    consumed_registration_keys:list[TextId]
    source_ref:ref_type('PriceSource')
    interpretation:TextId
