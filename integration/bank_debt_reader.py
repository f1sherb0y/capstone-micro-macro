"""Guard actual BANK-A09 receipt waits and prepare independent fresh successors."""
from copy import deepcopy
from dataclasses import dataclass

from integration.bank_debt_actions import BankDebtActionAssembler
from integration.bank_execution_wait_recovery import BankExecutionWaitRecoveryBridge
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.task_continuation import ObservationContinuationDispatcher
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.roles.bank_debt import account_debt
from src.actions.implementation import callable_implementation
from src.coordination.bank_debt_conditions import DEBT_CODE, BankDebtConditionReading, bank_original_debt_receipt_profile
from src.coordination.continuations import ConditionRegistry, ContinuationJournal
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class BankDebtCurrentSelection:
    request: RoleContractInvocation


class BankDebtReader:
    ACTION_ID = 'BANK-A09'
    CONDITION_CODE = DEBT_CODE
    TRIGGER = 'dependency_change'
    ASSEMBLER_TYPE = BankDebtActionAssembler
    SELECTION_TYPE = BankDebtCurrentSelection
    READING_TYPE = BankDebtConditionReading
    READER_SCHEMA = 'bank-debt-reader.v2'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, self.ASSEMBLER_TYPE) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore)
                or snapshots.store.run_id != assembler.organizations.run_id or not callable(select_current)):
            raise ValueError('Debt recovery requires its original formal assembler, snapshots and actual selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        components = (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler.methods,
            assembler._views, assembler._views.schemas, self.snapshots, self.snapshots.store,
            self.select_current, self.ASSEMBLER_TYPE, self.SELECTION_TYPE, self.READING_TYPE,
            *assembler.decision_strategies)
        if self.ACTION_ID == 'BANK-A09':
            components += (bank_original_debt_receipt_profile, account_debt)
        return components

    def _configuration(self):
        declared = dict(schema_version=self.READER_SCHEMA, action_id=self.ACTION_ID,
            condition_code=self.CONDITION_CODE, trigger=self.TRIGGER,
            run_id=self.snapshots.store.run_id, source_mode=self.assembler.source_mode,
            macro_version=self.assembler.macro_version, policy_version=self.assembler.policy_version,
            model_version=self.assembler.model_version, snapshot_schema=self.snapshots.SCHEMA,
            select_current=module_factory_descriptor(self.select_current, 'select_current'),
            assemble_current=module_factory_descriptor(self.assembler.build, 'assemble_current'),
            read_current=module_factory_descriptor(type(self).__call__, 'read_current'))
        if self.ACTION_ID == 'BANK-A09':
            declared['receipt_condition'] = {
                **module_factory_descriptor(bank_original_debt_receipt_profile, 'receipt_condition'),
                'implementation': callable_implementation(bank_original_debt_receipt_profile)}
            declared['receipt_allocation'] = {
                **module_factory_descriptor(account_debt, 'receipt_allocation'),
                'implementation': callable_implementation(account_debt)}
        return declared

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original) or any(now is not old for now, old in zip(current, self._original))
                or self.assembler.ACTION_ID != self.ACTION_ID or self.assembler.source_mode != 'formal'
                or self.assembler._views.provider is not self.assembler.provider
                or self.assembler._views.source_mode != 'formal' or self._configuration() != self._declared):
            raise TaskConflict('Debt reader changed original assembler, sources, snapshots or callbacks')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def validate_original_wait(self, check, original_input):
        if tuple(check.condition.object_refs) != (original_input.arrangement_ref,):
            raise TaskConflict('Debt reader replaces the original facility wait')

    def __call__(self, check):
        self._check()
        source = check.source['identity']
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != self.CONDITION_CODE or check.condition.trigger != self.TRIGGER
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Debt reader requires original allocation wait and recipient')
        identity = TaskIdentity(**source)
        snapshot = self.snapshots.get(identity)
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Debt reader replaces the original persisted invocation')
        original_context = ActionContext.model_validate(snapshot['context'])
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        self.validate_original_wait(check, original_input)
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, self.SELECTION_TYPE):
            raise TaskConflict('Debt reader requires a typed actual current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        if (context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
                or context.scope != original_context.scope or context.execution_mode != 'llm'
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or request.execution_path not in {None, registration.strategy}
                or not {ref.key() for ref in walk_references(original_input)} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Debt reader replaces original wait, scope or authorized historical visibility')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Debt reader substitutes another original Bank')
            for ref in walk_references(original_input):
                prepared.reading.resolve(ref)
            return self.READING_TYPE(prepared.context, prepared.reading, original_context,
                original_input, prepared.action_input)
        finally:
            prepared.reading.recheck()
            self._check()
            if self.snapshots.get(identity) != snapshot:
                raise TaskConflict('Debt reader changed original persisted input/context')


def build_assembled_bank_debt_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    reader = BankDebtReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    return _build_assembled_bank_snapshot_dispatcher(inbox=inbox, store=store, reader=reader,
        condition_factory=bank_original_debt_receipt_profile, read_guard=read_guard,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare,
        revalidate=revalidate, extra_profiles=extra_profiles)


def _build_assembled_bank_snapshot_dispatcher(*, inbox, store, reader, condition_factory,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=(), condition_registry=None):
    """Reuse the fixed snapshot, guard and journal boundary for explicit Bank routes."""
    callbacks = dict(read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate)
    if not all(callable(callback) for callback in callbacks.values()):
        raise ValueError('Debt recovery requires actual guard, native authentication and successor callbacks')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def check_callbacks():
        reader._check()
        if any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items()):
            raise TaskConflict('Debt recovery changed original guard/native/successor callbacks')

    def authenticate(**kwargs):
        check_binding()
        identity = TaskIdentity(**kwargs['source_identity'])
        snapshot = reader.snapshots.get(identity)
        if (snapshot['context'] != kwargs['original_context'].model_dump(mode='json')
                or snapshot['action_input'] != kwargs['original_action_input']):
            raise TaskConflict('Bank native wait authentication replaces original persisted input/context')
        try:
            return validate_relation(**kwargs)
        finally:
            check_binding()
            if reader.snapshots.get(identity) != snapshot:
                raise TaskConflict('Debt native authentication changed original persisted invocation')

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

    registry = condition_registry if condition_registry is not None else ConditionRegistry([
        condition_factory(reader, authenticate), *extra_profiles])
    journal = ContinuationJournal(store, registry)
    dispatcher = ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate_current, action_ids={reader.ACTION_ID})
    registry = journal.registry

    def check_binding():
        check_callbacks()
        if (dispatcher.inbox is not inbox or dispatcher.journal is not journal or journal.store is not store
                or journal.registry is not registry or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not revalidate_current or dispatcher.project_signal is not project_signal
                or dispatcher.action_ids != frozenset({reader.ACTION_ID})):
            raise TaskConflict('Debt recovery changed original journal, recipient or preparation boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Debt recovery requires the original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return BankExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id=reader.ACTION_ID)
