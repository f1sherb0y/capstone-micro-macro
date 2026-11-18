from typing import Optional

from pydantic import BaseModel

from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage


class ProjectEngagement(BaseModel):
    engagement_id: str
    project_id: str
    agent_id: str
    role: str

    status: EngagementStatus

    start_stage: ProjectStage
    expected_end_stage: Optional[ProjectStage] = None
    actual_end_stage: Optional[ProjectStage] = None

    joined_at_tick: int
    released_at_tick: Optional[int] = None

    resource_allocation: float = 1.0
    contractual_obligation: bool = True

    can_be_recalled: bool = False
    recall_reason: Optional[str] = None
