"""Resolve original Supplier A06 production waits without replaying inputs."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_execution_objects import (
    SupplierExecutionProfileView, SupplierExecutionTaskView, SupplierProductionExecutionView,
    SupplierProductionRequestView, SupplierStockMovementView, validate_supplier_reconciliation_task,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction


_CODES = ('query_original_production_execution_before_replay', 'continue_original_production_operation')


@dataclass(frozen=True)
class SupplierExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_refs: tuple[Reference, ...]
    task_ref: Reference
    execution_profile_ref: Reference
    action_input: dict | None = None


def check_supplier_production_query_selection(selected):
    """Require a separately authorized current reconciliation choice."""
    if (not isinstance(selected, SupplierExecutionConditionReading)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.execution_refs, tuple)
            or any(not isinstance(ref, Reference) for ref in selected.execution_refs)
            or not isinstance(selected.task_ref, Reference) or not isinstance(selected.execution_profile_ref, Reference)):
        raise TaskConflict('Supplier production wait requires typed current task/profile/execution sources')
    context, reading = selected.context, selected.reading
    reading.check_method_context(context, 'SUPPLIER-A06')
    task, profile = reading.resolve(selected.task_ref), reading.resolve(selected.execution_profile_ref)
    now = context.business_time
    if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A06'
            or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
            or not isinstance(task, SupplierExecutionTaskView) or task.ref != selected.task_ref
            or not isinstance(profile, SupplierExecutionProfileView) or profile.ref != selected.execution_profile_ref
            or task.organization_id != reading.organization_id or task.profile_ref != profile.ref
            or profile.organization_id != reading.organization_id or profile.task_ref != task.ref
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or profile.choice != 'reconcile_execution'
            or profile.available_at.clock_ref != now.clock_ref or profile.available_at.offset > now.offset
            or not profile.effective_window.contains(now)):
        raise TaskConflict('Supplier production continuation requires current own reconciliation authority')
    return task, profile


def supplier_original_execution_profiles(read_current, validate_relation):
    """Register original same-task production query waits, never retries.

    Native validation authenticates the original waiting invocation, complete
    query history and actual stock movements or absence of effects. Unknown
    commands remain waiting. A known failure only permits reconciliation;
    new production still requires separate recovery and original input gates.
    Resource-pool and inventory waits are separate conditions because their
    pending executions may belong to other tasks.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supplier production waits require actual current reader and native history validator')

    def profile_for(code):
        def evaluate(check):
            source, old_refs = check.source['identity'], check.condition.object_refs
            if (source['action_id'] != 'SUPPLIER-A06' or source['role'] != 'Supplier' or source['purpose'] != 'action'
                    or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                    or not old_refs or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)
                    or any(ref.kind != 'ProductionExecution' for ref in old_refs)):
                raise TaskConflict('Supplier production wait changes original task/recipient or execution dependencies')
            selected = read_current(deepcopy(check))
            # Selection checks also resolve authorized task/profile projections;
            # keep their source recheck inside the same finally as history reads.
            if not isinstance(selected, SupplierExecutionConditionReading) or not isinstance(selected.reading, ActionReadView):
                raise TaskConflict('Supplier production wait requires a typed authorized reading')
            reading = selected.reading
            try:
                task, profile = check_supplier_production_query_selection(selected)
                context, refs = selected.context.model_copy(deep=True), selected.execution_refs
                if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                        or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                        or len(refs) != len(old_refs) or len(set(refs)) != len(refs)
                        or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                        or not {ref.key() for ref in refs} <= {ref.key() for ref in task.prior_execution_refs}):
                    raise TaskConflict('Supplier production wait substitutes current read point or original command identities')
                now = context.business_time
                current_refs = {(ref.kind, ref.id): ref for ref in refs}
                originals, currents, requests, movements, observed = [], [], {}, {}, {}
                operations, businesses, events, physical_movements = set(), set(), set(), set()

                def available(row):
                    return (row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                        and row.effective_window.contains(now))

                def actual(ref):
                    row = reading.resolve(ref)
                    if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                        raise TaskConflict('Supplier production query requires actual observed evidence')
                    if row.effective_window is not None and not row.effective_window.contains(now):
                        return False
                    observed[ref.key()] = row.model_dump(mode='json')
                    return True

                for row in (task, profile):
                    for ref in row.evidence_refs:
                        if not actual(ref):
                            return 'unavailable'
                for old_ref in old_refs:
                    ref = current_refs[(old_ref.kind, old_ref.id)]
                    original, current = reading.resolve(old_ref), reading.resolve(ref)
                    if (not isinstance(original, SupplierProductionExecutionView) or not isinstance(current, SupplierProductionExecutionView)
                            or original.ref != old_ref or current.ref != ref
                            or current.run_id != source['run_id'] or current.organization_id != source['organization_id']
                            or (current.task_ref.kind, current.task_ref.id) != (task.ref.kind, task.ref.id)
                            or any(getattr(original, field) != getattr(current, field) for field in (
                                'organization_id', 'task_ref', 'run_id', 'operation_id', 'business_key', 'request_ref', 'request_sha256', 'scope'))
                            or current.operation_id in operations or current.business_key in businesses
                            or original.status != 'submitted_unknown' and current.status != original.status
                            or original.status == 'recorded' and (
                                original.core_event_id != current.core_event_id or original.recorded_at != current.recorded_at
                                or not {(item.kind, item.id) for item in original.movement_refs}
                                    <= {(item.kind, item.id) for item in current.movement_refs})):
                        raise TaskConflict('Supplier production query replaces original command/request/task or known effects')
                    operations.add(current.operation_id); businesses.add(current.business_key)
                    original_task = reading.resolve(current.task_ref)
                    validate_supplier_reconciliation_task(original_task, task, current,
                        run_id=context.run_id, organization_id=source['organization_id'])
                    if not available(current):
                        return 'unavailable'
                    if current.status == 'submitted_unknown' or current.query_status in {'unknown', 'not_queried'}:
                        return 'waiting'
                    request = reading.resolve(current.request_ref)
                    if (not isinstance(request, SupplierProductionRequestView) or request.ref != current.request_ref
                            or any(getattr(request, field) != getattr(current, field) for field in (
                                'organization_id', 'task_ref', 'run_id', 'operation_id', 'business_key', 'scope'))
                            or content_digest(request) != current.request_sha256
                            or len({item.allocation_ref.key() for item in request.inputs}) != len(request.inputs)
                            or len({item.resource_ref.key() for item in request.resources}) != len(request.resources)):
                        raise TaskConflict('Supplier production query changes exact submitted input/resource request')
                    requests[request.ref.key()] = request.model_dump(mode='json')
                    for evidence_ref in [*current.evidence_refs, *request.evidence_refs]:
                        if not actual(evidence_ref):
                            return 'unavailable'
                    if current.status == 'recorded':
                        if (current.query_status != 'present' or current.core_event_id is None or current.core_event_id in events
                                or current.recorded_at is None or current.recorded_at.clock_ref != now.clock_ref
                                or current.recorded_at.offset > current.available_at.offset
                                or not current.movement_refs or len(set(current.movement_refs)) != len(current.movement_refs)):
                            raise TaskConflict('Recorded production lacks distinct actual event, timing or stock movement history')
                        events.add(current.core_event_id)
                        allocations = {item.allocation_ref.key() for item in request.inputs}
                        for movement_ref in current.movement_refs:
                            movement = reading.resolve(movement_ref)
                            if (not isinstance(movement, SupplierStockMovementView) or movement.ref != movement_ref
                                    or movement.organization_id != current.organization_id or movement.execution_ref != current.ref
                                    or movement.core_event_id != current.core_event_id
                                    or movement.physical_movement_key in physical_movements
                                    or decimal_fraction(movement.quantity.value) <= 0 or not movement.lineage_batch_refs
                                    or not {item.key() for item in movement.source_allocation_refs} <= allocations):
                                raise TaskConflict('Production stock history replaces original inputs/lineage or duplicates a physical movement')
                            if not available(movement):
                                return 'unavailable'
                            physical_movements.add(movement.physical_movement_key)
                            for evidence_ref in [*movement.evidence_refs, movement.quantity.basis_ref]:
                                if not actual(evidence_ref):
                                    return 'unavailable'
                            movements[movement.ref.key()] = movement.model_dump(mode='json')
                    elif current.core_event_id is not None or current.movement_refs:
                        raise TaskConflict('Rejected or failed production cannot imply recorded stock effects')
                    originals.append(original.model_dump(mode='json'))
                    currents.append(current.model_dump(mode='json'))
                if validate_relation(source_identity=deepcopy(source), task=task.model_copy(deep=True),
                        profile=profile.model_copy(deep=True), original_executions=deepcopy(originals),
                        current_executions=deepcopy(currents), requests=deepcopy(list(requests.values())),
                        stock_movements=deepcopy(list(movements.values())), evidence=deepcopy(list(observed.values())),
                        context=context.model_copy(deep=True), reading=reading) is not True:
                    raise TaskConflict('Supplier production wait lacks authentic complete query and original stock/absence evidence')
                return 'ready'
            finally:
                reading.recheck()

        return ConditionProfile('SUPPLIER-A06', code, '1', frozenset({'dependency_change'}), evaluate)

    return tuple(profile_for(code) for code in _CODES)
