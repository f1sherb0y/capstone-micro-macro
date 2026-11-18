"""Read actual Supplier A06 production commands for guarded reconciliation."""
from copy import deepcopy
from dataclasses import dataclass

from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_execution_actions import SupplierExecutionActionAssembler
from integration.supplier_transport_reader import SupplierTransportRecoveryBindings, SupplierTransportRecoverySettings
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_execution_objects import (
    SupplierExecutionTaskView, SupplierProductionExecutionView, validate_supplier_reconciliation_task,
)
from src.coordination.supplier_execution_conditions import (
    SupplierExecutionConditionReading, _CODES, check_supplier_production_query_selection,
)
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class SupplierExecutionCurrentSelection:
    request: RoleContractInvocation
    execution_refs: tuple[Reference, ...]


class SupplierExecutionRecoverySettings(SupplierTransportRecoverySettings):
    """Explicit A06 versions; the formal application selects the original action."""


@dataclass(frozen=True)
class SupplierExecutionRecoveryBindings(SupplierTransportRecoveryBindings):
    """Actual A06 selector, shared guard and native/successor validation callbacks."""


class SupplierExecutionReader:
    """Assemble only reconciliation, retaining the full current task history.

    Historical commands keep their exact saved task and request references.
    An explicitly supplied current version of that physical task can select
    a current reconciliation profile, with method, purchase/rework lineage,
    scope and prior commands preserved. Reading performs no production,
    consumption, stock posting, method calculation or model call.
    """
    ACTION_ID = 'SUPPLIER-A06'

    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, SupplierExecutionActionAssembler) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Supplier production reader requires original formal A06 assembler and current selector')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.view_provider, assembler._views,
            assembler._views.schemas, assembler.methods, self.select_current, *assembler.decision_strategies)

    def _configuration(self):
        return {'schema_version': 'supplier-execution-reader.v1', 'action_id': self.ACTION_ID,
            'condition_codes': list(_CODES), 'run_id': self.assembler.organizations.run_id,
            'source_mode': self.assembler.source_mode, 'macro_version': self.assembler._views.macro_version,
            'policy_version': self.assembler.policy_version, 'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current'),
            'task_history': module_factory_descriptor(validate_supplier_reconciliation_task, 'task_history')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or self.ACTION_ID != 'SUPPLIER-A06' or self.assembler.source_mode != 'formal'
                or self.assembler._views.source_mode != 'formal'
                or self.assembler._views.organizations is not self.assembler.organizations
                or self._configuration() != self._declared):
            raise TaskConflict('Supplier production reader changed original sources, model bindings or declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Supplier' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'ProductionExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Supplier production reader changes original wait, recipient or execution dependencies')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, SupplierExecutionCurrentSelection) or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
            raise TaskConflict('Supplier production reader requires typed current request and explicit execution versions')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        refs = tuple(ref.model_copy(deep=True) for ref in selected.execution_refs)
        registration = self.assembler.registry.get(self.ACTION_ID)
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or len(refs) != len(old_refs) or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                or not {ref.key() for ref in (*old_refs, *refs)} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Supplier production reader requires visible original/current commands and fresh formal context')
        action_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (action_input.execution_setup.kind != 'reconciliation'
                or [ref.key() for ref in action_input.execution_setup.execution_refs] != [ref.key() for ref in refs]):
            raise TaskConflict('Supplier production recovery must reconcile selected commands without replaying production inputs')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            if task_digest(baseline) != prepared.reading_sha256 or prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Supplier production assembly changes original snapshot or authorized recipient')
            result = SupplierExecutionConditionReading(prepared.context, prepared.reading, refs,
                prepared.action_input.task_ref.model_copy(deep=True),
                prepared.reading.resolve(prepared.action_input.task_ref).profile_ref.model_copy(deep=True),
                prepared.action_input.model_dump(mode='json'))
            task, _ = check_supplier_production_query_selection(result)
            history = prepared.action_input.prior_execution_refs
            if (task.history_coverage != 'complete' or task.as_of != context.business_time
                    or len({(ref.kind, ref.id) for ref in task.prior_execution_refs}) != len(task.prior_execution_refs)
                    or {ref.key() for ref in history} != {ref.key() for ref in task.prior_execution_refs}
                    or not {ref.key() for ref in refs} <= {ref.key() for ref in history}):
                raise TaskConflict('Supplier production recovery must retain complete current task command history')
            current_refs = {(ref.kind, ref.id): ref for ref in refs}
            for old_ref in old_refs:
                original = prepared.reading.resolve(old_ref)
                ref = current_refs[(old_ref.kind, old_ref.id)]
                current = prepared.reading.resolve(ref)
                if (not isinstance(original, SupplierProductionExecutionView) or not isinstance(current, SupplierProductionExecutionView)
                        or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'organization_id', 'task_ref', 'run_id', 'operation_id', 'business_key', 'request_ref', 'request_sha256', 'scope'))
                        or original.status != 'submitted_unknown' and current.status != original.status
                        or original.core_event_id is not None and current.core_event_id != original.core_event_id
                        or original.recorded_at is not None and current.recorded_at != original.recorded_at
                        or not {(item.kind, item.id) for item in original.movement_refs}
                            <= {(item.kind, item.id) for item in current.movement_refs}):
                    raise TaskConflict('Supplier production reader replaces original command or its saved task version')
                original_task = prepared.reading.resolve(current.task_ref)
                validate_supplier_reconciliation_task(original_task, task, current,
                    run_id=context.run_id, organization_id=source['organization_id'])
            return result
        finally:
            prepared.reading.recheck()
            self._check()
            current_evidence = {Reference.model_validate(row['ref']).key(): row['projection']
                for row in prepared.reading.evidence()}
            if (any(current_evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Supplier production reader changed assembled input, context or original source readings')


def build_assembled_supplier_execution_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold the original source/authority/inbox/journal guard once through recovery."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_supplier_execution_continuation_dispatcher

    reader = SupplierExecutionReader(assembler=assembler, select_current=select_current)
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Supplier production recovery requires actual same-run source/authority/journal guard and validators')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        validated = assembler.registry.get('SUPPLIER-A06').contract.validate_input(deepcopy(preparation.next_input))
        if validated.model_dump(mode='json') != preparation.next_input:
            raise TaskConflict('Supplier production successor changes its current closed action input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_supplier_execution_continuation_dispatcher(inbox=inbox, store=store,
        read_current=reader, validate_relation=validate_relation, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    original_prepare, original_revalidate = dispatcher.prepare, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())
                or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not original_prepare
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({'SUPPLIER-A06'})):
            raise TaskConflict('Supplier production recovery changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Supplier production recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='SUPPLIER-A06', role='Supplier')
