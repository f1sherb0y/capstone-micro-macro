export interface AgentClusterListItem {
  cluster_id: string;
  name: string;
  cluster_type: string;
  region: string;
  status: "ready" | "draft" | "inactive";
  agent_count: number;
  structure_tag: string;
  ai_generated: boolean;
}

export interface AgentClusterDTO {
  cluster_id: string;
  name: string;
  description: string;
  city_region: string;
  cluster_size: number;
  dominant_type: string;
  market_structure: string;
  primary_scope: string;
  coverage: string[];
  composition: Record<string, number>;
  capacity_radar: Record<string, number>;
  quick_presets: string[];
  recent_usage: Record<string, unknown>[];
  notes: string[];
  map_preview: {
    nodes: Record<string, unknown>[];
    links: Record<string, unknown>[];
  };
  default_output: Record<string, unknown>;
}
