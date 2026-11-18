import { request } from "./http";
import type { AnalyticsDashboardDTO } from "../types/analytics";

export const analyticsApi = {
  dashboard(simulationId?: string, scenario = "green_growth_2030") {
    return request<AnalyticsDashboardDTO>("/api/analytics/dashboard", { query: { simulation_id: simulationId, scenario } });
  },
  spatialDistribution(simulationId?: string, projectType = "all", policyScenario = "green_growth_2030") {
    return request<Record<string, unknown>>("/api/analytics/spatial-distribution", {
      query: { simulation_id: simulationId, project_type: projectType, policy_scenario: policyScenario }
    });
  },
  collaborationNetwork(simulationId?: string, region = "all") {
    return request<Record<string, unknown>>("/api/analytics/collaboration-network", { query: { simulation_id: simulationId, region } });
  },
  trends(simulationId?: string, metric = "total_project_investment", timeRange = "24_months") {
    return request<Record<string, unknown>>("/api/analytics/trends", { query: { simulation_id: simulationId, metric, time_range: timeRange } });
  },
  policyEvaluation(simulationId?: string, policyId = "POL001") {
    return request<Record<string, unknown>>("/api/analytics/policy-evaluation", { query: { simulation_id: simulationId, policy_id: policyId } });
  }
};
