"""Read original Government A10 inspection task snapshots for guarded recovery."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.government_inspection_actions import GovernmentInspectionActionAssembler
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.government_inspection_objects import (
    GovInspectionTaskView, GovInspectionView, GovInspectionRuleView,
    GovInspectionObservationView, GovInspectionIssueView,
)
from src.coordination.government_inspection_conditions import (
    GovernmentInspectionTaskConditionReading, _CODE, _CODES, _WINDOW_CODE, _DEPENDENCY_CODE, _HANDOFF_CODE,
    _CAPACITY_CODE, _WAIT_KINDS,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class GovernmentInspectionCurrentSelection:
    request: RoleContractInvocation


class GovernmentInspectionRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class GovernmentInspectionRecoveryBindings:
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
            raise ValueError('Government inspection recovery requires actual source selection, guard and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class GovernmentInspectionReader:
    """Use the original journal and actual A10 assembler, without running A10.

    The selector supplies a separately authorized current invocation. All old
    input references remain explicitly visible; current task-bound projections
    preserve original inspection identities and already received observations.
    Native validation in the condition authenticates the task transition and
    current history. This reader creates no observation, permit or measure.
    """
    ACTION_ID = 'GOV-A10'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentInspectionActionAssembler
    READER_SCHEMA = 'government-inspection-reader.v1'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, self.ASSEMBLER_TYPE) or assembler.ACTION_ID != self.ACTION_ID or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore)
                or snapshots.store.run_id != assembler.organizations.run_id or not callable(select_current)):
            raise ValueError('Government inspection reader requires actual formal A10 assembler, original snapshots and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_selection = (self.ACTION_ID, self.CONDITION_CODE, self.CONDITION_CODES, self.ASSEMBLER_TYPE, self.READER_SCHEMA)
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            assembler._views.schemas, assembler.methods, assembler.audit_sink, self.snapshots, self.snapshots.store,
            self.select_current, *assembler.decision_strategies)

    def _configuration(self):
        return {'schema_version': self.READER_SCHEMA, 'action_id': self.ACTION_ID,
            'condition_code': self.CONDITION_CODE, 'run_id': self.assembler.organizations.run_id,
            'condition_codes': list(self.CONDITION_CODES),
            'source_mode': self.assembler.source_mode, 'macro_version': self.assembler.macro_version,
            'policy_version': self.assembler.policy_version, 'model_version': self.assembler.model_version,
            'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or (self.ACTION_ID, self.CONDITION_CODE, self.CONDITION_CODES, self.ASSEMBLER_TYPE, self.READER_SCHEMA) != self._original_selection
                or self.assembler.ACTION_ID != self.ACTION_ID or not isinstance(self.assembler, self.ASSEMBLER_TYPE)
                or self.assembler.source_mode != 'formal' or self.assembler._views.source_mode != 'formal'
                or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.provider is not self.assembler.provider
                or self.assembler._views.macro_version != self.assembler.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('Government inspection reader changed original source/model/snapshot components or declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        wait_kind = _WAIT_KINDS.get(check.condition.condition_code, 'Task')
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code not in self.CONDITION_CODES or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != wait_kind):
            raise TaskConflict('Government inspection reader replaces original task wait or recipient')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if wait_kind == 'Task' and original_input.task_ref.key() != old_refs[0].key():
            raise TaskConflict('Government inspection wait is absent from its original invocation snapshot')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentInspectionCurrentSelection):
            raise TaskConflict('Government inspection reader requires an explicit typed current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or current_input.task_ref.key()[:2] != original_input.task_ref.key()[:2]
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government inspection reader replaces original scope/task or authorized historical/current sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government inspection assembly changes original source snapshot or authorized recipient')
            # Historical inputs are independent authorized reads, never a
            # substitute for the exact current sources validated by assembly.
            for ref in walk_references(original_input):
                reading.resolve(ref)
            original, task = reading.resolve(original_input.task_ref), reading.resolve(prepared.action_input.task_ref)
            if (not isinstance(original, GovInspectionTaskView) or not isinstance(task, GovInspectionTaskView)
                    or original.ref.key() != original_input.task_ref.key() or task.ref.key() != current_input.task_ref.key()
                    or original.organization_id != source['organization_id'] or task.organization_id != source['organization_id']
                    or original.execution_action_id != self.ACTION_ID or task.execution_action_id != self.ACTION_ID
                    or original.scope != original_input.scope or task.scope != current_input.scope
                    or original.inspection_ref.key()[:2] != task.inspection_ref.key()[:2]):
                raise TaskConflict('Government inspection reader replaces original task, agency or physical inspection')
            if check.condition.condition_code in {_WINDOW_CODE, _HANDOFF_CODE, _CAPACITY_CODE}:
                # Keep original/current work-profile versions available to the
                # native validator under this same authorized reading guard.
                reading.resolve(original.work_profile_ref)
                reading.resolve(task.work_profile_ref)
                if check.condition.condition_code in {_HANDOFF_CODE, _CAPACITY_CODE}:
                    for row in (original, task):
                        reading.resolve(row.estimate_ref)
                        for ref in row.work_fact_refs:
                            reading.resolve(ref)
                if check.condition.condition_code == _CAPACITY_CODE:
                    if (original.resource_calendar_ref is None or task.resource_calendar_ref is None
                            or original.resource_calendar_ref.key() != old_refs[0].key()
                            or task.resource_calendar_ref.key()[:2] != old_refs[0].key()[:2]):
                        raise TaskConflict('Government inspection reader replaces its original emitted capacity calendar')
                    reading.resolve(original.resource_calendar_ref)
                    reading.resolve(task.resource_calendar_ref)
            elif check.condition.condition_code == _DEPENDENCY_CODE:
                current_refs = [ref for ref in task.dependency_refs if ref.key()[:2] == old_refs[0].key()[:2]]
                if old_refs[0].key() not in {ref.key() for ref in original.dependency_refs} or len(current_refs) != 1:
                    raise TaskConflict('Government inspection reader replaces its original emitted dependency')
                reading.resolve(old_refs[0])
                reading.resolve(current_refs[0])
            for row, action_input in ((original, original_input), (task, prepared.action_input)):
                inspection = reading.resolve(row.inspection_ref)
                basis = reading.resolve(action_input.inspection_basis_ref)
                if (not isinstance(inspection, GovInspectionView) or inspection.task_ref != row.ref
                        or inspection.organization_id != source['organization_id'] or inspection.permit_ref != row.permit_ref
                        or not isinstance(basis, GovInspectionRuleView) or basis.task_ref != row.ref
                        or basis.inspection_ref != inspection.ref or basis.organization_id != source['organization_id']
                        or basis.purpose != 'inspection' or row.inspection_basis_ref != basis.ref
                        or row.permit_ref != action_input.permit_ref or row.observation_method_ref != action_input.observation_method_ref
                        or {ref.key() for ref in row.received_observation_refs} != {ref.key() for ref in action_input.observation_refs}
                        or {ref.key() for ref in row.prior_issue_refs} != {ref.key() for ref in action_input.prior_issue_refs}):
                    raise TaskConflict('Government inspection reader changes exact task/inspection/basis or original received sources')
            current_observations = {ref.key()[:2]: ref for ref in prepared.action_input.observation_refs}
            current_issues = {ref.key()[:2]: ref for ref in prepared.action_input.prior_issue_refs}
            def retained(refs, current):
                old = {ref.key()[:2] for ref in refs}
                return old <= set(current) if check.condition.condition_code == _HANDOFF_CODE else old == set(current)

            if (len(current_observations) != len(prepared.action_input.observation_refs)
                    or len(current_issues) != len(prepared.action_input.prior_issue_refs)
                    or not retained(original_input.observation_refs, current_observations)
                    or not retained(original_input.prior_issue_refs, current_issues)):
                raise TaskConflict('Government inspection reader replaces or duplicates original received evidence/issue identities')
            for old_ref in original_input.observation_refs:
                old, current = reading.resolve(old_ref), reading.resolve(current_observations[old_ref.key()[:2]])
                if (not isinstance(old, GovInspectionObservationView) or not isinstance(current, GovInspectionObservationView)
                        or old.task_ref != original.ref or current.task_ref != task.ref
                        or any(getattr(old, field) != getattr(current, field) for field in type(old).model_fields
                            if field not in {'ref', 'task_ref', 'inspection_ref', 'available_at', 'effective_window', 'evidence_refs'})
                        or old.inspection_ref != original.inspection_ref or current.inspection_ref != task.inspection_ref
                        or not {ref.key() for ref in old.evidence_refs} <= {ref.key() for ref in current.evidence_refs}):
                    raise TaskConflict('Government inspection reader rewrites a received observation or its actual author/method/facts')
            for old_ref in original_input.prior_issue_refs:
                old, current = reading.resolve(old_ref), reading.resolve(current_issues[old_ref.key()[:2]])
                if (not isinstance(old, GovInspectionIssueView) or not isinstance(current, GovInspectionIssueView)
                        or old.task_ref != original.ref or current.task_ref != task.ref
                        or any(not {ref.key()[:2] for ref in getattr(old, field)} <= {ref.key()[:2] for ref in getattr(current, field)}
                            for field in ('requirement_refs', 'response_refs', 'assessment_refs'))):
                    raise TaskConflict('Government inspection reader drops original issue, requirement or received response history')
            return GovernmentInspectionTaskConditionReading(prepared.context, reading,
                deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck()
            self._check()
            current_evidence = {Reference.model_validate(row['ref']).key(): row['projection']
                for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot
                    or any(current_evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government inspection reader changed original snapshot or assembled context/input/source reading')


def build_assembled_government_inspection_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold the actual source/authority/inbox/journal guard through task recovery."""
    from integration.task_continuation import build_government_inspection_task_continuation_dispatcher

    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentInspectionReader, dispatcher_factory=build_government_inspection_task_continuation_dispatcher)


def _build_assembled_government_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader_type, dispatcher_factory):
    """Bind one actual Government reader to its original protected task journal."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Government inspection recovery requires actual same-run guard and native/successor validators')
    reader = reader_type(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        validated = assembler.registry.get(reader.ACTION_ID).contract.validate_input(deepcopy(preparation.next_input))
        if validated.model_dump(mode='json') != preparation.next_input:
            raise TaskConflict('Government inspection successor substitutes its current closed input')
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
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({reader.ACTION_ID})):
            raise TaskConflict('Government inspection recovery changed original snapshots/journal/recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Government inspection recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id=reader.ACTION_ID, role='Government')
