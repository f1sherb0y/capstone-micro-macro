export interface AnalyticsDashboardDTO {
  simulation_id: string;
  scenario_name: string;
  time_range: string;
  kpis: Record<string, number>;
  workflow?: Record<string, unknown>;
  spatial_distribution: Record<string, unknown>;
  collaboration_network: Record<string, unknown>;
  trend_analysis: {
    metric_options: string[];
    time_range_options: string[];
    series: {
      name: string;
      data: { date: string; value: number }[];
    }[];
  };
  top_affected_cities: Record<string, unknown>[];
  policy_evaluation_summary: {
    overall_impact_score: number;
    impact_level: string;
    scenario_name: string;
    compared_to: string;
    evaluation_period: string;
    score_breakdown: Record<string, number>;
    key_insights: string[];
    recommended_actions: Record<string, string>[];
  };
}
