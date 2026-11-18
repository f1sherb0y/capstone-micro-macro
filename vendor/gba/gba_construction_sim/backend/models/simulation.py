from typing import Dict, List, Optional

from pydantic import BaseModel, Field, root_validator

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.procurement import ProcurementExecution


class SimulationCreateRequest(BaseModel):
    procurement_execution: ProcurementExecution = Field(default_factory=ProcurementExecution)

    @root_validator(pre=True)
    def resolve_procurement_execution(cls, values):
        # An explicit run object replaces the saved object in its entirety.
        values = dict(values)
        configuration = (values.get("workflow_configuration") or {}).get("configuration") or {}
        if "shared_input" in values or "shared_input" in configuration:
            raise ValueError("shared_input dataset references are not implemented; pass explicit agents and initial_projects")
        if "procurement_execution" not in values and "procurement_execution" in configuration:
            values["procurement_execution"] = configuration["procurement_execution"]
        return values

    name: str = "GBA baseline simulation"
    ticks: int = 60
    random_seed: Optional[int] = 42
    policy: Dict = Field(default_factory=dict)
    macro_environment: Dict = Field(default_factory=dict)
    agents: List[EnterpriseAgentProfile] = Field(default_factory=list)
    initial_projects: List[ConstructionProject] = Field(default_factory=list)
    enable_project_generation: bool = False
    agent_source: str = "default"
    agent_count: Optional[int] = None
    agent_roles: List[str] = Field(default_factory=list)
    agent_regions: List[str] = Field(default_factory=list)
    agent_source_types: List[str] = Field(default_factory=list)
    max_tender_invites: int = 40
    use_prior_network_edges: bool = True
    store_full_agent_snapshots: bool = False
    target_project_count: Optional[int] = None
    max_active_projects: Optional[int] = None
    workflow_configuration: Dict = Field(default_factory=dict)

    @root_validator(skip_on_failure=True)
    def validate_explicit_inputs(cls, values):
        if values.get("agent_source", "").lower() != "explicit":
            return values
        agents = values.get("agents") or []
        projects = values.get("initial_projects") or []
        if not agents or not projects:
            raise ValueError("agent_source=explicit requires agents and initial_projects")
        if values.get("enable_project_generation") or values.get("use_prior_network_edges"):
            raise ValueError("Explicit input requires project generation and prior network edges to be disabled")
        agent_ids = [agent.agent_id for agent in agents]
        project_ids = [project.project_id for project in projects]
        if len(set(agent_ids)) != len(agent_ids) or len(set(project_ids)) != len(project_ids):
            raise ValueError("Explicit input contains duplicate enterprise or project IDs")
        if any(project.owner_id not in agent_ids for project in projects):
            raise ValueError("Every explicit project's owner_id must exist in agents")
        return values


class SimulationRunResponse(BaseModel):
    simulation_id: str
    status: str
    current_tick: int
    project_results: List[Dict] = Field(default_factory=list)
    agent_results: List[Dict] = Field(default_factory=list)
    network_results: Dict = Field(default_factory=dict)
    metrics: Dict = Field(default_factory=dict)


class SimulationSummary(BaseModel):
    procurement: Dict = Field(default_factory=dict)
    simulation_id: str
    name: str
    current_tick: int
    ticks: int
    project_count: int
    agent_count: int
    status: str
