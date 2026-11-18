"""Resolve original inventory uncertainty without inferring disposal rights."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.commercial_continuation_objects import CommercialMaterialView
from src.actions.contracts.supplier_continuation_objects import SupplierContinuationInventoryView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


def commercial_material_profiles(read_current):
    """Read original/current inventory versions from the host's authorized view.

    Known damage, return or incorporation can prompt a new decision. They do
    not mean usable stock, cleared obligations or permitted transfer. Actual
    owner/custodian rights and every remaining duty are checked by that action.
    """
    if not callable(read_current):
        raise ValueError('A current authorized inventory reader is required')

    def profile(action_id, schema):
        code = 'query_original_material_position'

        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or check.condition.condition_code != code
                    or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id']
                    or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Inventory condition changes original task, run or recipient')
            old_refs = check.condition.object_refs
            if len(old_refs) != 1 or old_refs[0].kind != 'InventoryPosition':
                raise TaskConflict('Inventory wait requires one original position')
            context, reading, ref = read_current(check)
            if (not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView)
                    or not isinstance(ref, Reference)):
                raise TaskConflict('Inventory condition requires a typed current authorized reading')
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.business_time != check.signal.business_time):
                raise TaskConflict('Inventory condition changes action, run, recipient or current time')
            reading.check_method_context(context, action_id)
            old_ref = old_refs[0]
            if (ref.kind, ref.id) != (old_ref.kind, old_ref.id):
                raise TaskConflict('Inventory condition substitutes another position')
            try:
                if ref.version == old_ref.version:
                    return 'unavailable'
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if not isinstance(original, schema) or not isinstance(current, schema):
                    raise TaskConflict('Inventory condition lacks the original role projection schema')
                if original.ref != old_ref or current.ref != ref:
                    raise TaskConflict('Inventory condition projection reference mismatch')
                fields = ('organization_id','physical_position_key','batch_ref','product_ref','scope')
                if (current.organization_id != source['organization_id']
                        or any(getattr(original, field) != getattr(current, field) for field in fields)):
                    raise TaskConflict('Inventory condition changes original physical goods or scope')
                now = context.business_time
                if (current.coverage != 'complete' or current.as_of != now
                        or current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                        or current.effective_window.start.clock_ref != now.clock_ref
                        or current.effective_window.end.clock_ref != now.clock_ref
                        or not current.effective_window.contains(now)):
                    return 'unavailable'
                observed = False
                for evidence_ref in current.evidence_refs:
                    evidence = reading.resolve(evidence_ref)
                    if not isinstance(evidence, EvidenceRecord):
                        raise TaskConflict('Inventory state lacks typed source evidence')
                    if evidence.effective_window is not None and (
                            evidence.effective_window.start.clock_ref != now.clock_ref
                            or evidence.effective_window.end.clock_ref != now.clock_ref
                            or not evidence.effective_window.contains(now)):
                        return 'unavailable'
                    observed = observed or evidence.basis_kind == 'observed'
                if not observed:
                    return 'unavailable'
                return 'waiting' if current.status == 'unknown' else 'ready'
            finally:
                reading.recheck()

        return ConditionProfile(action_id, code, '1', frozenset({'dependency_change'}), evaluate)

    return [profile('CONTRACTOR-A12', CommercialMaterialView),
            profile('SUPPLIER-A12', SupplierContinuationInventoryView)]
