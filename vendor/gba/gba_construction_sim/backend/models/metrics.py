from typing import Dict

from pydantic import BaseModel, Field


class SimulationMetrics(BaseModel):
    project_metrics: Dict = Field(default_factory=dict)
    agent_metrics: Dict = Field(default_factory=dict)
    network_metrics: Dict = Field(default_factory=dict)
    policy_metrics: Dict = Field(default_factory=dict)
