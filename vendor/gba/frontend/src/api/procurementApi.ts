import { request } from "./http";
import type { ProcurementCapability, ProcurementState } from "../types/procurement";

export const procurementApi = {
  engines() {
    return request<ProcurementCapability[]>("/api/procurement-engines");
  },
  state(simulationId: string) {
    return request<ProcurementState>(`/api/simulations/${encodeURIComponent(simulationId)}/procurement`);
  }
};
