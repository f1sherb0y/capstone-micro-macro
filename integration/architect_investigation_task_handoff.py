"""Fixed Architect A13 investigation intake to actual A04 planning tasks."""
from integration.service_investigation_task_handoff import prepare_service_investigation_task_handoff


def prepare_architect_investigation_task_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    return prepare_service_investigation_task_handoff(saved, invocation=invocation,
        registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
        native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
        validate_current=validate_current, action_id='ARCHITECT-A13')
