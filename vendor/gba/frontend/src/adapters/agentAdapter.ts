import type { AgentListItem, AgentProfileDTO } from "../types/agent";

const capabilityLabels: Record<string, string> = {
  financial_strength: "Financial Strength",
  technical_capability: "Technical Capability",
  project_experience: "Project Experience",
  innovation_level: "Innovation Level",
  compliance_level: "Compliance Level"
};

export function toAgentRow(agent: AgentListItem) {
  return {
    ...agent,
    role: normalizeRole(agent.role),
    projects: agent.project_count,
    capabilities: [
      { label: "Financial Strength", value: 4.0 },
      { label: "Technical Capability", value: 4.1 },
      { label: "Project Experience", value: 4.2 },
      { label: "Innovation Level", value: 3.9 },
      { label: "Compliance Level", value: 4.1 }
    ]
  };
}

export function toAgentProfileUi(profile: AgentProfileDTO) {
  return {
    ...profile,
    role: normalizeRole(profile.role),
    projects: 0,
    capabilities: Object.entries(profile.capabilities).map(([key, value]) => ({
      label: capabilityLabels[key] || key,
      value
    }))
  };
}

function normalizeRole(role: string) {
  const lower = role.toLowerCase();
  return {
    owner: "Owner",
    developer: "Owner",
    architect: "Architect",
    designer: "Architect",
    "design institute": "Architect",
    design_institute: "Architect",
    qs: "QS",
    quantity_surveyor: "QS",
    "quantity surveyor": "QS",
    consultant: "Consultant",
    contractor: "Contractor",
    supplier: "Supplier",
    government: "Government"
  }[lower] || role;
}
