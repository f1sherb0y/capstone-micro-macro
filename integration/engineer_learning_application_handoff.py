"""Relate a saved Engineer revision to actual applied private judgment state."""
from integration.service_learning_application_handoff import prepare_service_judgment_application_handoff


def prepare_engineer_judgment_application_handoff(saved, *, invocation, execution_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Inspect application under the caller's actual source/authorization guard."""
    return prepare_service_judgment_application_handoff(saved, invocation=invocation, execution_ref=execution_ref,
        native_evidence_ref=native_evidence_ref, native_source_sha256=native_source_sha256,
        relation_evidence_refs=relation_evidence_refs, validate_current=validate_current, action_id='ENGINEER-A12')
