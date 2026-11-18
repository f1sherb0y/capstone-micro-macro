"""A global index is a risk signal; private quoted money retains original A03 costs."""
from typing import Literal
from src.actions.contracts.common import Measured,ScopeRef,StrictRecord,TextId,TimePoint,TimeWindow,ref_type


class SupplierPriceMonitorPolicy(StrictRecord):
    ref:ref_type('SupplierPriceMonitorPolicy')
    organization_id:TextId
    scope:ScopeRef
    effective_window:TimeWindow
    authority_ref:ref_type('Authorization')
    base_markup_rate:str
    risk_surcharge_rate:str
    material_index_threshold:Measured
    evidence_refs:list[ref_type('Evidence')]


class SupplierPriceMonitorObservation(StrictRecord):
    ref:ref_type('SupplierPriceMonitorObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    material_index:Measured
    current_original_quote:dict
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]


class SupplierPriceMonitorJudgment(StrictRecord):
    schema_version:Literal['supplier-monthly-price-monitor.v1']='supplier-monthly-price-monitor.v1'
    operation:Literal['monitor_material_prices']='monitor_material_prices'
    material_index:Measured
    threshold:Measured
    price_risk_above_threshold:bool
    next_markup_rate:str
    current_original_quote:dict
    change_from_previous_quote:str|None
    consumed_event_ids:list[TextId]
    consumed_monitor_result_sha256:list[TextId]
    interpretation:TextId
