"""Background method-improvement decisions; no credential or training completion facts."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type


class AggregateDesignPolicy(StrictRecord):
    minimum_design_quality: float = Field(ge=0, le=1)
    minimum_information_quality: float = Field(ge=0, le=1)
    maximum_estimate_budget_ratio: float = Field(gt=0)


class AggregateConstructionPolicy(StrictRecord):
    maximum_delay_days: float = Field(ge=0)
    maximum_progress_shortfall: float = Field(ge=0, le=1)
    maximum_safety_risk: float | None = Field(default=None, ge=0, le=1, exclude_if=lambda v: v is None)


class AggregateConstructionResult(StrictRecord):
    run_id: TextId
    project_id: TextId
    event: dict
    event_sha256: TextId
    initial_assignment: dict
    initial_assignment_sha256: TextId


class AggregateDesignResult(StrictRecord):
    project_id: TextId
    tick: int = Field(ge=1)
    event: dict
    event_sha256: TextId
    appointment_event: dict
    appointment_event_sha256: TextId
    appointment_identity: dict
    appointment_result_sha256: TextId
    coordination_transition: dict
    coordination_transition_sha256: TextId
    design_quality: float = Field(ge=0, le=1)
    information_quality: float = Field(ge=0, le=1)
    estimated_cost: float = Field(ge=0)
    initial_budget: float = Field(gt=0)


class MonthlyMethodPolicy(StrictRecord):
    ref: ref_type('MonthlyMethodPolicy')
    organization_id: TextId
    role: Literal['Architect','Engineer']
    scope: ScopeRef
    authority_ref: ref_type('Authorization')
    effective_window: TimeWindow
    baseline_requirement: Measured
    regulatory_pressure_weight: Measured
    minimum_shortfall: Measured
    minimum_free_ratio: Measured
    maximum_prior_improvements: int = Field(ge=1)
    method_focus: TextId
    evidence_refs: list[ref_type('Evidence')]
    design_review: AggregateDesignPolicy | None = None
    qualification_maintenance_pressure: Measured | None = None
    construction_review: AggregateConstructionPolicy | None = None


class MonthlyMethodObservation(StrictRecord):
    ref: ref_type('MonthlyMethodObservation')
    organization_id: TextId
    role: Literal['Architect','Engineer']
    scope: ScopeRef
    as_of: TimePoint
    regulatory_pressure: Measured
    native_capability: Measured
    native_free_ratio: Measured
    prior_own_outcomes: list[dict]
    evidence_refs: list[ref_type('Evidence')]
    design_results: list[AggregateDesignResult] | None = None
    construction_results: list[AggregateConstructionResult] | None = None


class MonthlyMethodJudgment(StrictRecord):
    schema_version: Literal['monthly-professional-method-judgment.v1'] = 'monthly-professional-method-judgment.v1'
    role: Literal['Architect','Engineer']
    operation: Literal['improve_design_capability','improve_engineering_capability','maintain_professional_qualifications']
    participate: bool
    regulatory_pressure: Measured
    native_capability: Measured
    native_free_ratio: Measured
    required_capability_index: str
    capability_shortfall: str
    prior_actual_improvement_count: int = Field(ge=0)
    consumed_event_ids: list[TextId]
    prior_method_focus: list[TextId]
    method_focus: TextId
    interpretation: TextId
    design_review: list[dict] | None = None
    qualification_maintenance: dict | None = None
    construction_review: list[dict] | None = None
