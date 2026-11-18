"""QS A02 professional-service intake with an explicit conflict check."""
from src.actions.contracts.qs_objects import QSConflictCheckView
from src.actions.contracts.common import EvidenceRecord
from src.actions.roles.service_intake import (
    ServiceIntakeGap, _needs, assess_professional_service,
)


def assess_service_request(context, action_input, reading):
    """Assess only sourced terms; never turn selection into an appointment."""
    try:
        conflict = None
        if action_input.conflict_check_ref is not None:
            conflict = reading.resolve(action_input.conflict_check_ref)
            if not isinstance(conflict, QSConflictCheckView):
                return {"kind": "unsupported", "capability_ref": {
                    "kind": "Capability", "id": "qs-conflict-check-schema", "version": "1"}}
            if (conflict.organization_id != reading.organization_id
                    or conflict.request_ref != action_input.request_ref
                    or conflict.scope != action_input.scope):
                raise ValueError("Conflict check differs from the exact QS request or scope")
            if conflict.checked_at.clock_ref != context.business_time.clock_ref:
                return {"kind": "unsupported", "capability_ref": {
                    "kind": "Capability", "id": "qs-conflict-check-clock", "version": "1"}}
            if conflict.checked_at.offset > context.business_time.offset:
                _needs("conflict_check_at_current_read_point", [conflict.ref])
            if not conflict.effective_window.contains(context.business_time):
                _needs("current_conflict_check", [conflict.ref])
            for source in conflict.evidence_refs:
                record = reading.resolve(source)
                if not isinstance(record, EvidenceRecord):
                    return {"kind": "unsupported", "capability_ref": {
                        "kind": "Capability", "id": "qs-conflict-check-evidence-schema", "version": "1"}}
                if record.effective_window is not None:
                    if record.effective_window.start.clock_ref != context.business_time.clock_ref:
                        return {"kind": "unsupported", "capability_ref": {
                            "kind": "Capability", "id": "qs-conflict-check-evidence-clock", "version": "1"}}
                    if (not record.effective_window.contains(context.business_time)
                            or not record.effective_window.contains(conflict.checked_at)):
                        _needs("applicable_conflict_evidence", [source])
            if conflict.status == "failed":
                return {"kind": "technical_error", "error": {"kind": "unrecorded",
                        "correlation_id": getattr(context, "operation_id", "qs-intake"),
                        "code": "conflict_check_failed"}, "retryability": "unknown"}
            if conflict.status == "unknown":
                _needs("conflict_check_result", [conflict.ref])
            if conflict.status == "conflict":
                return {"kind": "completed", "payload": {
                    "choice": "decline", "scope": action_input.scope,
                    "reason": "The sourced conflict check identifies an unresolved conflict",
                    "note": "Decline without forming an appointment or contract"}}

        result = assess_professional_service(
            context, action_input, reading, role_key="qs",
            accepted_field="terms_ref",
        )
        # A missing check is an information gap for acceptance.  It may still
        # produce a sourced counteroffer, which does not assert independence.
        if conflict is None and result.get("kind") == "completed":
            payload = result.get("payload", {})
            if payload.get("choice") == "accept":
                return {"kind": "needs_information", "missing_fields": ["conflict_check_ref"],
                        "requested_refs": []}
        return result
    except ServiceIntakeGap as gap:
        return gap.result
