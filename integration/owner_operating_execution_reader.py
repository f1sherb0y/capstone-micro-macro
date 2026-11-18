"""Assemble current authorized OWN-A15 sources for original query waits."""
from copy import deepcopy
from dataclasses import dataclass

from integration.owner_operating_actions import OwnerOperatingActionAssembler
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.owner_operating_objects import (
    OwnerOperatingExecutionView, OwnerOperatingPortfolioView, OwnerOperatingProfileView,
)
from src.actions.roles.qs_change import content_digest
from src.actions.contracts.common import Reference
from src.coordination.owner_operating_conditions import OwnerOperatingExecutionConditionReading
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class OwnerOperatingExecutionCurrentSelection:
    request: RoleContractInvocation
    execution_ref: Reference


@dataclass(frozen=True)
class OwnerOperatingRecoveryBindings(OwnerContinuationRecoveryBindings):
    """Use the existing recovery callback contract with the original A15 reader."""
    assembler: OwnerOperatingActionAssembler

    def __post_init__(self):
        if (not isinstance(self.assembler, OwnerOperatingActionAssembler)
                or not all(callable(callback) for callback in self.components()[1:])):
            raise ValueError('Owner operating recovery requires original assembler and actual callbacks')
        object.__setattr__(self, '_reader', OwnerOperatingExecutionReader(
            assembler=self.assembler, select_current=self.select_current))


class OwnerOperatingExecutionReader:
    """Read explicit original/current versions through the original A15 assembler.

    The host holds source/authorization/journal guards throughout evaluation.
    The selector supplies a complete current invocation and explicit execution
    version. Signals never supply projections or establish which version is
    current. Assembly runs no action, native query, model or operating revision.
    """
    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, OwnerOperatingActionAssembler) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Owner operating recovery requires the original formal A15 assembler and current selector')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            self.select_current)

    def _configuration(self):
        return {'schema_version': 'owner-operating-execution-reader.v1',
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        if (any(now is not original for now, original in zip(self._components(), self._original_components))
                or self.assembler.ACTION_ID != 'OWN-A15' or self.assembler.source_mode != 'formal'
                or self.assembler._views.provider is not self.assembler.provider
                or self._configuration() != self._declared):
            raise TaskConflict('Owner operating reader changed original assembler, selector or source declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'OWN-A15' or source['role'] != 'Owner' or source['purpose'] != 'action'
                or check.condition.condition_code != 'query_original_owner_operating_execution'
                or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'OwnerOperatingExecution'):
            raise TaskConflict('Owner operating reader changes original condition, recipient or execution selection')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, OwnerOperatingExecutionCurrentSelection)
                or not isinstance(selected.execution_ref, Reference)):
            raise TaskConflict('Owner operating reader requires a typed current request and explicit execution version')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context, ref, old_ref = request.context, selected.execution_ref.model_copy(deep=True), old_refs[0]
        registration = self.assembler.registry.get('OWN-A15')
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.id != 'OWN-A15' or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or (ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                or not {old_ref.key(), ref.key()} <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Owner operating reader requires visible original/current versions and a fresh formal context')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Owner operating reader substitutes another authorized Owner')
            portfolio = prepared.reading.resolve(prepared.action_input.portfolio_ref)
            if (not isinstance(portfolio, OwnerOperatingPortfolioView)
                    or portfolio.ref.key() != prepared.action_input.portfolio_ref.key()
                    or portfolio.organization_id != source['organization_id'] or portfolio.scope != prepared.context.scope):
                raise TaskConflict('Owner operating reader lacks the selected actual private portfolio')
            if ref.key() not in {item.key() for item in portfolio.execution_refs}:
                raise TaskConflict('Selected execution is absent from the actual current portfolio history')
            execution = prepared.reading.resolve(ref)
            if (not isinstance(execution, OwnerOperatingExecutionView) or execution.ref.key() != ref.key()
                    or execution.organization_id != source['organization_id'] or execution.run_id != source['run_id']):
                raise TaskConflict('Selected execution substitutes another original Owner or run')
            profile = prepared.reading.resolve(execution.profile_ref)
            if (not isinstance(profile, OwnerOperatingProfileView) or profile.ref.key() != execution.profile_ref.key()
                    or profile.organization_id != execution.organization_id or profile.scope != execution.scope
                    or profile.business_key != execution.business_key
                    or (profile.portfolio_ref.kind, profile.portfolio_ref.id) != (portfolio.ref.kind, portfolio.ref.id)
                    or content_digest(profile) != execution.profile_sha256):
                raise TaskConflict('Selected execution lacks its original immutable operating profile and portfolio')
            return OwnerOperatingExecutionConditionReading(prepared.context, prepared.reading, ref,
                prepared.action_input.operating_profile_ref)
        finally:
            prepared.reading.recheck()
            self._check()
            if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Owner operating reader changed current input, context or authorized source snapshot')


def build_assembled_owner_operating_execution_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Hold read_guard(run_id, organization_id) through original wait wakeup.

    The guard covers inbox, original/current sources, authority and journal.
    Application preparation and revalidation remain responsible for independent
    successor facts, preserved obligations and a distinct current business plan.
    """
    from integration.task_continuation import build_owner_operating_continuation_dispatcher

    reader = OwnerOperatingExecutionReader(assembler=assembler, select_current=select_current)
    if not callable(read_guard) or reader.assembler.organizations.run_id != store.run_id:
        raise ValueError('Owner operating recovery requires its same-run source/authority/journal guard')
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()):
        raise ValueError('Owner operating recovery requires actual query and successor validation callbacks')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def check_callbacks():
        reader._check()
        if any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items()):
            raise TaskConflict('Owner operating recovery callback declarations changed')

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

    dispatcher = build_owner_operating_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current,
        revalidate=revalidate_current, extra_profiles=extra_profiles)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry

    def check_binding():
        check_callbacks()
        if (dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not revalidate_current or dispatcher.action_ids != frozenset({'OWN-A15'})):
            raise TaskConflict('Owner operating recovery changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Owner operating recovery requires its original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    from src.coordination.invocations import InvocationSnapshotStore
    from integration.owner_continuation_terminal import OwnerContinuationTerminalBridge
    from integration.owner_operating_terminal import OwnerOperatingTerminalReader

    terminal_reader = OwnerOperatingTerminalReader(assembler=assembler, snapshots=InvocationSnapshotStore(store),
        select_current=select_current)
    return OwnerContinuationTerminalBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='OWN-A15', role='Owner',
        terminal_reader=terminal_reader, native_validator=validate_relation)
