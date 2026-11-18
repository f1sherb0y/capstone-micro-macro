import { post, put, request } from "./http";
import type { PageData } from "../types/api";
import type {
  AgentBeliefDTO,
  AgentChatResponseDTO,
  AgentCognitiveStateDTO,
  AgentDecisionTraceDTO,
  AgentListItem,
  AgentMemoryDTO,
  AgentProfileDTO,
  AgentStrategyDTO
} from "../types/agent";

export const agentApi = {
  list(params: Record<string, string | number | undefined> = {}) {
    return request<PageData<AgentListItem>>("/api/agents", { query: params });
  },
  get(agentId: string) {
    return request<AgentProfileDTO>(`/api/agents/${agentId}`);
  },
  create(payload: Partial<AgentListItem>) {
    return post<AgentListItem>("/api/agents", payload);
  },
  update(agentId: string, payload: Partial<AgentListItem>) {
    return put<AgentListItem>(`/api/agents/${agentId}`, payload);
  },
  memory(agentId: string, limit = 20) {
    return request<AgentMemoryDTO[]>(`/api/agents/${agentId}/memory`, { query: { limit } });
  },
  beliefs(agentId: string) {
    return request<AgentBeliefDTO[]>(`/api/agents/${agentId}/beliefs`);
  },
  strategy(agentId: string) {
    return request<AgentStrategyDTO>(`/api/agents/${agentId}/strategy`);
  },
  decisionTrace(agentId: string, limit = 50) {
    return request<AgentDecisionTraceDTO[]>(`/api/agents/${agentId}/decision-trace`, { query: { limit } });
  },
  cognitiveState(agentId: string) {
    return request<AgentCognitiveStateDTO>(`/api/agents/${agentId}/cognitive-state`);
  },
  chat(agentId: string, message: string, context: Record<string, unknown> = {}) {
    return post<AgentChatResponseDTO>(`/api/agents/${agentId}/chat`, { message, context });
  }
};
