export interface PolicyListItem {
  policy_id: string;
  name: string;
  policy_type: string;
  region: string;
  status: "active" | "draft" | "pending" | "ready";
  parameter_count: number;
  tags: string[];
}

export interface PolicyDTO {
  policy_id: string;
  name: string;
  policy_type: string;
  applicable_region: string;
  start_date: string;
  duration_years: number;
  source: string;
  description: string;
  parameters: Record<string, number>;
  parameter_summary: Record<string, number>;
  impact_radar: Record<string, number>;
  parameter_tags: string[];
  recent_updates: Record<string, unknown>[];
  notes: string;
}

export interface PolicyPreviewDTO {
  policy_id: string;
  name: string;
  status: string;
  expected_influence_path: Record<string, unknown>[];
  quantified_parameters: Record<string, number>;
  affected_agent_types: { role: string; impact_level: string }[];
  regional_impact: { region: string; impact_level: string }[];
  preview_results: Record<string, string>;
}
