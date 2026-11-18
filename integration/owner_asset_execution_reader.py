"""Assemble current authorized OWN-A14 sources for original query waits."""
from copy import deepcopy
from dataclasses import dataclass

from integration.owner_asset_actions import OwnerAssetActionAssembler
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.owner_asset_objects import OwnerAssetExecutionView, OwnerAssetView
from src.actions.contracts.common import Reference
from src.coordination.owner_asset_conditions import OwnerAssetExecutionConditionReading
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class OwnerAssetExecutionCurrentSelection:
    request: RoleContractInvocation
    execution_ref: Reference


@dataclass(frozen=True)
class OwnerAssetRecoveryBindings(OwnerContinuationRecoveryBindings):
    """Use the existing recovery callback contract with the original A14 reader."""
    assembler: OwnerAssetActionAssembler

    def __post_init__(self):
        if (not isinstance(self.assembler, OwnerAssetActionAssembler)
                or not all(callable(callback) for callback in self.components()[1:])):
            raise ValueError('Owner asset recovery requires original assembler and actual callbacks')
        object.__setattr__(self, '_reader', OwnerAssetExecutionReader(
            assembler=self.assembler, select_current=self.select_current))


class OwnerAssetExecutionReader:
    """Read explicit original/current versions through the original A14 assembler.

    The host holds source/authorization/journal guards throughout evaluation.
    The selector supplies a complete current invocation and explicit execution
    version. Signals never supply projections or establish which version is
    current. Assembly runs no action, native query, model or asset operation.
    """
    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, OwnerAssetActionAssembler) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Owner asset recovery requires the original formal A14 assembler and current selector')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            self.select_current)

    def _configuration(self):
        return {'schema_version': 'owner-asset-execution-reader.v1',
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        if (any(now is not original for now, original in zip(self._components(), self._original_components))
                or self.assembler.ACTION_ID != 'OWN-A14' or self.assembler.source_mode != 'formal'
                or self.assembler._views.provider is not self.assembler.provider
                or self._configuration() != self._declared):
            raise TaskConflict('Owner asset reader changed original assembler, selector or source declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'OWN-A14' or source['role'] != 'Owner' or source['purpose'] != 'action'
                or check.condition.condition_code != 'query_original_asset_operation'
                or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'AssetOperationExecution'):
            raise TaskConflict('Owner asset reader changes original condition, recipient or execution selection')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, OwnerAssetExecutionCurrentSelection)
                or not isinstance(selected.execution_ref, Reference)):
            raise TaskConflict('Owner asset reader requires a typed current request and explicit execution version')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context, ref, old_ref = request.context, selected.execution_ref.model_copy(deep=True), old_refs[0]
        registration = self.assembler.registry.get('OWN-A14')
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.id != 'OWN-A14' or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or (ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                or not {old_ref.key(), ref.key()} <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Owner asset reader requires visible original/current versions and a fresh formal context')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Owner asset reader substitutes another authorized Owner')
            asset = prepared.reading.resolve(prepared.action_input.asset_ref)
            if not isinstance(asset, OwnerAssetView) or asset.ref.key() != prepared.action_input.asset_ref.key():
                raise TaskConflict('Owner asset reader lacks the selected actual current asset')
            if ref.key() not in {item.key() for item in asset.execution_refs}:
                raise TaskConflict('Selected execution is absent from the actual current asset history')
            execution = prepared.reading.resolve(ref)
            if (not isinstance(execution, OwnerAssetExecutionView) or execution.ref.key() != ref.key()
                    or (execution.asset_ref.kind, execution.asset_ref.id) != (asset.ref.kind, asset.ref.id)
                    or execution.organization_id != source['organization_id'] or execution.run_id != source['run_id']):
                raise TaskConflict('Selected execution substitutes another original asset, Owner or run')
            return OwnerAssetExecutionConditionReading(prepared.context, prepared.reading, ref,
                prepared.action_input.operating_profile_ref)
        finally:
            prepared.reading.recheck()
            self._check()
            if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Owner asset reader changed current input, context or authorized source snapshot')


def build_assembled_owner_asset_execution_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Hold read_guard(run_id, organization_id) through original wait wakeup.

    The guard covers inbox, original/current sources, authority and journal.
    Application preparation and revalidation remain responsible for independent
    successor facts, preserved obligations and a distinct current business plan.
    """
    from integration.task_continuation import build_owner_asset_continuation_dispatcher

    reader = OwnerAssetExecutionReader(assembler=assembler, select_current=select_current)
    if not callable(read_guard) or reader.assembler.organizations.run_id != store.run_id:
        raise ValueError('Owner asset recovery requires its same-run source/authority/journal guard')
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()):
        raise ValueError('Owner asset recovery requires actual query and successor validation callbacks')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def check_callbacks():
        reader._check()
        if any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items()):
            raise TaskConflict('Owner asset recovery callback declarations changed')

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

    dispatcher = build_owner_asset_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current,
        revalidate=revalidate_current, extra_profiles=extra_profiles)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry

    def check_binding():
        check_callbacks()
        if (dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not revalidate_current or dispatcher.action_ids != frozenset({'OWN-A14'})):
            raise TaskConflict('Owner asset recovery changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Owner asset recovery requires its original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    from integration.owner_asset_terminal import OwnerAssetTerminalReader
    from integration.owner_continuation_terminal import OwnerContinuationTerminalBridge
    from src.coordination.invocations import InvocationSnapshotStore

    terminal_reader = OwnerAssetTerminalReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    return OwnerContinuationTerminalBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='OWN-A14', role='Owner',
        terminal_reader=terminal_reader, native_validator=validate_relation)
