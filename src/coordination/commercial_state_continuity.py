"""Keep original commercial obligations, occupancy and execution history on recovery."""
from src.actions.contracts.common import EvidenceRecord
from src.coordination.commercial_execution_query import _STATE_LINKS, _EXECUTION_METADATA, TERMINAL
from src.coordination.tasks import TaskConflict


def check_commercial_state_continuity(*, reading, types, original_profile, profile,
        original_context, context, organization_id, supplier=False):
    """Retain source identities; native validation authenticates changes between versions."""
    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Commercial recovery requires exact original/current profile and state sources')
        return row

    def evidence_refs(refs, *, at=None):
        for ref in refs:
            row = read(ref, EvidenceRecord)
            if row.effective_window is not None:
                if (row.effective_window.start.clock_ref != context.business_time.clock_ref
                        or row.effective_window.start.offset > context.business_time.offset
                        or at is not None and not row.effective_window.contains(at)):
                    raise TaskConflict('Commercial recovery loses valid original/current evidence')

    if (not isinstance(original_profile, types['ContinuationProfile'])
            or not isinstance(profile, types['ContinuationProfile'])
            or original_profile.organization_id != organization_id or profile.organization_id != organization_id
            or original_profile.scope != original_context.scope or profile.scope != context.scope
            or original_profile.state_ref.key()[:2] != profile.state_ref.key()[:2]):
        raise TaskConflict('Commercial recovery replaces original firm, scope or physical state')
    old, current = (read(row.state_ref, types['ContinuationState']) for row in (original_profile, profile))
    for state, invocation in ((old, original_context), (current, context)):
        if (state.organization_id != organization_id or state.run_id != context.run_id
                or state.scope != invocation.scope or state.coverage != 'complete' or state.as_of != invocation.business_time
                or state.available_at.clock_ref != invocation.business_time.clock_ref
                or state.available_at.offset > invocation.business_time.offset
                or not state.effective_window.contains(invocation.business_time)):
            raise TaskConflict('Commercial recovery replaces original complete state or knowledge time')
        evidence_refs(state.evidence_refs, at=invocation.business_time)
    fields = (*_STATE_LINKS, 'work_in_progress_refs', 'shipment_refs', 'production_line_commitment_refs') if supplier else _STATE_LINKS
    for field in fields:
        before_refs, after_refs = getattr(old, field), getattr(current, field)
        before = {ref.key()[:2] for ref in before_refs}
        after = {ref.key()[:2] for ref in after_refs}
        if len(before) != len(before_refs) or len(after) != len(after_refs) or not before <= after:
            raise TaskConflict('Commercial recovery drops or repeats original ' + field)
        # These are retained original sources, including released/cleared rows;
        # recovering a task must not replace them with a newly empty state.
        for ref in (*before_refs, *after_refs):
            reading.resolve(ref)
    if old.resource_calendar_ref is not None and (current.resource_calendar_ref is None
            or old.resource_calendar_ref.key()[:2] != current.resource_calendar_ref.key()[:2]):
        raise TaskConflict('Commercial recovery replaces the original shared resource calendar')
    histories = []
    for state in (old, current):
        rows = [read(ref, types['ContinuationExecution']) for ref in state.execution_refs]
        if (len({row.business_key for row in rows}) != len(rows)
                or any(row.organization_id != organization_id or row.run_id != context.run_id
                    or row.state_ref.key()[:2] != state.ref.key()[:2] for row in rows)):
            raise TaskConflict('Commercial recovery substitutes original business execution history')
        for row in rows:
            if row.available_at.clock_ref != state.as_of.clock_ref or row.available_at.offset > state.as_of.offset:
                raise TaskConflict('Commercial recovery introduces execution history unavailable at its read point')
            # There is no actual per-status occurrence field on this history.
            evidence_refs(row.evidence_refs)
        histories.append({row.ref.key()[:2]: row for row in rows})
    for key, before in histories[0].items():
        after = histories[1][key]
        if (before.model_dump(exclude=_EXECUTION_METADATA) != after.model_dump(exclude=_EXECUTION_METADATA)
                or before.status in TERMINAL and before.status != after.status):
            raise TaskConflict('Commercial recovery rewrites original execution content or terminal disposition')
