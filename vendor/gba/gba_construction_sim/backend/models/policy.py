from pydantic import BaseModel


class PolicyRegime(BaseModel):
    policy_id: str = "POLICY_BASELINE"
    name: str = "GBA baseline policy"

    entry_waiting_time: float = 30.0
    approval_success_prob: float = 0.7
    procedural_uncertainty: float = 0.3
    compliance_cost: float = 0.2
    scope_breadth: float = 0.8

    cross_region_qualification_recognition: float = 0.5
    tax_or_subsidy_intensity: float = 0.0
    regulatory_intensity: float = 0.5
    information_transparency: float = 0.5
