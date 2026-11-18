"""Read original Supplier A06 resource demand and cross-task command history."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_execution_reader import (
    SupplierExecutionReader, SupplierExecutionRecoveryBindings, SupplierExecutionRecoverySettings,
)
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_execution_objects import (
    SupplierActualResourceView, SupplierExecutionTaskView, SupplierProductionAllocationView,
    SupplierProductionExecutionView,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.supplier_resource_conditions import SupplierResourceConditionReading, _CODE
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class SupplierResourceCurrentSelection:
    request: RoleContractInvocation
    execution_refs: tuple[Reference, ...]
    resource_refs: tuple[Reference, ...]


class SupplierResourceRecoverySettings(SupplierExecutionRecoverySettings):
    """Explicit versions for original resource waiting input recovery."""
    wait_kind: Literal['resource_query'] = 'resource_query'


@dataclass(frozen=True)
class SupplierResourceRecoveryBindings(SupplierExecutionRecoveryBindings):
    """Actual resource selector, source guard and native/successor validators."""


class SupplierResourceReader(SupplierExecutionReader):
    """Build the current original production demand without executing it.

    Pending commands can belong to other tasks. Read them independently under
    explicit current authorization; never add them to this task's prior history.
    The original demand comes from the same TaskStore invocation snapshot.
    Resource disposition and complete native effects remain condition checks,
    and ordinary production gates remain processor checks on the successor.
    """
    CONDITION_CODE = _CODE
    SELECTION_TYPE = SupplierResourceCurrentSelection
    SCHEMA_VERSION = 'supplier-resource-reader.v1'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(snapshots, InvocationSnapshotStore)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('Supplier resource reader requires original same-run invocation snapshots')
        self.snapshots = snapshots
        super().__init__(assembler=assembler, select_current=select_current)

    def _components(self):
        return (*super()._components(), self.snapshots, self.snapshots.store)

    def _configuration(self):
        result = super()._configuration()
        result.pop('task_history', None)
        return {**result, 'schema_version': self.SCHEMA_VERSION, 'condition_codes': [self.CONDITION_CODE],
            'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            **{name: module_factory_descriptor(getattr(type(self), name), name) for name in (
                '_dependency_refs', '_valid_dependencies', '_validate_dependencies', '_condition_reading')}}

    def _dependency_refs(self, selected):
        return selected.resource_refs

    def _valid_dependencies(self, refs):
        return bool(refs) and all(ref.kind == 'ResourcePool' for ref in refs)

    def _validate_dependencies(self, prepared, refs, source, original_input):
        reading = prepared.reading
        allocations = [reading.resolve(ref) for ref in prepared.action_input.available_input_refs]
        if (any(not isinstance(row, SupplierProductionAllocationView) for row in allocations)
                or {row.resource_ref.key() for row in allocations} != {ref.key() for ref in refs}):
            raise TaskConflict('Supplier resource selection differs from the actual current original allocations')
        for ref in refs:
            row = reading.resolve(ref)
            if (not isinstance(row, SupplierActualResourceView) or row.ref.key() != ref.key()
                    or row.organization_id != source['organization_id']):
                raise TaskConflict('Supplier resource selection substitutes another physical pool or owner')

    def _condition_reading(self, prepared, refs, dependencies, snapshot):
        return SupplierResourceConditionReading(prepared.context, prepared.reading, refs, dependencies,
            deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'))

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Supplier' or source['purpose'] != 'action'
                or check.condition.condition_code != self.CONDITION_CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'ProductionExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Supplier resource reader changes original wait, recipient or pending commands')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if original_input.execution_setup.kind != 'production':
            raise TaskConflict('Supplier resource wait is not an original saved production input')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, self.SELECTION_TYPE):
            raise TaskConflict('Supplier input reader requires its original typed current selection')
        dependency_refs = self._dependency_refs(selected)
        if (not isinstance(selected.execution_refs, tuple) or not isinstance(dependency_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in (*selected.execution_refs, *dependency_refs))):
            raise TaskConflict('Supplier resource reader requires typed current request and explicit command/pool versions')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        refs = tuple(ref.model_copy(deep=True) for ref in selected.execution_refs)
        resources = tuple(ref.model_copy(deep=True) for ref in dependency_refs)
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or len(refs) != len(old_refs) or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                or not self._valid_dependencies(resources)
                or len({(ref.kind, ref.id) for ref in resources}) != len(resources)
                or not {ref.key() for ref in (*old_refs, *refs, *resources)} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Supplier resource reader requires original scope, visible commands/pools and fresh formal context')
        action_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (action_input.execution_setup.kind != 'production'
                or (action_input.task_ref.kind, action_input.task_ref.id) != (original_input.task_ref.kind, original_input.task_ref.id)
                or action_input.execution_setup.method_ref != original_input.execution_setup.method_ref):
            raise TaskConflict('Supplier resource recovery replaces original task/method or changes production branch')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Supplier resource assembly changes original snapshot or authorized recipient')
            task = reading.resolve(prepared.action_input.task_ref)
            if (not isinstance(task, SupplierExecutionTaskView) or task.history_coverage != 'complete'
                    or task.as_of != context.business_time
                    or len({(ref.kind, ref.id) for ref in task.prior_execution_refs}) != len(task.prior_execution_refs)
                    or {ref.key() for ref in task.prior_execution_refs}
                        != {ref.key() for ref in prepared.action_input.prior_execution_refs}):
                raise TaskConflict('Supplier resource recovery must retain only the complete current original task history')
            self._validate_dependencies(prepared, resources, source, original_input)
            current_refs = {(ref.kind, ref.id): ref for ref in refs}
            for old_ref in old_refs:
                ref = current_refs[(old_ref.kind, old_ref.id)]
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if (not isinstance(original, SupplierProductionExecutionView) or not isinstance(current, SupplierProductionExecutionView)
                        or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                        or current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'organization_id', 'task_ref', 'run_id', 'operation_id', 'business_key', 'request_ref', 'request_sha256', 'scope'))
                        or original.status != 'submitted_unknown' and current.status != original.status
                        or original.core_event_id is not None and current.core_event_id != original.core_event_id
                        or original.recorded_at is not None and current.recorded_at != original.recorded_at
                        or not {(item.kind, item.id) for item in original.movement_refs}
                            <= {(item.kind, item.id) for item in current.movement_refs}):
                    raise TaskConflict('Supplier cross-task resource reader replaces an original command/request or known effects')
            return self._condition_reading(prepared, refs, resources, snapshot)
        finally:
            prepared.reading.recheck()
            self._check()
            current_evidence = {Reference.model_validate(row['ref']).key(): row['projection']
                for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot
                    or any(current_evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Supplier resource reader changed original snapshots or assembled input/context/source reading')


def build_assembled_supplier_resource_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one original source/authority/inbox/journal guard through recovery."""
    from integration.task_continuation import build_supplier_resource_continuation_dispatcher

    return _build_assembled_supplier_input_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=SupplierResourceReader, dispatcher_factory=build_supplier_resource_continuation_dispatcher)


def _build_assembled_supplier_input_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader_type, dispatcher_factory):
    """Bind one typed original input reader to its original guarded journal."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Supplier resource recovery requires actual same-run source/authority/journal guard and validators')
    reader = reader_type(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    action_id = reader.ACTION_ID
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        validated = assembler.registry.get(action_id).contract.validate_input(deepcopy(preparation.next_input))
        if validated.model_dump(mode='json') != preparation.next_input:
            raise TaskConflict('Supplier resource successor substitutes the current closed production input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = dispatcher_factory(inbox=inbox, store=store,
        read_current=reader, validate_relation=validate_relation, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    original_revalidate = dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())
                or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({action_id})):
            raise TaskConflict('Supplier resource recovery changed original snapshots/journal/recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Supplier resource recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id=action_id, role='Supplier')
