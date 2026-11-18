"""Read original Bank A07 cash-shortfall sources without dispatching payment."""
from copy import deepcopy
from dataclasses import dataclass

from integration.bank_payment_command_reader import BankPaymentCommandReader
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ResumeCondition
from src.coordination.bank_funding_conditions import BankFundingConditionReading, bank_currency_path_cash_profile
from src.coordination.continuations import ConditionCheck
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


_CODE = 'actual_same_currency_path_cash_after_original_reservations_available'


@dataclass(frozen=True)
class BankFundingCurrentSelection:
    request: RoleContractInvocation


class BankFundingReader(BankPaymentCommandReader):
    """Recover the original approval from its immutable invocation snapshot.

    The selector supplies the full authorized current input. Original and
    current account/path/approval versions must be explicitly visible. The
    surrounding guard covers their authority, inbox and the original journal;
    native ledger completeness and reservation facts require validation by
    the existing cash condition. No action, method or model executes here.
    """

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(snapshots, InvocationSnapshotStore)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('Bank funding reader requires original same-run invocation snapshots')
        self.snapshots = snapshots
        super().__init__(assembler=assembler, select_current=select_current)

    def _components(self):
        return (*super()._components(), self.snapshots, self.snapshots.store)

    def _configuration(self):
        declared = super()._configuration()
        return {**declared, 'schema_version': 'bank-funding-reader.v1',
            'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original')}

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 2 or {ref.kind for ref in old_refs} != {'Account', 'FundingPath'}):
            raise TaskConflict('Bank funding reader changes original cash condition, recipient or dependencies')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        original_operation = original_input.operation_context
        old = {ref.kind: ref for ref in old_refs}
        if (original_operation.kind != 'initiate' or original_operation.prior_execution_refs or original_input.receipt_refs
                or original_operation.funding_account_ref.key() != old['Account'].key()
                or original_operation.path_ref.key() != old['FundingPath'].key()):
            raise TaskConflict('Bank cash wait differs from its original saved initiation or has existing payment history')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, BankFundingCurrentSelection):
            raise TaskConflict('Bank funding reader requires a typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        action_input = registration.contract.validate_input(deepcopy(request.action_input))
        operation = action_input.operation_context
        if (operation.kind != 'initiate' or operation.prior_execution_refs or action_input.receipt_refs
                or action_input.arrangement_ref.key() != original_input.arrangement_ref.key()
                or (operation.funding_account_ref.kind, operation.funding_account_ref.id) != (old['Account'].kind, old['Account'].id)
                or (operation.path_ref.kind, operation.path_ref.id) != (old['FundingPath'].kind, old['FundingPath'].id)
                or (operation.draw_approval_ref.kind, operation.draw_approval_ref.id) != (
                    original_operation.draw_approval_ref.kind, original_operation.draw_approval_ref.id)
                or operation.model_dump(mode='json', exclude={'draw_approval_ref', 'funding_account_ref', 'path_ref'})
                    != original_operation.model_dump(mode='json', exclude={'draw_approval_ref', 'funding_account_ref', 'path_ref'})):
            raise TaskConflict('Bank cash recovery changes original approval, facility, transfers or initiation branch')
        required = (*old_refs, original_operation.draw_approval_ref,
            operation.funding_account_ref, operation.path_ref, operation.draw_approval_ref)
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or not {ref.key() for ref in required} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Bank funding reader requires original scope, visible old/current sources and fresh formal context')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Bank funding reader substitutes another authorized lender')
            return BankFundingConditionReading(prepared.context, prepared.reading,
                operation.funding_account_ref.model_copy(deep=True), operation.path_ref.model_copy(deep=True),
                original_operation.draw_approval_ref.model_copy(deep=True), operation.draw_approval_ref.model_copy(deep=True),
                prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck()
            self._check()
            if (self.snapshots.get(identity) != snapshot
                    or task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Bank funding reader changed original snapshots or current input/context/source reading')


def build_assembled_bank_funding_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Keep cash recomputation and successor validation in one original guard."""
    from integration.bank_execution_wait_recovery import BankExecutionWaitRecoveryBridge
    from integration.task_continuation import build_bank_funding_continuation_dispatcher

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Bank funding recovery requires actual same-run source/authority/journal guard and validators')
    reader = BankFundingReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions'] if raw['condition_code'] == _CODE]
        if len(conditions) != 1:
            raise TaskConflict('Bank funding recovery requires its original emitted cash wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        current = reader(check)
        try:
            profile = bank_currency_path_cash_profile(lambda _: current, validate_relation)
            if profile.evaluate(check) != 'ready':
                raise TaskConflict('Bank funding is no longer available after restrictions and original reservations')
            validated_input = assembler.registry.get('BANK-A07').contract.validate_input(deepcopy(preparation.next_input))
            if (validated_input.model_dump(mode='json') != preparation.next_input
                    or preparation.next_input != current.action_input
                    or preparation.next_context != current.context.model_dump(mode='json')):
                raise TaskConflict('Bank funding successor substitutes selected current context, approval, path, account or transfers')
            current.reading.recheck()
            result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
            check_binding()
            return result
        finally:
            current.reading.recheck()

    dispatcher = build_bank_funding_continuation_dispatcher(inbox=inbox, store=store,
        read_current=reader, validate_relation=validate_relation, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    original_prepare = dispatcher.prepare

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())
                or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not original_prepare
                or dispatcher.revalidate is not revalidate_current or dispatcher.action_ids != frozenset({'BANK-A07'})):
            raise TaskConflict('Bank funding recovery changed original snapshots, journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Bank funding recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return BankExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='BANK-A07')
