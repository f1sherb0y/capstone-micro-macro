export interface ProcurementExecution {
  schema_version: "1.0";
  mode: "gba_native" | "codedemo_micro";
  scope: "full_procurement";
  adapter_profile_id: "codedemo-local" | null;
  failure_policy: "pause";
}

export interface ProcurementCapability {
  mode: ProcurementExecution["mode"];
  label: string;
  available: boolean;
  scope: ProcurementExecution["scope"];
  adapter_profile_id: ProcurementExecution["adapter_profile_id"];
  reason: string;
}

export interface ProcurementState {
  simulation_id: string;
  effective_mode: ProcurementExecution["mode"];
  scope: ProcurementExecution["scope"];
  locked: true;
  effective_configuration: ProcurementExecution;
  configuration_hash: string;
}
