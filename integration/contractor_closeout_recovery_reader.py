"""Assemble actual original Contractor A11 history waits through the existing closeout boundary."""
from copy import deepcopy
from dataclasses import dataclass
from pydantic import model_serializer

from integration import contractor_closeout_actions as closeout_actions
from integration.contractor_closeout_actions import ContractorCloseoutActionAssembler
from integration.contractor_formation_command_reader import ContractorFormationRecoveryBindings
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, walk_references
from src.actions.implementation import callable_implementation
from src.actions.roles import contractor_closeout as closeout_role
from src.coordination import contractor_closeout_conditions as closeout_conditions
from src.coordination.contractor_closeout_conditions import (
    ACCOUNT_CODE, HANDOVER_CODE, ContractorCloseoutConditionReading,
    contractor_original_closeout_history_profile,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class ContractorCloseoutCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


class ContractorCloseoutRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_history_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_history_enabled:
            result.pop('terminal_history_enabled', None)
        return result


@dataclass(frozen=True)
class ContractorCloseoutRecoveryBindings(ContractorFormationRecoveryBindings):
    """Use actual source, guard, native-history and successor callbacks, without command IDs."""


class ContractorCloseoutRecoveryReader:
    ACTION_ID = 'CONTRACTOR-A11'
    ROLE = 'Contractor'
    ASSEMBLER_TYPE = ContractorCloseoutActionAssembler
    SELECTION_TYPE = ContractorCloseoutCurrentSelection
    READING_TYPE = ContractorCloseoutConditionReading
    PROFILE_FACTORY = staticmethod(contractor_original_closeout_history_profile)
    ROOT_FIELD = 'contract_ref'
    SCOPE_FIELD = 'scope_ref'
    PROVIDER_ATTRIBUTE = 'provider'
    READER_SCHEMA = 'contractor-closeout-recovery-reader.v3'
    CONDITION_CODES = (HANDOVER_CODE, ACCOUNT_CODE)
    CONDITION_KINDS = {HANDOVER_CODE: 'HandoverRequest', ACCOUNT_CODE: 'FinalAccount'}
    MULTI_REF_CONDITION_CODES = ()
    CONDITION_REF_KIND_SEQUENCES = {}
    CONDITION_TRIGGER = 'dependency_change'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, self.ASSEMBLER_TYPE) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('Closeout recovery requires original formal A11 assembler, snapshots and actual selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, getattr(a, self.PROVIDER_ATTRIBUTE), a._views, a._views.schemas, a.methods,
            self.snapshots, self.snapshots.store, self.select_current, self.ASSEMBLER_TYPE,
            self.SELECTION_TYPE, self.READING_TYPE, self.PROFILE_FACTORY, *a.decision_strategies,
            *self._closeout_checks().values(),
            *((a.registry.get(self.ACTION_ID).contract,) if self.ACTION_ID == 'CONTRACTOR-A11' else ()))

    def _closeout_checks(self):
        # Other roles reuse the reading machinery and declare their own checks.
        if self.ACTION_ID != 'CONTRACTOR-A11':
            return {}
        return dict(condition_profile=self.PROFILE_FACTORY,
            history_checks=closeout_conditions.check_contractor_closeout_history,
            closeout_checks=closeout_role.request_closeout,
            closeout_processor=self.assembler.registry.get(self.ACTION_ID).processor,
            source_checks=closeout_actions.validate_contractor_closeout_sources,
            source_schemas=self.assembler.SOURCE_SCHEMAS)

    def _configuration(self):
        a = self.assembler
        result = dict(schema_version=self.READER_SCHEMA, action_id=self.ACTION_ID, role=self.ROLE,
            root_field=self.ROOT_FIELD, scope_field=self.SCOPE_FIELD, provider_attribute=self.PROVIDER_ATTRIBUTE,
            condition_kinds=deepcopy(self.CONDITION_KINDS),
            condition_codes=list(self.CONDITION_CODES), run_id=a.organizations.run_id, source_mode=a.source_mode,
            macro_version=a._views.macro_version, policy_version=a.policy_version, model_version=a.model_version,
            snapshot_schema=self.snapshots.SCHEMA,
            read_original=module_factory_descriptor(self.snapshots.get, 'read_original'),
            select_current=module_factory_descriptor(self.select_current, 'select_current'),
            assemble_current=module_factory_descriptor(a.build, 'assemble_current'),
            assemble_selected=module_factory_descriptor(type(self)._assemble_current, 'assemble_selected'),
            condition_reading=module_factory_descriptor(type(self)._condition_reading, 'condition_reading'),
            compare_scope=module_factory_descriptor(type(self)._same_scope, 'compare_scope'),
            read_current=module_factory_descriptor(type(self).__call__, 'read_current'),
            **({'condition_trigger': self.CONDITION_TRIGGER} if self.CONDITION_TRIGGER != 'dependency_change' else {}),
            **({'multi_reference_condition_codes': list(self.MULTI_REF_CONDITION_CODES)}
                if self.MULTI_REF_CONDITION_CODES else {}),
            **({'condition_reference_kind_sequences': deepcopy(self.CONDITION_REF_KIND_SEQUENCES)}
                if self.CONDITION_REF_KIND_SEQUENCES else {}))
        for name, callback in self._closeout_checks().items():
            result[name] = module_factory_descriptor(callback, name)
        if self.ACTION_ID == 'CONTRACTOR-A11':
            result['check_implementations'] = {name: callable_implementation(callback)
                for name, callback in self._closeout_checks().items()}
        return result

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(actual is not original for actual, original in zip(current, self._original_components))
                or self.assembler.ACTION_ID != self.ACTION_ID or not isinstance(self.assembler, self.ASSEMBLER_TYPE)
                or self.assembler.source_mode != 'formal' or self.assembler._views.source_mode != 'formal'
                or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.provider is not getattr(self.assembler, self.PROVIDER_ATTRIBUTE)
                or self._configuration() != self._declared):
            raise TaskConflict('Closeout recovery changed original assembler/source/snapshot/callback bindings')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check, *, history_terminal=False):
        self._check()
        source, code = check.source['identity'], check.condition.condition_code
        kind = self.CONDITION_KINDS.get(code)
        allowed_kinds = (kind,) if isinstance(kind, str) else tuple(kind or ())
        sequence = self.CONDITION_REF_KIND_SEQUENCES.get(code)
        valid_refs = (tuple(ref.kind for ref in check.condition.object_refs) == tuple(sequence) if sequence is not None
            else bool(check.condition.object_refs)
                and (len(check.condition.object_refs) == 1 or code in self.MULTI_REF_CONDITION_CODES)
                and all(ref.kind in allowed_kinds for ref in check.condition.object_refs))
        if (source['action_id'] != self.ACTION_ID or source['role'] != self.ROLE or source['purpose'] != 'action'
                or code not in self.CONDITION_CODES or check.condition.trigger != self.CONDITION_TRIGGER
                or not valid_refs
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Closeout recovery substitutes original wait or private recipient')
        identity = TaskIdentity(**source)
        snapshot = self.snapshots.get(identity)
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Closeout recovery changes original persisted invocation')
        original_context = ActionContext.model_validate(snapshot['context'])
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, self.SELECTION_TYPE) or not isinstance(selected.history_ref, Reference):
            raise TaskConflict('Closeout recovery requires typed actual history selection')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context, ref = request.context, selected.history_ref.model_copy(deep=True)
        action_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
                or context.execution_mode != 'llm' or not self._same_scope(context.scope, original_context.scope)
                or context.business_time != check.signal.business_time
                or context.business_time.clock_ref != original_context.business_time.clock_ref
                or context.business_time.offset < original_context.business_time.offset
                or (context.operation_id != source['request_id'] if history_terminal else context.operation_id == source['request_id'])
                or history_terminal and (action_input != original_input or context.actor_id != original_context.actor_id
                    or context.function_ref != original_context.function_ref)
                or self.ROOT_FIELD is not None and getattr(action_input, self.ROOT_FIELD).key()[:2] != getattr(original_input, self.ROOT_FIELD).key()[:2]
                or self.SCOPE_FIELD is not None and not self._same_scope(getattr(action_input, self.SCOPE_FIELD), getattr(original_input, self.SCOPE_FIELD))
                or ref.key()[:2] != check.condition.object_refs[0].key()[:2]
                or request.execution_path not in {None, registration.strategy}
                or not {value.key() for value in (*walk_references(original_input), *walk_references(action_input),
                    ref, *check.condition.object_refs)} <= {value.key() for value in context.visible_refs}):
            raise TaskConflict('Closeout recovery replaces original contract/scope or selected current/query authorization')
        prepared = self._assemble_current(context, action_input, history_terminal)
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Closeout recovery substitutes another authorized Contractor')
            for source_ref in (*walk_references(original_input), ref, *check.condition.object_refs):
                self._resolve_recovery_ref(prepared.reading, source_ref,
                    original_input=original_input, action_input=action_input)
            return self._condition_reading(prepared, original_context, snapshot, ref, selected)
        finally:
            prepared.reading.recheck()
            self._check()
            if (self.snapshots.get(identity) != snapshot
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Closeout recovery changed original snapshot or assembled current input/context')

    def _assemble_current(self, context, action_input, history_terminal):
        return self.assembler.build(context, **action_input.model_dump(mode='json'))

    def _condition_reading(self, prepared, original_context, snapshot, ref, selected):
        return self.READING_TYPE(prepared.context, prepared.reading, original_context,
            deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'), ref)

    def _resolve_recovery_ref(self, reading, ref, *, original_input, action_input):
        return reading.resolve(ref)

    @staticmethod
    def _same_scope(current, original):
        return current == original


def build_assembled_contractor_closeout_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import ObservationContinuationDispatcher
    from src.actions.contracts.common import ResumeCondition
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal

    callbacks = dict(read_guard=read_guard, validate_relation=validate_relation, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate)
    if not all(callable(value) for value in callbacks.values()):
        raise ValueError('Closeout recovery requires actual guarded history and successor callbacks')
    reader = reader or ContractorCloseoutRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if (not isinstance(reader, ContractorCloseoutRecoveryReader) or reader.assembler is not assembler
            or reader.snapshots.store is not store or reader.select_current is not select_current):
        raise ValueError('Closeout recovery requires its original same-store reader')
    declared = {name: module_factory_descriptor(value, name) for name, value in callbacks.items()}
    profiles = [reader.PROFILE_FACTORY(reader, validate_relation, code) for code in reader.CONDITION_CODES]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in reader.CONDITION_CODES]
        if len(conditions) != 1:
            raise TaskConflict('Closeout recovery requires its original single history wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = reader(deepcopy(check))
        try:
            profile = reader.PROFILE_FACTORY(lambda _: selected, validate_relation, conditions[0].condition_code)
            if (profile.evaluate(check) != 'ready' or preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('Closeout successor replaces current source/input/context or loses history readiness')
            result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
            check_binding()
            return result is True
        finally:
            selected.reading.recheck()

    dispatcher = ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate_current, action_ids={reader.ACTION_ID})
    original_registry = journal.registry

    def check_binding():
        reader._check()
        if (dispatcher.inbox is not inbox or dispatcher.journal is not journal or journal.store is not store
                or journal.registry is not original_registry or dispatcher.project_signal is not project_signal
                or dispatcher.prepare is not prepare_current or dispatcher.revalidate is not revalidate_current
                or dispatcher.action_ids != frozenset({reader.ACTION_ID})
                or any(module_factory_descriptor(value, name) != declared[name] for name, value in callbacks.items())):
            raise TaskConflict('Closeout recovery changed original journal or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Closeout recovery changes original run or recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id=reader.ACTION_ID, role=reader.ROLE)
