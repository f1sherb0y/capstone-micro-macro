"""Authenticate preserved pending production commands for cross-task waits."""
from src.actions.contracts.supplier_execution_objects import SupplierProductionExecutionView, SupplierProductionRequestView, SupplierStockMovementView
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction


def read_supplier_pending_production_history(*, reading, source, old_refs, refs, now, available, actual, relates_request):
    """Return preserved query history, or waiting/unavailable; produce no effects.

    The caller authenticates current authorization, original snapshot and the
    resource/inventory relation. Its finally block rechecks the entire reading.
    Native validation still proves complete effects and query provenance.
    """
    current_refs = {ref.key()[:2]: ref for ref in refs}
    originals, currents, requests, movements = [], [], {}, {}
    operations, businesses, events, physical_movements = set(), set(), set(), set()
    for old_ref in old_refs:
        ref = current_refs[old_ref.key()[:2]]
        original, current = reading.resolve(old_ref), reading.resolve(ref)
        if (not isinstance(original, SupplierProductionExecutionView) or not isinstance(current, SupplierProductionExecutionView)
                or original.ref != old_ref or current.ref != ref or current.organization_id != source['organization_id']
                or current.run_id != source['run_id']
                or any(getattr(original, field) != getattr(current, field) for field in (
                    'organization_id', 'task_ref', 'run_id', 'operation_id', 'business_key', 'request_ref', 'request_sha256', 'scope'))
                or current.operation_id in operations or current.business_key in businesses
                or original.status != 'submitted_unknown' and current.status != original.status
                or original.core_event_id is not None and original.core_event_id != current.core_event_id
                or original.recorded_at is not None and original.recorded_at != current.recorded_at
                or not {(item.kind, item.id) for item in original.movement_refs}
                    <= {(item.kind, item.id) for item in current.movement_refs}):
            raise TaskConflict('Supplier resource query replaces original command/request identity or known effects')
        operations.add(current.operation_id); businesses.add(current.business_key)
        if not available(current):
            return 'unavailable'
        if current.status == 'submitted_unknown' or current.query_status in {'unknown', 'not_queried'}:
            return 'waiting'
        request = reading.resolve(current.request_ref)
        if (not isinstance(request, SupplierProductionRequestView) or request.ref != current.request_ref
                or task_digest(request.model_dump(mode='json')) != current.request_sha256
                or any(getattr(request, field) != getattr(current, field) for field in (
                    'organization_id', 'task_ref', 'run_id', 'operation_id', 'business_key', 'scope'))
                or relates_request(request) is not True):
            raise TaskConflict('Supplier pending command is unrelated to the original pool or exact submitted request')
        for evidence_ref in [*current.evidence_refs, *request.evidence_refs]:
            if not actual(evidence_ref):
                return 'unavailable'
        if current.status == 'recorded':
            if (current.query_status != 'present' or current.core_event_id is None or current.core_event_id in events
                    or current.recorded_at is None or current.recorded_at.clock_ref != now.clock_ref
                    or current.recorded_at.offset > current.available_at.offset or not current.movement_refs
                    or len(set(current.movement_refs)) != len(current.movement_refs)):
                raise TaskConflict('Recorded cross-task production lacks actual event, timing or stock movement history')
            events.add(current.core_event_id)
            for movement_ref in current.movement_refs:
                movement = reading.resolve(movement_ref)
                if (not isinstance(movement, SupplierStockMovementView) or movement.ref != movement_ref
                        or movement.organization_id != current.organization_id or movement.execution_ref != current.ref
                        or movement.core_event_id != current.core_event_id
                        or movement.physical_movement_key in physical_movements
                        or decimal_fraction(movement.quantity.value) <= 0 or not movement.lineage_batch_refs
                        or not {item.key() for item in movement.source_allocation_refs}
                            <= {item.allocation_ref.key() for item in request.inputs}):
                    raise TaskConflict('Cross-task production movement replaces its original command or physical quantity')
                if not available(movement):
                    return 'unavailable'
                physical_movements.add(movement.physical_movement_key)
                for evidence_ref in [*movement.evidence_refs, movement.quantity.basis_ref]:
                    if not actual(evidence_ref):
                        return 'unavailable'
                movements[movement.ref.key()] = movement.model_dump(mode='json')
        elif current.core_event_id is not None or current.movement_refs:
            raise TaskConflict('Rejected or failed cross-task production cannot imply recorded stock')
        originals.append(original.model_dump(mode='json')); currents.append(current.model_dump(mode='json'))
        requests[request.ref.key()] = request.model_dump(mode='json')
    return {'originals': originals, 'currents': currents, 'requests': requests, 'movements': movements}
