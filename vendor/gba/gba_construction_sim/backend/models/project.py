from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.models.engagement import ProjectEngagement
from gba_construction_sim.backend.models.project_performance import ProjectPerformanceState


class ConstructionProject(BaseModel):
    project_id: str
    name: str
    project_type: str = "building"
    region: str
    owner_id: str

    current_stage: ProjectStage = ProjectStage.INITIATION

    technical_complexity: float = 0.5
    initial_budget: float
    estimated_cost: Optional[float] = None
    contract_sum: Optional[float] = None

    selected_architect_id: Optional[str] = None
    selected_engineer_id: Optional[str] = None
    selected_qs_id: Optional[str] = None
    selected_contractor_id: Optional[str] = None
    selected_supplier_ids: List[str] = Field(default_factory=list)
    selected_bank_id: Optional[str] = None

    performance: ProjectPerformanceState = Field(default_factory=ProjectPerformanceState)
    engagements: List[ProjectEngagement] = Field(default_factory=list)
    bids: List[Dict] = Field(default_factory=list)
    contracts: List[Dict] = Field(default_factory=list)
    event_log: List[Dict] = Field(default_factory=list)

    stage_tick: int = 0
    flags: Dict[str, Any] = Field(default_factory=dict)
