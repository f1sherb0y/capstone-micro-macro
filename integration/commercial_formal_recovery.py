"""Bind existing commercial A12 waits to an explicitly guarded formal application."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.commercial_callbacks import CommercialSuccessorCallbacks, CommercialNextSelection
from integration.commercial_continuation import CommercialContinuationReader, CommercialCurrentSelection
from integration.commercial_worker import CommercialTaskWorker
from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId
from src.coordination.commercial_execution_query import (
    EXECUTION_CODE, CommercialExecutionConditionReading, check_commercial_execution,
)
from src.coordination.commercial_conditions import (
    commercial_execution_profiles, LATE_EXECUTION_CODES,
    _authenticate_formal_late_execution, _check_late_execution_history,
)
from src.coordination.commercial_state_continuity import check_commercial_state_continuity
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class CommercialFormalRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_execution_enabled: bool = False


@dataclass(frozen=True)
class CommercialFormalRecoveryBindings:
    select_current: Callable
    select_next: Callable
    read_guard: Callable
    validate_relation: Callable
    project_signal: Callable

    def components(self):
        return tuple(getattr(self, name) for name in (
            'select_current', 'select_next', 'read_guard', 'validate_relation', 'project_signal'))

    def __post_init__(self):
        if not all(callable(callback) for callback in self.components()):
            raise ValueError('Formal commercial recovery requires actual selectors, guard and native relation validation')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'select_next', 'read_guard', 'validate_relation', 'project_signal')}


class CommercialFormalRecoveryReader(CommercialContinuationReader):
    def __init__(self, *, worker, bindings, action_id):
        if (not isinstance(worker, CommercialTaskWorker) or worker.assembler.source_mode != 'formal'
                or action_id not in {'CONTRACTOR-A12', 'SUPPLIER-A12'}
                or not isinstance(bindings, CommercialFormalRecoveryBindings)):
            raise ValueError('Formal commercial recovery requires its original A12 worker and callbacks')
        self.worker, self.bindings, self.ACTION_ID = worker, bindings, action_id
        super().__init__(assembler=worker.assembler, select_current=bindings.select_current)
        self._original = self._components()
        self._declared = bindings.configuration_evidence()
        self._action_id = action_id
        self._reader_configuration = self._configuration()

    def _configuration(self):
        view = self.assembler._views[self.ACTION_ID]
        return dict(schema_version='commercial-formal-recovery-reader.v3', action_id=self.ACTION_ID,
            run_id=self.worker.store.run_id, source_mode=self.assembler.source_mode,
            macro_version=view.macro_version, policy_version=self.assembler.policy_version,
            model_version=self.assembler.model_version, client_version=self.worker.client_version,
            condition_codes=sorted(code for action, code in self._conditions if action == self.ACTION_ID),
            snapshot_schema=self.worker.snapshots.SCHEMA, callbacks=self.bindings.configuration_evidence(),
            execution_conditions=module_factory_descriptor(commercial_execution_profiles, 'execution_conditions'),
            execution_checker=module_factory_descriptor(check_commercial_execution, 'execution_checker'),
            late_execution_checker=module_factory_descriptor(_authenticate_formal_late_execution, 'late_execution_checker'),
            late_execution_history=module_factory_descriptor(_check_late_execution_history, 'late_execution_history'),
            state_continuity=module_factory_descriptor(check_commercial_state_continuity, 'state_continuity'),
            read_sources=module_factory_descriptor(self.assembler.read_sources, 'read_sources'),
            reader=module_factory_descriptor(type(self).__call__, 'read_current'))

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._reader_configuration)

    def _components(self):
        return (self.worker, self.worker.store, self.worker.snapshots, self.worker.snapshots.store,
            self.worker.journal, self.worker.journal.store, self.worker.journal.registry,
            self.assembler, self.assembler.registry, self.assembler.organizations, self.assembler.methods,
            self.select_current, self.bindings, *self.bindings.components(),
            commercial_execution_profiles, check_commercial_execution,
            _authenticate_formal_late_execution, _check_late_execution_history, check_commercial_state_continuity,
            *self.assembler.decision_strategies,
            *(component for view in self.assembler._views.values()
                for component in (view, view.provider, view.schemas, view.organizations)))

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original)
                or any(now is not original for now, original in zip(current, self._original))
                or self.bindings.configuration_evidence() != self._declared
                or self._configuration() != self._reader_configuration
                or self.worker.assembler is not self.assembler or self.assembler.source_mode != 'formal'
                or self.worker.snapshots.store is not self.worker.store or self.worker.journal.store is not self.worker.store
                or self.ACTION_ID != self._action_id or self.ACTION_ID not in self.assembler._views
                or any(view.source_mode != 'formal' for view in self.assembler._views.values())):
            raise TaskConflict('Formal commercial recovery changed original worker/sources/journal/callbacks')

    @property
    def snapshots(self):
        return self.worker.snapshots

    def __call__(self, check, *, execution_terminal=False):
        self._check()
        result = self._read_terminal(check) if execution_terminal else super().__call__(check)
        self._check()
        return result

    def condition_reading(self, check, prepared, ref):
        if check.condition.condition_code not in {EXECUTION_CODE, *LATE_EXECUTION_CODES}:
            return super().condition_reading(check, prepared, ref)
        snapshot = self.snapshots.get(TaskIdentity(**check.source['identity']))
        return CommercialExecutionConditionReading(prepared.context, prepared.reading, ref,
            prepared.action_input.continuation_profile_ref, ActionContext.model_validate(snapshot['context']),
            deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'))

    def read_prepared_condition(self, check, prepared, ref):
        """Authenticate each newly assembled successor at preparation and revalidation."""
        self.validate_prepared(check, prepared)
        return self.condition_reading(check, prepared, ref)

    def validate_execution_relation(self, **kwargs):
        """Keep the original snapshot fixed through native execution authentication."""
        self._check()
        source = deepcopy(kwargs['source_identity'])
        identity = TaskIdentity(**source)
        snapshot = self.snapshots.get(identity)
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Commercial execution authentication changed the original snapshot')
        try:
            return self.bindings.validate_relation(**kwargs)
        finally:
            self._check()
            if task_digest(self.snapshots.get(identity)) != task_digest(snapshot):
                raise TaskConflict('Commercial native execution authentication rewrote the original snapshot')

    def _read_terminal(self, check):
        source = check.source['identity']
        if (source['action_id'] != self.ACTION_ID or check.condition.condition_code != EXECUTION_CODE
                or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('ContinuationExecution',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Commercial terminal reading requires the original execution wait and recipient')
        identity = TaskIdentity(**source)
        snapshot = self.snapshots.get(identity)
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Commercial terminal reading replaces the original persisted snapshot')
        original_context = ActionContext.model_validate(snapshot['context'])
        original_input = self.assembler.registry.get(self.ACTION_ID).contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, CommercialCurrentSelection):
            raise TaskConflict('Commercial terminal reading requires a typed actual host selection')
        selected = deepcopy(selected)
        context, ref = selected.context, selected.current_ref
        if (not isinstance(context, ActionContext) or not isinstance(ref, Reference)
                or selected.profile_ref != original_input.continuation_profile_ref
                or ref.key()[:2] != check.condition.object_refs[0].key()[:2]
                or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
                or context.operation_id != source['request_id'] or context.scope != original_context.scope
                or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
                or context.business_time != check.signal.business_time
                or context.business_time.clock_ref != original_context.business_time.clock_ref
                or context.business_time.offset < original_context.business_time.offset):
            raise TaskConflict('Commercial terminal reading replaces the original invocation or current read point')
        _, reading = self.assembler.read_sources(context)
        try:
            if reading.organization_id != source['organization_id']:
                raise TaskConflict('Commercial terminal reading changes the original firm')
            for dependency in (check.condition.object_refs[0], ref, selected.profile_ref):
                reading.resolve(dependency)
            if task_digest(self.snapshots.get(identity)) != task_digest(snapshot):
                raise TaskConflict('Commercial terminal reading changed original persisted input/context')
            return CommercialExecutionConditionReading(context, reading, ref, selected.profile_ref,
                original_context, deepcopy(snapshot['action_input']), original_input.model_dump(mode='json'))
        finally:
            reading.recheck()
            self._check()

    def validate_prepared(self, check, prepared):
        self._check()
        source = check.source['identity']
        if source['action_id'] != self.ACTION_ID or source['purpose'] != 'action':
            raise TaskConflict('Formal commercial recovery replaces original action or purpose')
        snapshot = self.worker.snapshots.get(TaskIdentity(**source))
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Formal commercial recovery changes original invocation snapshot')
        context, reading = prepared.context, prepared.reading
        try:
            original_ref = Reference.model_validate(snapshot['action_input']['continuation_profile_ref'])
            original_profile = reading.resolve(original_ref)
            current_profile = reading.resolve(prepared.action_input.continuation_profile_ref)
            original_time = snapshot['context']['business_time']
            check_commercial_state_continuity(reading=reading, types=self.assembler._types[self.ACTION_ID],
                original_profile=original_profile, profile=current_profile,
                original_context=ActionContext.model_validate(snapshot['context']), context=context,
                organization_id=source['organization_id'], supplier=self.ACTION_ID == 'SUPPLIER-A12')
            if (original_profile.organization_id != source['organization_id']
                    or current_profile.organization_id != source['organization_id']
                    or original_profile.state_ref.key()[:2] != current_profile.state_ref.key()[:2]
                    or task_digest(context.scope.model_dump(mode='json')) != task_digest(snapshot['context']['scope'])
                    or task_digest(context.business_time.clock_ref.model_dump(mode='json')) != task_digest(original_time['clock_ref'])
                    or context.business_time.offset < original_time['offset']
                    or context.operation_id == source['request_id']
                    or self.bindings.validate_relation(source_identity=deepcopy(source),
                        condition_code=check.condition.condition_code, original_snapshot=deepcopy(snapshot),
                        context=context.model_copy(deep=True), reading=reading) is not True):
                raise TaskConflict('Formal commercial recovery lacks native original history/current source authentication')
        finally:
            reading.recheck()
            self._check()
            if task_digest(self.worker.snapshots.get(TaskIdentity(**source))) != task_digest(snapshot):
                raise TaskConflict('Formal commercial recovery changed original persisted input/context')


def build_formal_commercial_recovery(*, inbox, worker, bindings, action_id, reader):
    from integration.task_continuation import build_commercial_continuation_dispatcher
    role = {'CONTRACTOR-A12': 'Contractor', 'SUPPLIER-A12': 'Supplier'}[action_id]
    if reader.worker is not worker or reader.bindings is not bindings or reader.ACTION_ID != action_id:
        raise ValueError('Formal commercial recovery requires the original shared reader/worker')

    def select_next(*, source, signal, request_id):
        reader._check()
        snapshot = worker.snapshots.get(TaskIdentity(**source['identity']))
        result = bindings.select_next(source=deepcopy(source), signal=signal.model_copy(deep=True), request_id=request_id)
        if (not isinstance(result, CommercialNextSelection)
                or task_digest(result.original_context.model_dump(mode='json')) != task_digest(snapshot['context'])):
            raise TaskConflict('Formal commercial successor replaces original persisted context')
        reader._check()
        return result

    callbacks = CommercialSuccessorCallbacks(assembler=worker.assembler, select_next=select_next,
        client_version=worker.client_version, model_version=worker.model_version,
        read_prepared=reader.read_prepared_condition, validate_relation=reader.validate_execution_relation)

    def revalidate(source, preparation, signal):
        reader._check()
        valid = callbacks.revalidate(source, preparation, signal)
        if valid and bindings.validate_relation(source_identity=deepcopy(source['identity']),
                successor_preparation=deepcopy(preparation), signal=signal.model_copy(deep=True)) is not True:
            raise TaskConflict('Formal commercial successor lacks native preserved-history/current-source authentication')
        reader._check()
        return valid

    dispatcher = build_commercial_continuation_dispatcher(inbox=inbox, store=worker.store, read_current=reader,
        project_signal=bindings.project_signal, prepare=callbacks.prepare, revalidate=revalidate,
        action_ids={action_id}, validate_relation=reader.validate_execution_relation)
    original = (dispatcher.journal, dispatcher.journal.registry, dispatcher.prepare, dispatcher.revalidate, dispatcher.project_signal)
    callback_components = (callbacks.assembler, callbacks.select_next, callbacks.read_prepared, callbacks.validate_relation)

    def check_binding():
        reader._check()
        if (dispatcher.inbox is not inbox or dispatcher.journal.store is not worker.store
                or any(now is not previous for now, previous in zip((callbacks.assembler, callbacks.select_next,
                    callbacks.read_prepared, callbacks.validate_relation), callback_components))
                or any(now is not previous for now, previous in zip((dispatcher.journal,
                    dispatcher.journal.registry, dispatcher.prepare, dispatcher.revalidate, dispatcher.project_signal), original))):
            raise TaskConflict('Formal commercial dispatcher changed original journal or callbacks')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != worker.store.run_id or organization_id not in worker.store.organization_ids:
            raise TaskConflict('Formal commercial recovery requires original run and recipient')
        with bindings.read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=bindings.read_guard, check_binding=check_binding, action_id=action_id, role=role)
