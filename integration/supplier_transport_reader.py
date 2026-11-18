"""Read actual Supplier A08 shipment history for protected original transport waits."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_logistics_actions import SupplierLogisticsActionAssembler
from src.actions.contracts.common import Reference, ResumeCondition, StrictRecord, TextId
from src.actions.contracts.supplier_logistics_objects import SupplierLogisticsOrderView, SupplierShipmentView
from src.coordination.continuations import ConditionCheck
from src.coordination.supplier_transport_conditions import (
    SupplierTransportConditionReading, check_supplier_query_selection, supplier_original_transport_profile,
)
from src.actions.roles.supplier_transport_history import validate_arrival_traversals
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class SupplierTransportCurrentSelection:
    request: RoleContractInvocation
    shipment_refs: tuple[Reference, ...]


class SupplierTransportRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class SupplierTransportRecoveryBindings:
    select_current: Callable
    read_guard: Callable
    validate_relation: Callable
    project_signal: Callable
    prepare: Callable
    revalidate: Callable

    def components(self):
        return (self.select_current, self.read_guard, self.validate_relation,
            self.project_signal, self.prepare, self.revalidate)

    def __post_init__(self):
        if not all(callable(callback) for callback in self.components()):
            raise ValueError('Supplier transport recovery requires actual selection, guard and native/successor validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class SupplierTransportReader:
    """Assemble the full current order history and query original shipment versions.

    Reconciliation preserves the original command, plan and physical cargo.
    The application supplies a separately authorized current reconcile profile
    under its source/authority/inbox/journal guard. Reading runs no processor,
    method, model or dispatch, and establishes no arrival, title or usable stock.
    """
    ACTION_ID = 'SUPPLIER-A08'
    CONDITION_CODE = 'continue_original_transport_operation'

    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, SupplierLogisticsActionAssembler) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Supplier transport reader requires original formal A08 assembler and actual current selector')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.view_provider, assembler._views,
            assembler._views.schemas, assembler.methods, self.select_current,
            supplier_original_transport_profile, validate_arrival_traversals, *assembler.decision_strategies)

    def _configuration(self):
        return {'schema_version': 'supplier-transport-reader.v1', 'action_id': self.ACTION_ID,
            'condition_code': self.CONDITION_CODE, 'run_id': self.assembler.organizations.run_id,
            'source_mode': self.assembler.source_mode, 'macro_version': self.assembler._views.macro_version,
            'policy_version': self.assembler.policy_version, 'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'transport_condition': module_factory_descriptor(supplier_original_transport_profile, 'transport_condition'),
            'arrival_history': module_factory_descriptor(validate_arrival_traversals, 'arrival_history'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or self.ACTION_ID != 'SUPPLIER-A08' or self.CONDITION_CODE != 'continue_original_transport_operation'
                or self.assembler.source_mode != 'formal' or self.assembler._views.source_mode != 'formal'
                or self.assembler._views.organizations is not self.assembler.organizations
                or self._configuration() != self._declared):
            raise TaskConflict('Supplier transport reader changed original sources, model bindings or declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Supplier' or source['purpose'] != 'action'
                or check.condition.condition_code != self.CONDITION_CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'Shipment' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Supplier transport reader changes original condition, recipient or shipment dependencies')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, SupplierTransportCurrentSelection) or not isinstance(selected.shipment_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.shipment_refs)):
            raise TaskConflict('Supplier transport reader requires typed current request and explicit shipment versions')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        refs = tuple(ref.model_copy(deep=True) for ref in selected.shipment_refs)
        registration = self.assembler.registry.get(self.ACTION_ID)
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or len(refs) != len(old_refs) or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                or not {ref.key() for ref in (*old_refs, *refs)} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Supplier transport reader requires visible original/current shipments and fresh formal context')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            if task_digest(baseline) != prepared.reading_sha256 or prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Supplier transport assembly changed original source snapshot or authorized recipient')
            reading = prepared.reading
            result = SupplierTransportConditionReading(prepared.context, reading, refs,
                prepared.action_input.logistics_profile_ref.model_copy(deep=True))
            profile = check_supplier_query_selection(result)
            order = reading.resolve(prepared.action_input.order_ref)
            if (not isinstance(order, SupplierLogisticsOrderView) or order.ref.key() != prepared.action_input.order_ref.key()
                    or order.supplier_id != source['organization_id'] or order.ref.key() != profile.order_ref.key()
                    or order.coverage != 'complete' or order.as_of != context.business_time
                    or len({ref.key() for ref in prepared.action_input.shipment_refs}) != len(prepared.action_input.shipment_refs)
                    or {ref.key() for ref in prepared.action_input.shipment_refs} != {ref.key() for ref in order.shipment_refs}
                    or not {ref.key() for ref in refs} <= {ref.key() for ref in order.shipment_refs}):
                raise TaskConflict('Supplier transport recovery must retain the actual complete current order shipment history')
            originals = {(ref.kind, ref.id): ref for ref in old_refs}
            for ref in refs:
                old_ref = originals[(ref.kind, ref.id)]
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if (not isinstance(original, SupplierShipmentView) or not isinstance(current, SupplierShipmentView)
                        or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                        or current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                        or current.order_ref.key() != order.ref.key()
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'order_ref', 'organization_id', 'run_id', 'operation_id', 'command_id', 'business_key',
                            'physical_batch_key', 'slice_refs', 'plan', 'request_sha256', 'scope'))
                        or task_digest(current.plan.model_dump(mode='json')) != current.request_sha256
                        or original.status in {'received', 'rejected', 'failed'} and current.status != original.status
                        or original.core_event_id is not None and current.core_event_id != original.core_event_id
                        or original.dispatched_at is not None and current.dispatched_at != original.dispatched_at
                        or not {(item.kind, item.id) for item in original.traversal_refs}
                            <= {(item.kind, item.id) for item in current.traversal_refs}):
                    raise TaskConflict('Supplier transport reader changes original command, cargo, plan or known transport history')
            return result
        finally:
            prepared.reading.recheck()
            self._check()
            # Authorized original-history reads extend the assembler's ledger.
            # Compare by reference because the evidence ledger is sorted.
            current_evidence = {Reference.model_validate(row['ref']).key(): row['projection']
                for row in prepared.reading.evidence()}
            if (any(current_evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Supplier transport reader changed assembled input, context or original source readings')


def build_assembled_supplier_transport_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold the original source/authority/inbox/journal guard once through wakeup."""
    from integration.task_continuation import build_supplier_transport_continuation_dispatcher
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge

    reader = SupplierTransportReader(assembler=assembler, select_current=select_current)
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Supplier transport recovery requires actual same-run source/authority/journal guard and validators')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == reader.CONDITION_CODE]
        if len(conditions) != 1:
            raise TaskConflict('Supplier transport recovery requires its original emitted wait')
        selected = reader(ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True)))
        try:
            next_input = assembler.registry.get(reader.ACTION_ID).contract.validate_input(deepcopy(preparation.next_input))
            if (next_input.model_dump(mode='json') != preparation.next_input
                    or preparation.next_context != selected.context.model_dump(mode='json')
                    or next_input.logistics_profile_ref.key() != selected.logistics_profile_ref.key()):
                raise TaskConflict('Supplier transport successor substitutes current closed input, context or reconcile profile')
            selected.reading.recheck()
            result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
            check_binding()
            return result
        finally:
            selected.reading.recheck()

    dispatcher = build_supplier_transport_continuation_dispatcher(inbox=inbox, store=store,
        read_current=reader, validate_relation=validate_relation, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    original_revalidate = dispatcher.revalidate

    def check_binding():
        reader._check()
        if (any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())
                or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({'SUPPLIER-A08'})):
            raise TaskConflict('Supplier transport recovery changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Supplier transport recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='SUPPLIER-A08', role='Supplier')
