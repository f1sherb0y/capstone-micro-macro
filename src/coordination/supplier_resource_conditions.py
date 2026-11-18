"""Recompute Supplier A06 cross-task resource waits from native query history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_execution_objects import (
    SupplierActualResourceView, SupplierExecutionProfileView, SupplierExecutionTaskView,
    SupplierProductionAllocationView, SupplierProductionReservationView,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination.supplier_pending_production_history import read_supplier_pending_production_history


_CODE = 'query_original_resource_production_before_reallocation'


@dataclass(frozen=True)
class SupplierResourceConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_refs: tuple[Reference, ...]
    resource_refs: tuple[Reference, ...]
    original_action_input: dict
    action_input: dict


def supplier_original_resource_profile(read_current, validate_relation):
    """Query commands across tasks before judging the original resource demand.

    The original input is recovered from the waiting task's immutable snapshot.
    A host independently selects current versions of its same resource pools
    and pending commands. Native validation authenticates all resource query,
    reservation and stock effects. Clearing pending commands only permits a
    fresh production decision; the processor still checks capacity, exclusive
    allocation, release/gates, inputs and any explicit failed-command recovery.
    No pending command is inserted into another task's production history.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supplier resource wait requires current sources and independent native query validation')

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'SUPPLIER-A06' or source['role'] != 'Supplier' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'ProductionExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Supplier resource wait changes original task, recipient or pending command dependencies')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, SupplierResourceConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_refs, tuple) or not isinstance(selected.resource_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in (*selected.execution_refs, *selected.resource_refs))
                or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Supplier resource wait requires typed current reading and immutable original input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            refs, pools = selected.execution_refs, selected.resource_refs
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A06'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or len(refs) != len(old_refs) or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                    or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                    or not pools or any(ref.kind != 'ResourcePool' for ref in pools)
                    or len({(ref.kind, ref.id) for ref in pools}) != len(pools)
                    or task_digest(selected.original_action_input) != source['input_sha256']):
                raise TaskConflict('Supplier resource wait substitutes original snapshot/commands or current read point')
            reading.check_method_context(context, 'SUPPLIER-A06')
            now = context.business_time
            original_input, current_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            original_setup, setup = original_input.get('execution_setup', {}), current_input.get('execution_setup', {})
            if original_setup.get('kind') != 'production' or setup.get('kind') != 'production':
                raise TaskConflict('Supplier resource recovery requires the original production branch')
            original_task = reading.resolve(Reference.model_validate(original_input['task_ref']))
            task = reading.resolve(Reference.model_validate(current_input['task_ref']))
            if (not isinstance(original_task, SupplierExecutionTaskView) or not isinstance(task, SupplierExecutionTaskView)
                    or (original_task.ref.kind, original_task.ref.id) != (task.ref.kind, task.ref.id)
                    or task.organization_id != source['organization_id']
                    or any(getattr(original_task, field) != getattr(task, field) for field in (
                        'organization_id', 'mode', 'production_method_ref', 'purchase_order_ref', 'source_rework_batch_refs', 'scope'))
                    or task.scope != context.scope or task.mode == 'purchase'
                    or Reference.model_validate(setup['method_ref']) != task.production_method_ref
                    or original_setup.get('method_ref') != setup.get('method_ref')):
                raise TaskConflict('Supplier resource recovery replaces original task, scope or production method')
            original_profile, profile = reading.resolve(original_task.profile_ref), reading.resolve(task.profile_ref)
            if (not isinstance(original_profile, SupplierExecutionProfileView) or not isinstance(profile, SupplierExecutionProfileView)
                    or original_profile.task_ref != original_task.ref or original_profile.organization_id != task.organization_id
                    or profile.task_ref != task.ref or profile.organization_id != task.organization_id
                    or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                    or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
                    or original_profile.choice not in {'execute', 'rebalance'} or profile.choice not in {'execute', 'rebalance'}):
                raise TaskConflict('Supplier resource recovery lacks current own production authority and original demand')

            def allocations(action_input, expected_task):
                rows = [reading.resolve(Reference.model_validate(ref)) for ref in action_input['available_input_refs']]
                if (not rows or any(not isinstance(row, SupplierProductionAllocationView)
                        or row.task_ref != expected_task.ref or row.organization_id != expected_task.organization_id for row in rows)
                        or len({(row.ref.kind, row.ref.id) for row in rows}) != len(rows)
                        or len({(row.resource_ref.kind, row.resource_ref.id) for row in rows}) != len(rows)):
                    raise TaskConflict('Supplier resource wait substitutes original task allocations or repeats a resource pool')
                return rows

            before_allocations, current_allocations = allocations(original_input, original_task), allocations(current_input, task)
            original_pools = {(row.resource_ref.kind, row.resource_ref.id): reading.resolve(row.resource_ref) for row in before_allocations}
            if ({(ref.kind, ref.id) for ref in pools} != set(original_pools)
                    or {(row.resource_ref.kind, row.resource_ref.id) for row in current_allocations} != set(original_pools)
                    or {(row.ref.kind, row.ref.id) for row in current_allocations}
                        != {(row.ref.kind, row.ref.id) for row in before_allocations}
                    or {(row.resource_ref.kind, row.resource_ref.id) for row in profile.resources} != set(original_pools)
                    or {(row.resource_ref.kind, row.resource_ref.id) for row in original_profile.resources} != set(original_pools)):
                raise TaskConflict('Supplier resource recovery drops or replaces an original physical resource demand/allocation')
            current_pools = {ref.key()[:2]: reading.resolve(ref) for ref in pools}
            if any(not isinstance(row, SupplierActualResourceView) for row in (*original_pools.values(), *current_pools.values())):
                raise TaskConflict('Supplier resource wait requires actual original/current resource pool projections')
            waiting_keys = {ref.key() for ref in old_refs}
            linked = [pool for pool in original_pools.values() if {ref.key() for ref in pool.pending_execution_refs} == waiting_keys]
            if not linked:
                raise TaskConflict('Supplier resource wait is not the exact pending history of an originally selected resource')

            def available(row):
                return (row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                    and row.effective_window.contains(now))

            observed, reservations = {}, {}

            def actual(ref):
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Supplier resource query requires actual observed ledger evidence')
                if row.effective_window is not None and not row.effective_window.contains(now):
                    return False
                observed[ref.key()] = row.model_dump(mode='json')
                return True

            for row in (task, profile, *current_pools.values(), *current_allocations):
                if not available(row):
                    return 'unavailable'
                for ref in row.evidence_refs:
                    if not actual(ref):
                        return 'unavailable'
            for physical, pool in current_pools.items():
                before = original_pools[physical]
                if (before.organization_id != source['organization_id'] or pool.organization_id != before.organization_id
                        or pool.resource_kind != before.resource_kind or pool.scope != before.scope
                        or pool.as_of != now or pool.coverage != 'complete'):
                    raise TaskConflict('Supplier resource query replaces original pool ownership, kind or current complete ledger')
                if pool.pending_execution_refs:
                    return 'waiting'
                if len(set(pool.reservation_refs)) != len(pool.reservation_refs):
                    raise TaskConflict('Supplier resource query repeats a reservation')
                for ref in pool.reservation_refs:
                    reservation = reading.resolve(ref)
                    if (not isinstance(reservation, SupplierProductionReservationView) or reservation.ref != ref
                            or reservation.resource_ref != pool.ref):
                        raise TaskConflict('Supplier resource query substitutes another pool reservation')
                    if not available(reservation):
                        return 'unavailable'
                    for evidence_ref in [*reservation.evidence_refs, reservation.quantity.basis_ref]:
                        if not actual(evidence_ref):
                            return 'unavailable'
                    reservations[ref.key()] = reservation.model_dump(mode='json')
            for allocation in current_allocations:
                pool = current_pools[(allocation.resource_ref.kind, allocation.resource_ref.id)]
                if allocation.resource_ref != pool.ref or allocation.as_of != now:
                    raise TaskConflict('Supplier resource allocation does not use the selected current pool version')
            history = read_supplier_pending_production_history(reading=reading, source=source,
                old_refs=old_refs, refs=refs, now=now, available=available, actual=actual,
                relates_request=lambda request: bool({(item.resource_ref.kind, item.resource_ref.id) for item in request.resources}
                    & {(pool.ref.kind, pool.ref.id) for pool in linked}))
            if isinstance(history, str):
                return history
            originals, currents = history['originals'], history['currents']
            requests, movements = history['requests'], history['movements']
            if validate_relation(source_identity=deepcopy(source), original_action_input=original_input,
                    action_input=current_input, original_task=original_task.model_copy(deep=True), task=task.model_copy(deep=True),
                    original_profile=original_profile.model_copy(deep=True), profile=profile.model_copy(deep=True),
                    original_pools=[row.model_copy(deep=True) for row in original_pools.values()],
                    pools=[row.model_copy(deep=True) for row in current_pools.values()],
                    original_allocations=[row.model_copy(deep=True) for row in before_allocations],
                    allocations=[row.model_copy(deep=True) for row in current_allocations],
                    original_executions=deepcopy(originals), current_executions=deepcopy(currents),
                    requests=deepcopy(list(requests.values())), stock_movements=deepcopy(list(movements.values())),
                    reservations=deepcopy(list(reservations.values())), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Supplier resource wait lacks authentic complete pending-query and resource reservation history')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('SUPPLIER-A06', _CODE, '1', frozenset({'dependency_change'}), evaluate)
