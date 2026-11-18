from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from gba_construction_sim.backend.core.enums import ProjectStage


class StageRule(BaseModel):
    stage: ProjectStage
    required_roles: List[str]
    allowed_actions: Dict[str, List[str]]
    entry_conditions: List[str] = Field(default_factory=list)
    exit_conditions: List[str] = Field(default_factory=list)
    failure_conditions: List[str] = Field(default_factory=list)
    next_stage: Optional[ProjectStage] = None
    rollback_stage: Optional[ProjectStage] = None
    release_roles_on_exit: List[str] = Field(default_factory=list)
    standby_roles_on_exit: List[str] = Field(default_factory=list)
