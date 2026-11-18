from typing import Dict, Optional

from pydantic import BaseModel, Field

from gba_construction_sim.backend.core.enums import ProjectStage


class SimulationEvent(BaseModel):
    event_id: str
    tick: int
    project_id: Optional[str] = None
    agent_id: Optional[str] = None
    event_type: str
    stage: Optional[ProjectStage] = None
    description: str
    data: Dict = Field(default_factory=dict)
