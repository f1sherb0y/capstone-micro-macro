const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return response.json();
}

export const api = {
  health: () => request("/health"),
  createSimulation: (payload) =>
    request("/simulation/create", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  runSimulation: (simulationId) =>
    request(`/simulation/${simulationId}/run`, {
      method: "POST"
    }),
  stepSimulation: (simulationId) =>
    request(`/simulation/${simulationId}/step`, {
      method: "POST"
    }),
  getPerformance: (simulationId, projectId = "P001") =>
    request(`/simulation/${simulationId}/projects/${projectId}/performance`),
  getTimeline: (simulationId, projectId = "P001") =>
    request(`/simulation/${simulationId}/projects/${projectId}/timeline`),
  getNetwork: (simulationId) => request(`/simulation/${simulationId}/network`),
  getMetrics: (simulationId) => request(`/simulation/${simulationId}/metrics`)
};
