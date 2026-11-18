import type { AnalyticsDashboardDTO } from "../types/analytics";

export function analyticsTrendToHistory(dashboard?: AnalyticsDashboardDTO | null) {
  const scenario = dashboard?.trend_analysis?.series?.[1]?.data || [];
  const baseline = dashboard?.trend_analysis?.series?.[0]?.data || [];
  return scenario.map((point, index) => ({
    tick: parseTrendTick(point.date, index + 1),
    actual_progress: normalize(point.value, scenario),
    planned_progress: normalize(baseline[index]?.value || point.value, baseline)
  }));
}

export function analyticsNetworkToGraph(dashboard?: AnalyticsDashboardDTO | null) {
  const network = dashboard?.collaboration_network as any;
  return {
    nodes: (network?.nodes || []).map((node: any) => ({
      id: node.node_id,
      node_type: node.node_type === "project" ? "project" : "agent"
    })),
    edges: (network?.edges || []).map((edge: any) => ({
      source_agent_id: edge.source_id,
      target_agent_id: edge.target_id
    }))
  };
}

function normalize(value: number, series: { value: number }[]) {
  const max = Math.max(...series.map((item) => item.value), 1);
  return value / max;
}

function parseTrendTick(date: string | undefined, fallback: number) {
  const match = String(date || "").match(/\d+/);
  return match ? Number(match[0]) : fallback;
}
