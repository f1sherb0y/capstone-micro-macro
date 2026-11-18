import type { PolicyDTO, PolicyListItem, PolicyPreviewDTO } from "../types/policy";

export function toPolicyRow(policy: PolicyListItem) {
  return {
    id: policy.policy_id,
    name: policy.name,
    type: titleCase(policy.policy_type),
    region: policy.region,
    status: titleCase(policy.status),
    params: policy.parameter_count,
    color: policyColor(policy.policy_type)
  };
}

export function toPolicyParams(policy?: PolicyDTO | null) {
  if (!policy?.parameter_summary) {
    return [
      { label: "Policy Intensity", value: 4.3 },
      { label: "Scope of Impact", value: 3.8 },
      { label: "Incentive Strength", value: 3.6 },
      { label: "Compliance Requirement", value: 3.0 },
      { label: "Implementation Certainty", value: 4.1 }
    ];
  }
  return [
    { label: "Policy Intensity", value: policy.parameter_summary.policy_intensity },
    { label: "Scope of Impact", value: policy.parameter_summary.scope_of_impact },
    { label: "Incentive Strength", value: policy.parameter_summary.incentive_strength },
    { label: "Compliance Requirement", value: policy.parameter_summary.compliance_requirement },
    { label: "Implementation Certainty", value: policy.parameter_summary.implementation_certainty }
  ];
}

export function toPolicyImpacts(preview?: PolicyPreviewDTO | null) {
  if (!preview?.quantified_parameters) {
    return [
      { label: "Waiting Time Reduction", width: "62%", delta: "-25%" },
      { label: "Approval Success Increase", width: "78%", delta: "+18%" },
      { label: "Compliance Burden", width: "46%", delta: "-15%" },
      { label: "Incentive Strength", width: "80%", delta: "+22%" }
    ];
  }
  return [
    { label: "Waiting Time Reduction", width: `${Math.abs(preview.quantified_parameters.waiting_time_reduction) * 2.5}%`, delta: `${preview.quantified_parameters.waiting_time_reduction}%` },
    { label: "Approval Success Increase", width: `${preview.quantified_parameters.approval_success_increase * 4}%`, delta: `+${preview.quantified_parameters.approval_success_increase}%` },
    { label: "Compliance Burden", width: `${Math.abs(preview.quantified_parameters.compliance_burden_change) * 3}%`, delta: `${preview.quantified_parameters.compliance_burden_change}%` },
    { label: "Incentive Strength", width: `${preview.quantified_parameters.incentive_strength_change * 3.5}%`, delta: `+${preview.quantified_parameters.incentive_strength_change}%` }
  ];
}

function policyColor(type: string) {
  return {
    regulation: "orange",
    incentive: "green",
    sustainability: "green",
    technology: "purple",
    procurement: "blue"
  }[type] || "orange";
}

function titleCase(value: string) {
  return value.replace(/\w\S*/g, (part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase());
}
