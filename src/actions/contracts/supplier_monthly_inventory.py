"""Aggregate inventory-planning review, without a physical stock assertion."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import StrictRecord, TextId, Measured, ScopeRef, TimePoint, TimeWindow, ref_type


class SupplierInventoryPolicy(StrictRecord):
    ref: ref_type('SupplierInventoryPolicy')
    organization_id: TextId
    scope: ScopeRef
    authority_ref: ref_type('Authorization')
    effective_window: TimeWindow
    minimum_material_index: Measured
    minimum_free_ratio: Measured
    minimum_material_availability: Measured
    maximum_supply_delay_risk: Measured
    maximum_prior_reviews: int = Field(ge=1)
    evidence_refs: list[ref_type('Evidence')]


class SupplierInventoryObservation(StrictRecord):
    ref: ref_type('SupplierInventoryObservation')
    organization_id: TextId
    scope: ScopeRef
    as_of: TimePoint
    material_index: Measured
    native_free_ratio: Measured
    prior_own_outcomes: list[dict]
    actual_supply_outcomes: list[dict]
    evidence_refs: list[ref_type('Evidence')]


class SupplierInventoryJudgment(StrictRecord):
    schema_version: Literal['supplier-inventory-planning-judgment.v1'] = 'supplier-inventory-planning-judgment.v1'
    operation: Literal['adjust_inventory'] = 'adjust_inventory'
    participate: bool
    material_index: Measured
    material_index_gap: str
    native_free_ratio: Measured
    price_triggered: bool
    supply_risk_triggered: bool
    prior_actual_review_count: int = Field(ge=0)
    consumed_event_ids: list[TextId]
    consumed_micro_result_sha256: list[TextId]
    consumed_supply_record_sha256: list[TextId]
    current_backup_request: dict
    interpretation: TextId
