"""Relate an original A09 revision to its actual registered version for A07."""
from integration.engineer_design_registration_handoff import _prepare_engineer_registration_handoff


def prepare_engineer_change_revision_registration_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Require native revision lineage and A07's independent current authority.

    The fixed A09 route retains the complete saved revise draft, original issue,
    obligation, parent/content, instruction and change basis. Actual registration
    and the new deliverable must match full content and immutable result/source
    evidence. An independent gate verifies native artifact/task/dependency and
    unresolved-question/issue lineage, service authority, receipt and privacy.
    Registration grants no completion, acceptance, signing or allowed use.
    """
    return _prepare_engineer_registration_handoff(saved, source_action_id='ENGINEER-A09',
        invocation=invocation, registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
        native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
        validate_current=validate_current)
