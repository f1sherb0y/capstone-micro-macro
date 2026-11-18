import { post, put, request } from "./http";
import type { PageData } from "../types/api";
import type { PolicyDTO, PolicyListItem, PolicyPreviewDTO } from "../types/policy";

export const policyApi = {
  list(params: Record<string, string | number | undefined> = {}) {
    return request<PageData<PolicyListItem>>("/api/policies", { query: params });
  },
  get(policyId: string) {
    return request<PolicyDTO>(`/api/policies/${policyId}`);
  },
  create(payload: Partial<PolicyDTO>) {
    return post<PolicyListItem>("/api/policies", payload);
  },
  update(policyId: string, payload: Partial<PolicyDTO>) {
    return put<PolicyListItem>(`/api/policies/${policyId}`, payload);
  },
  import(payload: Partial<PolicyDTO>) {
    return post<PolicyListItem>("/api/policies/import", payload);
  },
  preview(policyId: string) {
    return request<PolicyPreviewDTO>(`/api/policies/${policyId}/preview`);
  },
  mapToParameters(policyId: string) {
    return post<Record<string, number>>(`/api/policies/${policyId}/map-to-parameters`);
  }
};
