from pydantic import BaseModel


class ProjectPerformanceState(BaseModel):
    planned_progress: float = 0.0
    actual_progress: float = 0.0
    progress_deviation: float = 0.0

    design_quality: float = 0.0
    material_quality: float = 1.0
    construction_quality: float = 1.0
    overall_quality: float = 1.0
    defect_rate: float = 0.0
    detected_defect_rate: float = 0.0

    planned_cost: float = 0.0
    actual_cost: float = 0.0
    cost_overrun_ratio: float = 0.0

    planned_duration: int = 0
    elapsed_time: int = 0
    delay_days: int = 0

    safety_risk: float = 0.0
    compliance_risk: float = 0.0
    inspection_pass_probability: float = 1.0

    coordination_efficiency: float = 1.0
    information_quality: float = 1.0
    decision_delay_risk: float = 0.0

    material_availability: float = 1.0
    supply_delay_risk: float = 0.0

    variation_risk: float = 0.0
    claim_risk: float = 0.0
    dispute_risk: float = 0.0

    project_failure_risk: float = 0.0
