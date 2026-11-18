"""Computable local Owner A01 capacity condition over fresh authorized views."""
from decimal import Decimal
from fractions import Fraction

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.owner_objects import OwnerManagementCapacityView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


def owner_management_profile(read_current):
    """Host supplies (new context, authorized read view, exact current capacity ref).

    This is a local screening condition, not a formal capacity reservation or a
    claim that the old GBA protocol publishes ManagementCapacity changes.
    """
    def evaluate(check):
        context, reading, ref = read_current(check)
        if not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView) or not isinstance(ref, Reference):
            raise TaskConflict("Owner condition requires a typed current authorized reading")
        source = check.source["identity"]
        if (context.run_id != source["run_id"] or reading.organization_id != source["organization_id"]
                or context.business_time != check.signal.business_time):
            raise TaskConflict("Owner condition reading differs from its run, recipient or current business time")
        reading.check_method_context(context, "OWN-A01")
        old = check.condition.object_refs
        if len(old) != 1 or old[0].kind != "ManagementCapacity" or (ref.kind, ref.id) != (old[0].kind, old[0].id):
            raise TaskConflict("Owner condition must read the same management capacity object")
        if ref.version == old[0].version:
            return "unavailable"
        capacity = reading.resolve(ref)
        if not isinstance(capacity, OwnerManagementCapacityView) or capacity.organization_id != reading.organization_id:
            raise TaskConflict("Management capacity schema or owner mismatch")
        now = context.business_time
        if capacity.ref.key() != ref.key() or not capacity.effective_window.contains(now):
            return "unavailable"
        if capacity.total.state != "known" or capacity.screening_requirement.state != "known":
            return "unavailable"
        total, required = capacity.total.value, capacity.screening_requirement.value
        if total.unit != required.unit:
            return "unavailable"
        refs = [*capacity.evidence_refs, total.basis_ref, required.basis_ref]
        used = Fraction(0)
        for load in capacity.commitments:
            if load.window.start.clock_ref != now.clock_ref or load.window.bounds != "closed_open":
                return "unavailable"
            if load.window.contains(now):
                if load.quantity.unit != total.unit:
                    return "unavailable"
                used += Fraction(Decimal(load.quantity.value))
                refs.append(load.quantity.basis_ref)
        for evidence_ref in refs:
            evidence = reading.resolve(evidence_ref)
            if not isinstance(evidence, EvidenceRecord) or (evidence.effective_window is not None
                    and not evidence.effective_window.contains(now)):
                return "unavailable"
        reading.recheck()
        return "ready" if used + Fraction(Decimal(required.value)) <= Fraction(Decimal(total.value)) else "waiting"

    return ConditionProfile("OWN-A01", "management_capacity_revalidated", "1",
                            frozenset({"dependency_change"}), evaluate)
