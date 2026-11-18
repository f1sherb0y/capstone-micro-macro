import { post, put, request } from "./http";
import type { SimulationWorkflowDTO } from "../types/workflow";
import type { ProcurementState } from "../types/procurement";

export const workflowApi = {
  list() {
    return request<SimulationWorkflowDTO[]>("/api/workflows");
  },
  get(workflowId: string) {
    return request<SimulationWorkflowDTO>(`/api/workflows/${workflowId}`);
  },
  create(payload: Partial<SimulationWorkflowDTO>) {
    return post<SimulationWorkflowDTO>("/api/workflows", payload);
  },
  update(workflowId: string, payload: Partial<SimulationWorkflowDTO>) {
    return put<SimulationWorkflowDTO>(`/api/workflows/${workflowId}`, payload);
  },
  validate(workflowId: string) {
    return post<{ valid: boolean; warnings: string[]; errors: string[] }>(`/api/workflows/${workflowId}/validate`);
  },
  saveTemplate(workflowId: string) {
    return post<{ workflow_id: string; template_saved: boolean }>(`/api/workflows/${workflowId}/save-template`);
  },
  loadTemplate() {
    return post<SimulationWorkflowDTO>("/api/workflows/load-template");
  },
  run(workflowId: string, payload: Record<string, unknown> = {}) {
    return post<{
      simulation_id: string;
      procurement: ProcurementState;
      workflow_id: string;
      status: string;
      agent_count: number;
      project_count: number;
      prior_edge_count: number;
      current_tick: number;
      total_ticks?: number;
      live_mode?: boolean;
      configuration_summary?: Record<string, unknown>;
      workflow_runtime?: Record<string, unknown>;
      message: string;
    }>(`/api/workflows/${workflowId}/run`, payload);
  }
};
