import type { AgentClusterDTO, AgentClusterListItem } from "../types/cluster";

export function toClusterRow(cluster: AgentClusterListItem) {
  return {
    id: cluster.cluster_id,
    name: cluster.name,
    type: titleCase(cluster.cluster_type.replace("_", " ")),
    region: cluster.region,
    size: cluster.agent_count,
    status: titleCase(cluster.status),
    tag: cluster.structure_tag
  };
}

export function toClusterComposition(cluster?: AgentClusterDTO | null) {
  if (!cluster?.composition) {
    return [
      { label: "Large Enterprises", value: 28 },
      { label: "Mid-size Enterprises", value: 34 },
      { label: "Specialized Firms", value: 18 },
      { label: "Consulting Support", value: 10 },
      { label: "Supply Support", value: 10 }
    ];
  }
  return [
    { label: "Contractors", value: cluster.composition.contractors || 0 },
    { label: "Consultants", value: cluster.composition.consultants || 0 },
    { label: "Suppliers", value: cluster.composition.suppliers || 0 },
    { label: "Developers", value: cluster.composition.developers || 0 },
    { label: "Others", value: cluster.composition.others || 0 }
  ];
}

function titleCase(value: string) {
  return value.replace(/\w\S*/g, (part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase());
}
