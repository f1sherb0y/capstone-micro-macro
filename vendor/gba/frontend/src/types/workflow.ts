import type { ProcurementExecution } from "./procurement";

export interface SimulationWorkflowDTO {
  workflow_id: string;
  name: string;
  selected_cluster_id: string;
  selected_agent_ids: string[];
  horizon_years: number;
  time_step: "monthly" | "quarterly" | "yearly";
  trigger_mode: "scheduled" | "event_based" | "scheduled_event_based";
  output_mode: "summary" | "full_trace";
  phases: Record<string, unknown>[];
  interventions: Record<string, unknown>[];
  events: Record<string, unknown>[];
  execution_logic: Record<string, unknown>;
  configuration?: {
    procurement_execution?: ProcurementExecution;
    periods?: Record<string, unknown>[];
    policies?: Record<string, unknown>[];
    events?: Record<string, unknown>[];
    agent_source?: string;
    agent_count?: number | null;
    agent_regions?: string[];
    max_tender_invites?: number;
    use_prior_network_edges?: boolean;
  };
}
