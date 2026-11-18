"""Recompute Supplier A06 inventory waits without promoting stock usability."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_execution_objects import (
    SupplierActualInventoryAllocationView, SupplierActualInventoryView,
    SupplierExecutionProfileView, SupplierExecutionTaskView,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.supplier_pending_production_history import read_supplier_pending_production_history
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction


_CODE = 'query_original_inventory_production_before_reuse'


@dataclass(frozen=True)
class SupplierInventoryConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_refs: tuple[Reference, ...]
    original_action_input: dict
    action_input: dict


def supplier_original_inventory_profile(read_current, validate_relation):
    """Clear original cross-task inventory queries before fresh production judgment.

    Native validation proves the original snapshot's complete pending command
    relation, input allocations, stock movement lineage and current reservation
    ledger. Commands can belong to other tasks. Query completion alone conveys
    no usable stock, release, inspection acceptance or right to consume inputs.
    Ordinary production retains all its independent gates on the successor.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supplier inventory waits require actual sources and independent native history validation')

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'SUPPLIER-A06' or source['role'] != 'Supplier' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'ProductionExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Supplier inventory wait replaces original task/recipient or pending command selection')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, SupplierInventoryConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)
                or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Supplier inventory wait requires typed current reading and original saved input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            refs = selected.execution_refs
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A06'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or len(refs) != len(old_refs) or len({ref.key()[:2] for ref in refs}) != len(refs)
                    or {ref.key()[:2] for ref in refs} != {ref.key()[:2] for ref in old_refs}
                    or task_digest(selected.original_action_input) != source['input_sha256']):
                raise TaskConflict('Supplier inventory wait substitutes original input/commands or current formal read point')
            reading.check_method_context(context, 'SUPPLIER-A06')
            original_input, current_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            before_setup, setup = original_input.get('execution_setup', {}), current_input.get('execution_setup', {})
            if before_setup.get('kind') != 'production' or setup.get('kind') != 'production':
                raise TaskConflict('Supplier inventory recovery requires original production branch')
            original_task = reading.resolve(Reference.model_validate(original_input['task_ref']))
            task = reading.resolve(Reference.model_validate(current_input['task_ref']))
            original_inventory = reading.resolve(Reference.model_validate(original_input['inventory_ref']))
            inventory = reading.resolve(Reference.model_validate(current_input['inventory_ref']))
            if (not isinstance(original_task, SupplierExecutionTaskView) or not isinstance(task, SupplierExecutionTaskView)
                    or original_task.ref.key()[:2] != task.ref.key()[:2] or task.organization_id != source['organization_id']
                    or any(getattr(original_task, field) != getattr(task, field) for field in (
                        'organization_id', 'mode', 'production_method_ref', 'purchase_order_ref', 'source_rework_batch_refs', 'scope'))
                    or task.scope != context.scope or task.mode == 'purchase'
                    or Reference.model_validate(setup['method_ref']) != task.production_method_ref
                    or before_setup.get('method_ref') != setup.get('method_ref')
                    or not isinstance(original_inventory, SupplierActualInventoryView) or not isinstance(inventory, SupplierActualInventoryView)
                    or original_inventory.ref.key()[:2] != inventory.ref.key()[:2]
                    or original_inventory.organization_id != task.organization_id or inventory.organization_id != task.organization_id
                    or original_inventory.scope != inventory.scope
                    or {ref.key() for ref in original_inventory.pending_execution_refs} != {ref.key() for ref in old_refs}
                    or len(original_inventory.pending_execution_refs) != len(old_refs)):
                raise TaskConflict('Supplier inventory recovery replaces original task/method/lineage or exact pending inventory snapshot')
            original_profile, profile = reading.resolve(original_task.profile_ref), reading.resolve(task.profile_ref)
            if (not isinstance(original_profile, SupplierExecutionProfileView) or not isinstance(profile, SupplierExecutionProfileView)
                    or original_profile.task_ref != original_task.ref or original_profile.organization_id != task.organization_id
                    or profile.task_ref != task.ref or profile.organization_id != task.organization_id
                    or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                    or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
                    or original_profile.choice not in {'execute', 'rebalance'} or profile.choice not in {'execute', 'rebalance'}
                    or [(item.batch_ref.key()[:2], item.allocation_ref.key()[:2], item.quantity) for item in original_profile.inputs]
                        != [(item.batch_ref.key()[:2], item.allocation_ref.key()[:2], item.quantity) for item in profile.inputs]):
                raise TaskConflict('Supplier inventory recovery changes original material demand or current production authority')
            now = context.business_time

            def available(row):
                return (row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                    and row.effective_window.contains(now))

            observed, allocations = {}, {}

            def actual(ref):
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Supplier inventory query requires actual observed stock ledger evidence')
                if row.effective_window is not None and not row.effective_window.contains(now):
                    return False
                observed[ref.key()] = row.model_dump(mode='json')
                return True

            for row in (task, profile, inventory):
                if not available(row):
                    return 'unavailable'
                for ref in row.evidence_refs:
                    if not actual(ref):
                        return 'unavailable'
            if inventory.as_of != now or inventory.coverage != 'complete':
                return 'unavailable'
            if inventory.pending_execution_refs:
                return 'waiting'
            if len({position.batch_ref.key()[:2] for position in inventory.positions}) != len(inventory.positions):
                raise TaskConflict('Supplier inventory query repeats a physical material batch')
            events, physical_allocations = set(), set()
            for position in inventory.positions:
                amounts = [position.actual, position.usable, position.reserved]
                if (any(amount.unit != position.actual.unit or decimal_fraction(amount.value) < 0 for amount in amounts)
                        or any(decimal_fraction(amount.value) > decimal_fraction(position.actual.value) for amount in amounts[1:])):
                    raise TaskConflict('Supplier inventory query invents usable/reserved stock above actual physical quantity')
                for amount in amounts:
                    if not actual(amount.basis_ref):
                        return 'unavailable'
                for ref in position.allocation_refs:
                    allocation = reading.resolve(ref)
                    if (not isinstance(allocation, SupplierActualInventoryAllocationView) or allocation.ref != ref
                            or allocation.inventory_ref != inventory.ref or allocation.organization_id != task.organization_id
                            or allocation.batch_ref != position.batch_ref or allocation.as_of != now
                            or allocation.ref.key()[:2] in physical_allocations or allocation.core_event_id in events
                            or allocation.quantity.unit != position.actual.unit or allocation.used_quantity.unit != position.actual.unit
                            or decimal_fraction(allocation.quantity.value) < 0 or decimal_fraction(allocation.used_quantity.value) < 0
                            or decimal_fraction(allocation.used_quantity.value) > decimal_fraction(allocation.quantity.value)):
                        raise TaskConflict('Supplier inventory query changes original reservation ownership, physical batch, quantity or event')
                    if not available(allocation):
                        return 'unavailable'
                    if allocation.status == 'unknown':
                        return 'waiting'
                    physical_allocations.add(allocation.ref.key()[:2]); events.add(allocation.core_event_id)
                    for ref in [*allocation.evidence_refs, allocation.quantity.basis_ref, allocation.used_quantity.basis_ref]:
                        if not actual(ref):
                            return 'unavailable'
                    allocations[allocation.ref.key()] = allocation.model_dump(mode='json')
            # Original snapshot pending refs establish the association; native
            # validation proves why each submitted input or resulting movement
            # affected this inventory, including newly produced batches.
            history = read_supplier_pending_production_history(reading=reading, source=source, old_refs=old_refs,
                refs=refs, now=now, available=available, actual=actual, relates_request=lambda request: True)
            if isinstance(history, str):
                return history
            for request in history['requests'].values():
                for item in request['inputs']:
                    ref = Reference.model_validate(item['allocation_ref'])
                    allocation = reading.resolve(ref)
                    if (not isinstance(allocation, SupplierActualInventoryAllocationView) or allocation.ref != ref
                            or allocation.organization_id != request['organization_id']
                            or allocation.task_ref.model_dump(mode='json') != request['task_ref']
                            or allocation.batch_ref.model_dump(mode='json') != item['batch_ref']):
                        raise TaskConflict('Supplier pending production request replaces its exact input reservation or material lineage')
                    for evidence_ref in allocation.evidence_refs:
                        if not actual(evidence_ref):
                            return 'unavailable'
                    allocations[allocation.ref.key()] = allocation.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=original_input, action_input=current_input,
                    original_task=original_task.model_copy(deep=True), task=task.model_copy(deep=True),
                    original_profile=original_profile.model_copy(deep=True), profile=profile.model_copy(deep=True),
                    original_inventory=original_inventory.model_copy(deep=True), inventory=inventory.model_copy(deep=True),
                    original_executions=deepcopy(history['originals']), current_executions=deepcopy(history['currents']),
                    requests=deepcopy(list(history['requests'].values())), stock_movements=deepcopy(list(history['movements'].values())),
                    allocations=deepcopy(list(allocations.values())), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Supplier inventory wait lacks authentic complete command/stock/lineage/reservation history')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('SUPPLIER-A06', _CODE, '1', frozenset({'dependency_change'}), evaluate)
