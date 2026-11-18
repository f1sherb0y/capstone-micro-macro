"""Read original Bank A07 payment commands for guarded wait recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.bank_execution_actions import BankExecutionActionAssembler
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_execution_objects import BankExecutionReceiptView, BankExecutionSavedView
from src.actions.contracts.common import Reference, ResumeCondition
from src.coordination.bank_execution_conditions import BankExecutionConditionReading, bank_original_payment_command_profile
from src.coordination.continuations import ConditionCheck
from src.coordination.tasks import TaskConflict, task_digest


_CODE = 'query_original_payment_command_before_new_execution'


@dataclass(frozen=True)
class BankPaymentCommandCurrentSelection:
    request: RoleContractInvocation
    execution_refs: tuple[Reference, ...]


class BankPaymentCommandReader:
    """Assemble an authorized existing-command input without executing payment.

    The host explicitly selects current versions and holds the original source,
    authority, inbox and journal guard. Native history authentication remains
    independent; a scheduling event never establishes receipt or money facts.
    """
    ACTION_ID = 'BANK-A07'

    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, BankExecutionActionAssembler) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Bank payment command reader requires original formal A07 assembler and selector')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            assembler._views.schemas, assembler.methods, self.select_current, *assembler.decision_strategies)

    def _configuration(self):
        return {'schema_version': 'bank-payment-command-reader.v1', 'action_id': self.ACTION_ID,
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'policy_version': self.assembler.policy_version,
            'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or self.assembler.ACTION_ID != 'BANK-A07' or self.ACTION_ID != self.assembler.ACTION_ID
                or self.assembler.source_mode != 'formal'
                or self.assembler._views.provider is not self.assembler.provider
                or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.macro_version != self.assembler.macro_version
                or self.assembler._views.source_mode != 'formal' or self._configuration() != self._declared):
            raise TaskConflict('Bank payment command reader changed original source/model components or declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'event'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'PaymentExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Bank payment command reader changes original condition, recipient or command selection')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, BankPaymentCommandCurrentSelection) or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
            raise TaskConflict('Bank payment command reader requires typed current request and explicit execution versions')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        refs = tuple(ref.model_copy(deep=True) for ref in selected.execution_refs)
        registration = self.assembler.registry.get(self.ACTION_ID)
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or len(refs) != len(old_refs) or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}
                or not {ref.key() for ref in (*old_refs, *refs)} <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Bank payment command reader requires visible original/current commands and a fresh formal context')
        action_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (action_input.operation_context.kind != 'existing'
                or [ref.key() for ref in action_input.operation_context.execution_refs] != [ref.key() for ref in refs]):
            raise TaskConflict('Bank wait recovery must use selected existing executions without initiating a new payment')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            if prepared.reading.organization_id != source['organization_id']:
                raise TaskConflict('Bank payment command reader substitutes another authorized lender')
            originals = {(ref.kind, ref.id): ref for ref in old_refs}
            for ref in refs:
                old_ref = originals[(ref.kind, ref.id)]
                original, current = prepared.reading.resolve(old_ref), prepared.reading.resolve(ref)
                if (not isinstance(original, BankExecutionSavedView) or not isinstance(current, BankExecutionSavedView)
                        or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                        or current.lender_id != source['organization_id']
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'lender_id', 'borrower_id', 'arrangement_ref', 'approval_ref', 'path_ref',
                            'command_id', 'business_key', 'lines', 'scope'))
                        or original.dispatch_state == 'dispatched' and current.dispatch_state != 'dispatched'):
                    raise TaskConflict('Bank payment reader changes original payment identity, split, scope or known dispatch')
                current_receipts = {(item.kind, item.id): item for item in current.receipt_refs}
                if len(current_receipts) != len(current.receipt_refs):
                    raise TaskConflict('Bank payment reader repeats a physical receipt in current command history')
                for receipt_ref in original.receipt_refs:
                    latest_ref = current_receipts.get((receipt_ref.kind, receipt_ref.id))
                    if latest_ref is None:
                        raise TaskConflict('Bank payment reader removes an original command receipt')
                    old_receipt = prepared.reading.resolve(receipt_ref)
                    receipt = prepared.reading.resolve(latest_ref)
                    if (not isinstance(old_receipt, BankExecutionReceiptView) or not isinstance(receipt, BankExecutionReceiptView)
                            or old_receipt.ref.key() != receipt_ref.key() or receipt.ref.key() != latest_ref.key()
                            or (receipt.execution_ref.kind, receipt.execution_ref.id) != (ref.kind, ref.id)
                            or (old_receipt.execution_ref.kind, old_receipt.execution_ref.id) != (old_ref.kind, old_ref.id)
                            or any(getattr(receipt, field) != getattr(current, field) for field in (
                                'lender_id', 'borrower_id', 'arrangement_ref', 'approval_ref', 'path_ref', 'command_id', 'business_key'))
                            or any(getattr(old_receipt, field) != getattr(receipt, field) for field in (
                                'lender_id', 'borrower_id', 'arrangement_ref', 'approval_ref', 'path_ref',
                                'command_id', 'business_key', 'event_id', 'sequence', 'semantics', 'scope'))
                            or old_receipt.status != 'unknown' and any(
                                getattr(old_receipt, field) != getattr(receipt, field) for field in (
                                    'status', 'observed_at', 'lines', 'confirmed_unexecuted_amount'))):
                        raise TaskConflict('Bank payment reader replaces original receipt identity or known payment history')
            return BankExecutionConditionReading(prepared.context, prepared.reading, refs,
                prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck()
            self._check()
            if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Bank payment reader changed its current input, context or source snapshot')


def build_assembled_bank_payment_command_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one original source/authority/inbox/journal guard through recovery."""
    from integration.bank_execution_wait_recovery import BankExecutionWaitRecoveryBridge
    from integration.task_continuation import build_bank_execution_continuation_dispatcher

    reader = BankPaymentCommandReader(assembler=assembler, select_current=select_current)
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Bank payment recovery requires actual same-run source/authority/journal guard and validators')
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
            raise TaskConflict('Bank payment recovery requires its original emitted command wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        current = reader(check)
        try:
            profile = bank_original_payment_command_profile(lambda _: current, validate_relation)
            if profile.evaluate(check) != 'ready':
                raise TaskConflict('Bank payment query is no longer complete and available before successor registration')
            validated_input = assembler.registry.get('BANK-A07').contract.validate_input(deepcopy(preparation.next_input))
            if (validated_input.model_dump(mode='json') != preparation.next_input
                    or preparation.next_input != current.action_input
                    or preparation.next_context != current.context.model_dump(mode='json')):
                raise TaskConflict('Bank payment successor substitutes selected current context, arrangement, executions or receipts')
            current.reading.recheck()
            result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
            check_binding()
            return result
        finally:
            current.reading.recheck()

    dispatcher = build_bank_execution_continuation_dispatcher(inbox=inbox, store=store,
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
                or dispatcher.revalidate is not revalidate_current or dispatcher.action_ids != frozenset({'BANK-A07'})):
            raise TaskConflict('Bank payment recovery changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Bank payment recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return BankExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='BANK-A07')
