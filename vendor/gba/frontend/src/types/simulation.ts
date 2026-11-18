export interface ProjectMapNodeDTO {
  project_id: string;
  name: string;
  city: string;
  latitude: number;
  longitude: number;
  project_type: string;
  status: "building" | "ongoing" | "completed" | "suspended" | "failed";
  progress: number;
  quality_score: number;
  delay_days: number;
  cost_overrun_ratio: number;
  stage: string;
  owner_id?: string | null;
  selected_architect_id?: string | null;
  selected_engineer_id?: string | null;
  selected_qs_id?: string | null;
  selected_contractor_id?: string | null;
  selected_supplier_ids?: string[];
  participants?: Array<{
    agent_id: string;
    name: string;
    role: string;
    city: string;
    status?: string;
  }>;
  initial_budget?: number | null;
  estimated_cost?: number | null;
  contract_sum?: number | null;
  planned_duration?: number | null;
  bids?: Record<string, unknown>[];
  contracts?: Record<string, unknown>[];
  created_tick?: number | null;
  interaction_sessions?: Array<{
    session_id: string;
    session_type: string;
    tick?: number | null;
    stage?: string | null;
    participants?: string[];
    summary?: string;
    recent_messages?: Record<string, unknown>[];
  }>;
}

export interface EnterpriseMapNodeDTO {
  agent_id: string;
  name: string;
  role: string;
  city: string;
  latitude: number;
  longitude: number;
  status: string;
  engaged_project_ids: string[];
}

export interface FlowLinkDTO {
  link_id: string;
  project_id?: string;
  source_id: string;
  target_id: string;
  source_city?: string;
  target_city?: string;
  source_latitude: number;
  source_longitude: number;
  target_latitude: number;
  target_longitude: number;
  link_type: "resource_flow" | "collaboration_link";
  strength: number;
  flow_volume?: number;
  cross_city: boolean;
  status: string;
}

export interface SimulationMapDTO {
  projects: ProjectMapNodeDTO[];
  enterprises: EnterpriseMapNodeDTO[];
  resource_flows: FlowLinkDTO[];
  collaboration_links: FlowLinkDTO[];
}

export interface RuntimeStepProfileDTO {
  tick?: number;
  status?: string;
  current_operation?: string;
  project_count?: number;
  project_count_after_generation?: number;
  active_project_count?: number;
  agent_count?: number;
  macro_environment_ms?: number;
  owner_initiation_ms?: number;
  active_project_scan_ms?: number;
  project_lifecycle_ms?: number;
  project_state_update_ms?: number;
  agent_operations_ms?: number;
  network_metrics_ms?: number;
  snapshot_save_ms?: number;
  return_snapshot_ms?: number;
  total_step_ms?: number;
  total_step_with_return_ms?: number;
  [key: string]: unknown;
}

export interface RuntimePerformanceDTO {
  requested_tick?: number;
  started_from_tick?: number;
  generated_until_tick?: number;
  effective_tick?: number;
  ticks_generated?: number;
  request_total_ms?: number;
  generation_loop_ms?: number;
  snapshot_lookup_ms?: number;
  map_build_ms?: number;
  kpi_build_ms?: number;
  interaction_summary_ms?: number;
  last_step_profile?: RuntimeStepProfileDTO;
  recent_step_profiles?: RuntimeStepProfileDTO[];
  [key: string]: unknown;
}

export interface SimulationRuntimeStateDTO {
  simulation_id: string;
  current_tick: number;
  total_ticks?: number;
  generated_until_tick?: number;
  requested_tick?: number;
  progress_percent?: number;
  elapsed_ms?: number;
  last_progress_at?: string | null;
  current_phase?: string | null;
  current_operation?: string | null;
  warnings?: string[];
  error?: string | null;
  is_stalled?: boolean;
  generation_state?: {
    status?: string;
    requested_tick?: number;
    generated_until_tick?: number;
    current_tick?: number;
    current_phase?: string;
    current_operation?: string;
    progress_percent?: number;
    request_progress_percent?: number;
    elapsed_ms?: number;
    last_progress_at?: string | null;
    warnings?: string[];
    error?: string | null;
    is_stalled?: boolean;
    camel_queue?: CamelQueueDTO;
    performance?: RuntimePerformanceDTO;
  };
  camel_queue?: CamelQueueDTO;
  interaction_session_summary?: InteractionSessionSummaryDTO;
  current_date: string;
  status: string;
  kpis: Record<string, number>;
  map: SimulationMapDTO;
}

export interface InteractionSessionSummaryDTO {
  total?: number;
  by_type?: Record<string, number>;
  latest?: {
    session_id?: string;
    session_type?: string;
    project_id?: string;
    project_name?: string;
    tick?: number;
    latest_tick?: number;
    latest_event_type?: string;
    latest_action?: string;
    latest_reason?: string;
    summary?: string;
  } | null;
}

export interface CamelQueueDTO {
  queued?: number;
  running?: number;
  completed?: number;
  failed?: number;
  skipped_by_budget?: number;
  avg_model_ms?: number;
  avg_queue_ms?: number;
  current_operation?: string;
  last_error?: string | null;
}

export interface SimulationTimelineEventDTO {
  event_id: string;
  tick: number;
  project_id?: string | null;
  agent_id?: string | null;
  event_type: string;
  stage?: string | null;
  description: string;
  data?: Record<string, unknown>;
}

export interface SimulationTimelineTickDTO {
  tick: number;
  date: string;
  active_projects: number;
  completed_projects: number;
  project_count: number;
  average_progress: number;
  average_quality: number;
  delay_days: number;
  stage_counts: Record<string, number>;
  metrics?: Record<string, unknown>;
  collaboration_edges: number;
  resource_flows: number;
  engaged_agents: number;
  stage: string;
  event_count: number;
  important_events: SimulationTimelineEventDTO[];
}

export interface SimulationTimelineDTO {
  simulation_id: string;
  start_date: string;
  end_date: string;
  ticks: SimulationTimelineTickDTO[];
}

export interface SimulationAgentHistoryDTO {
  simulation_id: string;
  current_tick?: number;
  agent: Record<string, unknown> | null;
  events: SimulationTimelineEventDTO[];
  activity_timeline?: SimulationTimelineEventDTO[];
  engagements: Record<string, unknown>[];
  status_timeline: {
    tick: number;
    date: string;
    status: string;
    project_ids: string[];
  }[];
  summary: {
    joined_projects: number;
    joined_project_ids: string[];
    event_count: number;
    bid_events: number;
    release_events: number;
    active_ticks: number;
    first_active_tick: number | null;
    last_active_tick: number | null;
    event_counts: Record<string, number>;
  };
}
