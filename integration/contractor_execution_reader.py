"""Read actual original Contractor A07 executions for guarded wait recovery."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.contractor_execution_actions import ContractorExecutionActionAssembler
from integration import contractor_execution_actions as execution_actions
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, ResumeCondition, StrictRecord, TextId
from src.actions.contracts import contractor_execution_objects as execution_objects
from src.actions.contracts.contractor_execution_objects import ContractorWorkExecutionView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.implementation import callable_implementation
from src.coordination.continuations import ConditionCheck
from src.coordination.contractor_execution_conditions import ContractorExecutionConditionReading, _CODES
from src.coordination import contractor_execution_conditions as execution_conditions
from src.actions.roles import contractor_execution as execution_role
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class ContractorExecutionCurrentSelection:
    request: RoleContractInvocation
    execution_refs: tuple[Reference, ...]


class ContractorExecutionRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class ContractorExecutionRecoveryBindings:
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
            raise ValueError('Contractor execution recovery requires actual selection, guard and validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class ContractorExecutionReader:
    """Use the original A07 assembler's existing-execution branch without replay.

    The selector supplies a full current authorized invocation and all explicit
    current versions of the original executions. Source/authority/inbox/journal
    guards cover the entire wake. Reading creates no work, consumption, receipt,
    method calculation or model call; native effects require independent checks.
    """
    ACTION_ID = 'CONTRACTOR-A07'

    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, ContractorExecutionActionAssembler) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Contractor execution reader requires original formal A07 assembler and actual selector')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            assembler._views.schemas, assembler.methods, self.select_current, *assembler.decision_strategies,
            assembler.registry.get(self.ACTION_ID).contract, *self._execution_checks().values())

    def _execution_checks(self):
        return dict(condition_profiles=execution_conditions.contractor_original_execution_profiles,
            execution_checks=execution_role.execute_or_report,
            work_history_checks=execution_objects.validate_contractor_recorded_work_history,
            work_command_checks=execution_objects.validate_contractor_work_record_execution,
            registered_processor=self.assembler.registry.get(self.ACTION_ID).processor,
            source_checks=execution_actions.validate_contractor_execution_sources,
            source_schemas=self.assembler.SOURCE_SCHEMAS)

    def _configuration(self):
        return {'schema_version': 'contractor-execution-reader.v5', 'action_id': self.ACTION_ID,
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'policy_version': self.assembler.policy_version,
            'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current'),
            'check_implementations': {name: callable_implementation(callback)
                for name, callback in self._execution_checks().items()},
            'checks': {name: module_factory_descriptor(callback, name)
                for name, callback in self._execution_checks().items()}}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or self.assembler.ACTION_ID != 'CONTRACTOR-A07' or self.assembler.source_mode != 'formal'
                or self.ACTION_ID != self.assembler.ACTION_ID
                or self.assembler._views.provider is not self.assembler.provider
                or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.macro_version != self.assembler.macro_version
                or self.assembler._views.source_mode != 'formal' or self._configuration() != self._declared):
            raise TaskConflict('Contractor execution reader changed original source/model components or declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'CONTRACTOR-A07' or source['role'] != 'Contractor' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'WorkExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Contractor execution reader changes original condition, recipient or dependencies')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, ContractorExecutionCurrentSelection) or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
            raise TaskConflict('Contractor execution reader requires typed current request and explicit execution versions')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        refs = tuple(ref.model_copy(deep=True) for ref in selected.execution_refs)
        registration = self.assembler.registry.get('CONTRACTOR-A07')
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.id != 'CONTRACTOR-A07' or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or len(refs) != len(old_refs) or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                or not {ref.key() for ref in (*old_refs, *refs)} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Contractor execution reader requires all visible original/current executions and fresh formal context')
        action_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (action_input.execution_context.kind != 'existing'
                or {ref.key() for ref in action_input.execution_context.execution_refs} != {ref.key() for ref in refs}
                or len(action_input.execution_context.execution_refs) != len(refs)):
            raise TaskConflict('Contractor wait recovery must query selected original executions without issuing construction inputs')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Contractor execution reader substitutes another authorized organization')
            originals = {(ref.kind, ref.id): ref for ref in old_refs}
            for ref in refs:
                old_ref = originals[(ref.kind, ref.id)]
                original, current = prepared.reading.resolve(old_ref), prepared.reading.resolve(ref)
                if (not isinstance(original, ContractorWorkExecutionView) or not isinstance(current, ContractorWorkExecutionView)
                        or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                        or current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'organization_id', 'run_id', 'task_ref', 'operation_id', 'business_key', 'request_ref', 'request_sha256', 'scope'))
                        or original.status in {'recorded', 'failed', 'not_executed'} and current.status != original.status
                        or original.status == 'recorded' and (
                            current.core_event_id != original.core_event_id or current.recorded_at != original.recorded_at
                            or not {(item.kind, item.id) for item in original.work_record_refs}
                                <= {(item.kind, item.id) for item in current.work_record_refs})):
                    raise TaskConflict('Contractor execution reader changes original request/command/task/scope or known work history')
                if original.status == 'recorded':
                    unique_refs(original.work_record_refs); unique_refs(current.work_record_refs)
                    current_work = {item.key()[:2]: item for item in current.work_record_refs}
                    for old_work_ref in original.work_record_refs:
                        new_work_ref = current_work[old_work_ref.key()[:2]]
                        before, after = prepared.reading.resolve(old_work_ref), prepared.reading.resolve(new_work_ref)
                        if getattr(before, 'ref', None) != old_work_ref or getattr(after, 'ref', None) != new_work_ref:
                            raise TaskConflict('Contractor execution query substitutes an exact known work record source')
                        try:
                            execution_objects.validate_contractor_recorded_work_history(original, current, before, after)
                        except ValueError as error:
                            raise TaskConflict('Contractor execution query rewrites already recorded work') from error
            current_refs = tuple(ref.model_copy(deep=True) for ref in prepared.action_input.execution_context.execution_refs)
            return ContractorExecutionConditionReading(prepared.context, prepared.reading, current_refs)
        finally:
            prepared.reading.recheck()
            self._check()
            if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Contractor execution reader changed its original current invocation or source snapshot')


def build_assembled_contractor_execution_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one original source/authority/inbox/journal guard across recovery."""
    from integration.task_continuation import build_contractor_execution_continuation_dispatcher
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge

    reader = ContractorExecutionReader(assembler=assembler, select_current=select_current)
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Contractor execution recovery requires actual same-run source/authority/journal guard and validators')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions'] if raw['condition_code'] in _CODES]
        if len(conditions) != 1:
            raise TaskConflict('Contractor execution recovery requires its original emitted execution wait')
        current = reader(ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True)))
        try:
            validated_input = assembler.registry.get('CONTRACTOR-A07').contract.validate_input(deepcopy(preparation.next_input))
            operation = preparation.next_input.get('execution_context', {})
            if (validated_input.model_dump(mode='json') != preparation.next_input
                    or preparation.next_context != current.context.model_dump(mode='json')
                    or preparation.next_input.get('scope_ref') != current.context.scope.model_dump(mode='json')
                    or operation.get('kind') != 'existing'
                    or operation.get('execution_refs') != [ref.model_dump(mode='json') for ref in current.execution_refs]):
                raise TaskConflict('Contractor execution successor substitutes selected current context, scope or execution versions')
            current.reading.recheck()
            result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
            check_binding()
            return result
        finally:
            current.reading.recheck()

    dispatcher = build_contractor_execution_continuation_dispatcher(inbox=inbox, store=store,
        read_current=reader, validate_relation=validate_relation, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    original_prepare = dispatcher.prepare

    def check_binding():
        reader._check()
        if (any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())
                or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not original_prepare
                or dispatcher.revalidate is not revalidate_current or dispatcher.action_ids != frozenset({'CONTRACTOR-A07'})):
            raise TaskConflict('Contractor execution recovery changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Contractor execution recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='CONTRACTOR-A07', role='Contractor')
