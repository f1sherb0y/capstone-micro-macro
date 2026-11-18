import { post, put, request } from "./http";
import type { PageData } from "../types/api";
import type { AgentClusterDTO, AgentClusterListItem } from "../types/cluster";

export const clusterApi = {
  list(params: Record<string, string | number | undefined> = {}) {
    return request<PageData<AgentClusterListItem>>("/api/clusters", { query: params });
  },
  get(clusterId: string) {
    return request<AgentClusterDTO>(`/api/clusters/${clusterId}`);
  },
  create(payload: Partial<AgentClusterDTO>) {
    return post<AgentClusterDTO>("/api/clusters", payload);
  },
  update(clusterId: string, payload: Partial<AgentClusterDTO>) {
    return put<AgentClusterDTO>(`/api/clusters/${clusterId}`, payload);
  },
  duplicate(clusterId: string) {
    return post<AgentClusterDTO>(`/api/clusters/${clusterId}/duplicate`);
  },
  useInSimulation(clusterId: string) {
    return post<Record<string, unknown>>(`/api/clusters/${clusterId}/use-in-simulation`);
  }
};
