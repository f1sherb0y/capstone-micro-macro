import { post, request } from "./http";
import type {
  ProjectMapNodeDTO,
  SimulationAgentHistoryDTO,
  SimulationMapDTO,
  SimulationRuntimeStateDTO,
  SimulationTimelineDTO
} from "../types/simulation";

export const simulationApi = {
  runtimeState(simulationId: string, tick?: number) {
    return request<SimulationRuntimeStateDTO>(`/api/simulations/${simulationId}/runtime-state`, { query: { tick } });
  },
  map(simulationId: string, tick?: number) {
    return request<SimulationMapDTO>(`/api/simulations/${simulationId}/map`, { query: { tick } });
  },
  projects(simulationId: string, tick?: number) {
    return request<ProjectMapNodeDTO[]>(`/api/simulations/${simulationId}/projects`, { query: { tick } });
  },
  timeline(simulationId: string) {
    return request<SimulationTimelineDTO>(`/api/simulations/${simulationId}/timeline`);
  },
  agentHistory(simulationId: string, agentId: string, tick?: number) {
    return request<SimulationAgentHistoryDTO>(`/api/simulations/${simulationId}/agents/${agentId}/history`, { query: { tick } });
  },
  insights(simulationId: string, tick?: number) {
    return request<Record<string, unknown>[]>(`/api/simulations/${simulationId}/insights`, { query: { tick } });
  },
  play(simulationId: string) {
    return post<SimulationRuntimeStateDTO>(`/api/simulations/${simulationId}/play`);
  },
  pause(simulationId: string) {
    return post<SimulationRuntimeStateDTO>(`/api/simulations/${simulationId}/pause`);
  },
  step(simulationId: string) {
    return post<SimulationRuntimeStateDTO>(`/api/simulations/${simulationId}/step`);
  },
  seek(simulationId: string, targetTick: number) {
    return post<SimulationRuntimeStateDTO>(`/api/simulations/${simulationId}/seek`, { target_tick: targetTick });
  }
};
