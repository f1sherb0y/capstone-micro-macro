"""Private index sensitivity review, distinct from forecast-error calibration."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type


class MonthlyEstimationPolicy(StrictRecord):
    ref: ref_type('MonthlyEstimationPolicy')
    organization_id: TextId
    scope: ScopeRef
    authority_ref: ref_type('Authorization')
    effective_window: TimeWindow
    baseline_material_index: Measured
    minimum_relative_change: Measured
    minimum_free_ratio: Measured
    maximum_updates: int = Field(ge=1)
    authorized_project_ids: list[TextId] = Field(min_length=1)
    purpose: Literal['private_future_index_sensitivity_only']
    evidence_refs: list[ref_type('Evidence')]


class MonthlyEstimationObservation(StrictRecord):
    ref: ref_type('MonthlyEstimationObservation')
    organization_id: TextId
    scope: ScopeRef
    as_of: TimePoint
    material_index: Measured
    native_free_ratio: Measured
    own_project_evidence: list[dict]
    prior_own_outcomes: list[dict]
    evidence_refs: list[ref_type('Evidence')]


class MonthlyEstimationJudgment(StrictRecord):
    schema_version: Literal['qs-monthly-estimation-judgment.v1'] = 'qs-monthly-estimation-judgment.v1'
    operation: Literal['improve_cost_estimation'] = 'improve_cost_estimation'
    participate: bool
    material_index: Measured
    native_free_ratio: Measured
    accepted_material_index: str
    relative_index_change: str
    proposed_material_factor: str
    applied_material_factor: str
    indicative_estimates: list[dict]
    prior_actual_update_count: int = Field(ge=0)
    consumed_event_ids: list[TextId]
    interpretation: TextId
