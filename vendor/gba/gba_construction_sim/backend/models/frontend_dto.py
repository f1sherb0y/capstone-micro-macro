from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AgentActivityDTO(BaseModel):
    activity_id: str
    date: str
    title: str
    type: str
    description: Optional[str] = None


class AgentListItemDTO(BaseModel):
    agent_id: str
    name: str
    role: str
    region: str
    status: str = "active"
    ai_generated: bool = False
    rating: float = 0.0
    project_count: int = 0
    tags: List[str] = Field(default_factory=list)
    short_description: str = ""
    agent_type: Optional[str] = None
    role_type: Optional[str] = None
    enterprise_scale: Optional[str] = None
    data_source_type: Optional[str] = None
    financial_capacity: Optional[float] = None
    technical_capability: Optional[float] = None
    cross_region_experience: Optional[float] = None
    policy_adaptability: Optional[float] = None
    management_capability: Optional[float] = None


class AgentProfileDTO(BaseModel):
    agent_id: str
    name: str
    role: str
    region: str
    scale: str
    ownership: str
    established_year: int
    employees: int
    annual_revenue: float
    service_scope: str
    description: str
    capabilities: Dict[str, float]
    capability_tags: List[str]
    radar: Dict[str, float]
    recent_activities: List[AgentActivityDTO]
    notes: str
    updated_at: str


class AgentChatRequest(BaseModel):
    message: str
    context: Dict = Field(default_factory=dict)


class AgentChatResponseDTO(BaseModel):
    agent_id: str
    reply: str
    reasoning_summary: str
    used_memory: List[Dict] = Field(default_factory=list)
    timestamp: str


class AgentClusterListItemDTO(BaseModel):
    cluster_id: str
    name: str
    cluster_type: str
    region: str
    status: str
    agent_count: int
    structure_tag: str
    ai_generated: bool = False


class AgentClusterDTO(BaseModel):
    cluster_id: str
    name: str
    description: str
    city_region: str
    cluster_size: int
    dominant_type: str
    market_structure: str
    primary_scope: str
    coverage: List[str]
    composition: Dict[str, int]
    capacity_radar: Dict[str, float]
    quick_presets: List[str]
    recent_usage: List[Dict]
    notes: List[str]
    map_preview: Dict
    default_output: Dict


class PolicyListItemDTO(BaseModel):
    policy_id: str
    name: str
    policy_type: str
    region: str
    status: str
    parameter_count: int
    tags: List[str] = Field(default_factory=list)


class PolicyDTO(BaseModel):
    policy_id: str
    name: str
    policy_type: str
    applicable_region: str
    start_date: str
    duration_years: int
    source: str
    description: str
    parameters: Dict[str, float]
    parameter_summary: Dict[str, float]
    impact_radar: Dict[str, float]
    parameter_tags: List[str]
    recent_updates: List[Dict]
    notes: str


class PolicyPreviewDTO(BaseModel):
    policy_id: str
    name: str
    status: str
    expected_influence_path: List[Dict]
    quantified_parameters: Dict[str, float]
    affected_agent_types: List[Dict]
    regional_impact: List[Dict]
    preview_results: Dict[str, str]


class SimulationWorkflowDTO(BaseModel):
    workflow_id: str
    name: str
    selected_cluster_id: str
    selected_agent_ids: List[str] = Field(default_factory=list)
    horizon_years: int
    time_step: str
    trigger_mode: str
    output_mode: str
    phases: List[Dict]
    interventions: List[Dict]
    events: List[Dict]
    execution_logic: Dict
    configuration: Dict = Field(default_factory=dict)


class SimulationRuntimeStateDTO(BaseModel):
    simulation_id: str
    current_tick: int
    total_ticks: int = 0
    generated_until_tick: int = 0
    requested_tick: int = 0
    progress_percent: float = 0.0
    elapsed_ms: int = 0
    last_progress_at: Optional[str] = None
    current_phase: Optional[str] = None
    current_operation: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    is_stalled: bool = False
    generation_state: Dict = Field(default_factory=dict)
    camel_queue: Dict = Field(default_factory=dict)
    interaction_session_summary: Dict = Field(default_factory=dict)
    workflow_runtime: Dict = Field(default_factory=dict)
    current_date: str
    status: str
    kpis: Dict
    map: Dict


class AnalyticsDashboardDTO(BaseModel):
    simulation_id: str
    scenario_name: str
    time_range: str
    kpis: Dict
    workflow: Dict = Field(default_factory=dict)
    spatial_distribution: Dict
    collaboration_network: Dict
    trend_analysis: Dict
    top_affected_cities: List[Dict]
    policy_evaluation_summary: Dict
