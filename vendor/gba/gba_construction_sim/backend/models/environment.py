from typing import Dict

from pydantic import BaseModel, Field


class MacroEnvironment(BaseModel):
    current_tick: int = 0

    market_demand_index: float = 1.0
    material_price_index: float = 1.0
    labor_price_index: float = 1.0
    financing_condition_index: float = 1.0
    regulatory_pressure_index: float = 0.5
    policy_stability_index: float = 0.5

    regional_friction_matrix: Dict[str, Dict[str, float]] = Field(default_factory=dict)
