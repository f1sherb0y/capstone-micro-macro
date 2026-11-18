"""Assemble authorized current A13 sources for original execution wait recovery."""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable
from pydantic import model_serializer

from integration.module_host import module_factory_descriptor
from integration.owner_continuation_actions import OwnerContinuationActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.contracts.owner_continuation_objects import OwnerContinuationStateView
from src.coordination.owner_continuation_conditions import (
    OwnerContinuationExecutionConditionReading, owner_original_continuation_execution_profile,
)
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class OwnerContinuationExecutionCurrentSelection:
    request: RoleContractInvocation
    execution_refs: tuple[Reference, ...]


class OwnerContinuationRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_execution_enabled: bool = False
    terminal_asset_execution_enabled: bool = False
    terminal_operating_execution_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_execution_enabled:
            result.pop('terminal_execution_enabled', None)
        if not self.terminal_asset_execution_enabled:
            result.pop('terminal_asset_execution_enabled', None)
        if not self.terminal_operating_execution_enabled:
            result.pop('terminal_operating_execution_enabled', None)
        return result


@dataclass(frozen=True)
class OwnerContinuationRecoveryBindings:
    assembler: OwnerContinuationActionAssembler
    select_current: Callable
    read_guard: Callable
    validate_relation: Callable
    project_signal: Callable
    prepare: Callable
    revalidate: Callable
    _reader: object = field(init=False, repr=False)

    def components(self):
        return (self.assembler, self.select_current, self.read_guard, self.validate_relation,
            self.project_signal, self.prepare, self.revalidate)

    def __post_init__(self):
        if (not isinstance(self.assembler, OwnerContinuationActionAssembler)
                or not all(callable(callback) for callback in self.components()[1:])):
            raise ValueError('Owner continuation recovery requires original assembler and actual callbacks')
        object.__setattr__(self, '_reader', OwnerContinuationExecutionReader(
            assembler=self.assembler, select_current=self.select_current))

    def configuration_evidence(self):
        return {'reader': self._reader.configuration_evidence(), 'policy_version': self.assembler.policy_version,
            **{name: module_factory_descriptor(getattr(self, name), name) for name in (
                'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}}


class OwnerContinuationExecutionReader:
    """Select explicit current versions through the original formal A13 assembler.

    The application holds a boundary covering original/current source versions,
    authorization and journal reads throughout condition evaluation and wakeup.
    Selection receives a scheduling hint, never a replacement source projection.
    Assembly runs no processor, model, native query or business transition.
    """
    ACTION_ID = 'OWN-A13'
    ASSEMBLER_TYPE = OwnerContinuationActionAssembler

    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, self.ASSEMBLER_TYPE) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Owner execution recovery requires the original formal A13 assembler and current selection')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            self.select_current, owner_original_continuation_execution_profile)

    def _configuration(self):
        return {'schema_version': 'owner-continuation-execution-reader.v1',
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'execution_condition': module_factory_descriptor(owner_original_continuation_execution_profile, 'execution_condition'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        if (any(now is not original for now, original in zip(self._components(), self._original_components))
                or self.assembler.ACTION_ID != self.ACTION_ID or self.assembler.source_mode != 'formal'
                or self.assembler._views.provider is not self.assembler.provider
                or self._configuration() != self._declared):
            raise TaskConflict('Owner execution recovery changed original assembler, selection or source declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'OWN-A13' or source['role'] != 'Owner' or source['purpose'] != 'action'
                or check.condition.condition_code != 'query_original_continuation_execution'
                or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'ContinuationExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Owner execution reader changes original condition, recipient or execution selection')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, OwnerContinuationExecutionCurrentSelection)
                or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
            raise TaskConflict('Owner execution reader requires a typed actual current request and execution selection')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        refs = tuple(ref.model_copy(deep=True) for ref in selected.execution_refs)
        registration = self.assembler.registry.get('OWN-A13')
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.id != 'OWN-A13' or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or len(refs) != len(old_refs) or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                or not {ref.key() for ref in (*old_refs, *refs)} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Owner execution reader requires complete visible original/current versions and a fresh formal context')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Owner execution reader substitutes another authorized organization')
            profile = prepared.reading.resolve(prepared.action_input.continuation_profile_ref)
            state = prepared.reading.resolve(profile.state_ref)
            if (not isinstance(state, OwnerContinuationStateView)
                    or not {ref.key() for ref in refs} <= {ref.key() for ref in state.execution_refs}):
                raise TaskConflict('Selected current executions are absent from the actual current Owner state')
            return OwnerContinuationExecutionConditionReading(prepared.context, prepared.reading, refs,
                prepared.action_input.continuation_profile_ref)
        finally:
            prepared.reading.recheck()
            self._check()
            if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Owner execution reader changed original current context, input or source snapshot')


def build_assembled_owner_continuation_execution_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Hold read_guard(run_id, organization_id) through all original wait checks.

    The guard must cover the recipient inbox, old/current sources, authority and
    original journal. Preparation and revalidation still own all successor facts.
    """
    from integration.task_continuation import build_owner_continuation_execution_dispatcher

    reader = OwnerContinuationExecutionReader(assembler=assembler, select_current=select_current)
    if not callable(read_guard) or reader.assembler.organizations.run_id != store.run_id:
        raise ValueError('Owner recovery requires an actual same-run source/authority/journal guard')
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()):
        raise ValueError('Owner continuation recovery requires actual query and successor validation callbacks')
    declarations = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_owner_continuation_execution_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current,
        revalidate=revalidate_current, extra_profiles=extra_profiles)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    guard_descriptor = module_factory_descriptor(read_guard, 'read_guard')

    def check_binding():
        reader._check()
        if (dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not revalidate_current or dispatcher.action_ids != frozenset({'OWN-A13'})
                or any(module_factory_descriptor(callback, name) != declarations[name]
                    for name, callback in callbacks.items())
                or module_factory_descriptor(read_guard, 'read_guard') != guard_descriptor):
            raise TaskConflict('Owner recovery dispatcher changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Owner recovery dispatcher requires its original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    from integration.owner_continuation_terminal import OwnerContinuationTerminalReader, OwnerContinuationTerminalBridge
    from src.coordination.invocations import InvocationSnapshotStore

    terminal_reader = OwnerContinuationTerminalReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    return OwnerContinuationTerminalBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='OWN-A13', role='Owner',
        terminal_reader=terminal_reader, native_validator=validate_relation)
