from typing import Dict, List

from pydantic import BaseModel, Field


class EnterpriseAgentProfile(BaseModel):
    agent_id: str
    name: str
    role: str
    region: str
    enterprise_type: str

    qualification_level: float = 0.5
    financial_capacity: float = 0.5
    technical_capability: float = 0.5
    management_capability: float = 0.5

    risk_preference: float = 0.5
    collaboration_preference: float = 0.5
    cross_region_experience: float = 0.5
    policy_adaptability: float = 0.5

    design_capability: float = 0.5
    cost_estimation_capability: float = 0.5
    construction_capability: float = 0.5
    safety_management_capability: float = 0.5
    quality_management_capability: float = 0.5
    supervision_capability: float = 0.5
    supply_reliability: float = 0.5
    material_quality: float = 0.5
    payment_reliability: float = 0.5
    decision_speed: float = 0.5

    total_resource_capacity: float = 1.0
    occupied_resource: float = 0.0

    active_regions: List[str] = Field(default_factory=list)
    preferred_partners: List[str] = Field(default_factory=list)

    semantic_memory: Dict = Field(default_factory=dict)
    episodic_memory: List[Dict] = Field(default_factory=list)

    def available_resource(self) -> float:
        return max(0.0, self.total_resource_capacity - self.occupied_resource)

    def has_available_resource(self, required: float = 0.1) -> bool:
        return self.available_resource() >= required
