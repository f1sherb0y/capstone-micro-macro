"""Read original QS-A03 appointment/task waits for guarded recovery."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.qs_appointment_actions import QSAppointmentActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId, walk_references
from src.actions.contracts.qs_appointment_objects import QSTaskView, QSTaskDependencyView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_appointment_conditions import (
    QSAppointmentConditionReading, _CODE, _DEPENDENCY_CODE, _CAPACITY_CODE, _CODES,
)
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSAppointmentCurrentSelection:
    request: RoleContractInvocation


class QSAppointmentRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class QSAppointmentRecoveryBindings:
    select_current: Callable
    read_guard: Callable
    validate_relation: Callable
    project_signal: Callable
    prepare: Callable
    revalidate: Callable

    def components(self):
        return tuple(getattr(self, name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate'))

    def __post_init__(self):
        if not all(callable(callback) for callback in self.components()):
            raise ValueError('QS appointment recovery requires actual source selection and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSAppointmentReader:
    """Assemble current A03 sources while retaining the immutable original input."""
    ACTION_ID = 'QS-A03'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSAppointmentActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS appointment reader requires actual formal assembler, snapshot store and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components(); self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current, *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-appointment-reader.v1', 'action_id': self.ACTION_ID,
            'condition_code': _CODE, 'condition_codes': list(_CODES),
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode,
            'macro_version': a.macro_version, 'policy_version': a.policy_version, 'model_version': a.model_version,
            'snapshot_schema': self.snapshots.SCHEMA, 'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A03' or self.assembler.ACTION_ID != self.ACTION_ID or self.assembler.source_mode != 'formal'
                or self.assembler._views.source_mode != 'formal' or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.provider is not self.assembler.provider or self.assembler._views.macro_version != self.assembler.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS appointment reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check(); return deepcopy(self._declared)

    def __call__(self, check):
        self._check(); source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not waited
                or check.condition.condition_code != _CAPACITY_CODE and len(waited) != (2 if check.condition.condition_code == _DEPENDENCY_CODE else 1)
                or waited[0].kind != ('Dependency' if check.condition.condition_code == _DEPENDENCY_CODE
                    else 'ResourceCalendar' if check.condition.condition_code == _CAPACITY_CODE else 'Task')
                or check.condition.condition_code == _DEPENDENCY_CODE and waited[1].kind != 'Task'):
            raise TaskConflict('QS appointment reader replaces original task wait or recipient')
        identity = TaskIdentity(**deepcopy(source)); snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if check.condition.condition_code == _CODE and waited[0].key() not in {ref.key() for ref in original_input.task_refs}:
            raise TaskConflict('QS appointment wait differs from its original task input')
        if check.condition.condition_code == _DEPENDENCY_CODE:
            declared = {ref.key() for ref in original_input.task_refs}
            if waited[1].key() not in declared:
                raise TaskConflict('QS appointment dependency wait differs from its original task input')
        if check.condition.condition_code == _CAPACITY_CODE:
            if waited != [original_input.capacity_ref, *original_input.task_refs] or not original_input.task_refs:
                raise TaskConflict('QS appointment capacity wait changes its original calendar or complete ordered task set')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, QSAppointmentCurrentSelection):
            raise TaskConflict('QS appointment reader requires typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        context = request.context
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or context.business_time != check.signal.business_time
                or context.operation_id == source['request_id'] or current_input.scope != original_input.scope
                or request.execution_path not in {None, registration.strategy}
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('QS appointment reader substitutes original scope, time or visible sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading = prepared.reading
        baseline = deepcopy(reading.evidence())
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS appointment assembly changed its source snapshot or recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)
            for ref in walk_references(current_input):
                reading.resolve(ref)
            if check.condition.condition_code == _DEPENDENCY_CODE:
                current_refs = [ref for ref in current_input.task_refs if ref.key()[:2] == waited[1].key()[:2]]
                if len(current_refs) != 1:
                    raise TaskConflict('QS dependency reader replaces its original waited task')
                for task_ref in (waited[1], current_refs[0]):
                    task = reading.resolve(task_ref)
                    if not isinstance(task, QSTaskView) or task.ref != task_ref:
                        raise TaskConflict('QS dependency reader lacks its exact original/current task')
                    matches = [ref for ref in task.dependency_refs if ref.key()[:2] == waited[0].key()[:2]]
                    if len(matches) != 1 or task_ref == waited[1] and matches[0] != waited[0]:
                        raise TaskConflict('QS dependency reader replaces its original dependency')
                    dependency = reading.resolve(matches[0])
                    if (not isinstance(dependency, QSTaskDependencyView) or dependency.ref != matches[0]
                            or dependency.task_ref != task.ref or dependency.scope != task.scope):
                        raise TaskConflict('QS dependency reader borrows another task dependency')
                    for evidence_ref in dependency.evidence_refs:
                        reading.resolve(evidence_ref)
            result = QSAppointmentConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'), action_input=current_input.model_dump(mode='json'))
            reading.recheck()
            return result
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS appointment reader changed original snapshot or assembled source/context/input')


def build_assembled_qs_appointment_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_appointment_continuation_dispatcher
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS appointment recovery requires actual same-run guards and validators')
    reader = QSAppointmentReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding(); result = prepare(deepcopy(source), signal.model_copy(deep=True)); check_binding(); return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        validated = assembler.registry.get(reader.ACTION_ID).contract.validate_input(deepcopy(preparation.next_input))
        if validated.model_dump(mode='json') != preparation.next_input:
            raise TaskConflict('QS appointment successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)); check_binding(); return result

    dispatcher = build_qs_appointment_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry, original_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({'QS-A03'})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS appointment recovery changed original journal, snapshots or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS appointment recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding(); return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id='QS-A03', role='QS')
