export interface AgentActivityDTO {
  activity_id: string;
  date: string;
  title: string;
  type: string;
  description?: string;
}

export interface AgentListItem {
  agent_id: string;
  name: string;
  role: string;
  region: string;
  status: "active" | "pending" | "inactive";
  ai_generated: boolean;
  rating: number;
  project_count: number;
  tags: string[];
  short_description: string;
  agent_type?: string;
  role_type?: string;
  enterprise_scale?: string;
  data_source_type?: string;
  financial_capacity?: number;
  technical_capability?: number;
  cross_region_experience?: number;
  policy_adaptability?: number;
  management_capability?: number;
  source_type?: string;
}

export interface AgentProfileDTO {
  agent_id: string;
  name: string;
  role: string;
  region: string;
  scale: string;
  ownership: string;
  established_year: number;
  employees: number;
  annual_revenue: number;
  service_scope: string;
  description: string;
  capabilities: Record<string, number>;
  capability_tags: string[];
  radar: Record<string, number>;
  recent_activities: AgentActivityDTO[];
  notes: string;
  updated_at: string;
}

export interface AgentChatResponseDTO {
  agent_id: string;
  reply: string;
  reasoning_summary: string;
  used_memory: Record<string, unknown>[];
  timestamp: string;
}

export interface AgentMemoryDTO {
  memory_id: string;
  agent_id: string;
  memory_type: string;
  related_agent_id?: string | null;
  related_project_id?: string | null;
  city?: string | null;
  event_type: string;
  content: string;
  sentiment: number;
  importance_score: number;
  decay_rate: number;
  created_tick: number;
  last_access_tick: number;
  source_type: string;
}

export interface AgentBeliefDTO {
  belief_id: string;
  agent_id: string;
  belief_type: string;
  target_type: string;
  target_id?: string | null;
  belief_value: number;
  confidence: number;
  evidence_count: number;
  updated_tick: number;
  explanation: string;
}

export interface AgentStrategyDTO {
  agent_id: string;
  primary_strategy: string;
  bidding_aggressiveness: number;
  margin_protection_level: number;
  cooperation_preference: number;
  risk_tolerance: number;
  innovation_preference: number;
  regional_expansion_preference: number;
  public_project_preference: number;
  private_project_preference: number;
  subcontracting_preference: number;
  cash_preservation_level: number;
  source_type: string;
  profile_7s: Record<string, unknown>;
  schein_culture: Record<string, unknown>;
  created_at: string;
}

export interface AgentDecisionTraceDTO {
  decision_id: string;
  agent_id: string;
  project_id?: string | null;
  tick?: number | null;
  stage?: string | null;
  role?: string | null;
  decision_type: string;
  selected_action?: string | null;
  candidate_actions: string[];
  available_actions?: string[];
  utility_score?: number | null;
  input_context?: Record<string, unknown>;
  belief_snapshot: Record<string, unknown>;
  memory_used: Record<string, unknown>[];
  memory_belief_used?: Record<string, unknown>;
  strategy_used: Record<string, unknown>;
  camel_used: boolean;
  fallback_used: boolean;
  validation_result: Record<string, unknown>;
  decision_reason?: string | null;
  model_provider?: string | null;
  model_name?: string | null;
  retry_info?: Record<string, unknown>;
  error?: Record<string, unknown>;
  explanation?: string | null;
  created_at: string;
}

export interface AgentCognitiveStateDTO {
  agent_id: string;
  profile_summary: Record<string, unknown>;
  profile_7s: Record<string, unknown>;
  schein_culture: Record<string, unknown>;
  memory: AgentMemoryDTO[];
  beliefs: AgentBeliefDTO[];
  strategy: AgentStrategyDTO;
  decision_trace: AgentDecisionTraceDTO[];
}
