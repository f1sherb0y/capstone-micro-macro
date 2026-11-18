"""Relate a saved Architect proposal to its actual registered training task."""
from integration.service_training_task_handoff import prepare_service_training_task_handoff


def prepare_architect_training_task_handoff(saved, *, invocation, training_task_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Inspect registration under the caller's actual source/authorization guard."""
    return prepare_service_training_task_handoff(saved, invocation=invocation, training_task_ref=training_task_ref,
        native_evidence_ref=native_evidence_ref, native_source_sha256=native_source_sha256,
        relation_evidence_refs=relation_evidence_refs, validate_current=validate_current, action_id='ARCHITECT-A12')
