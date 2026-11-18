"""Bind BANK-A08 original notice delivery to guarded actual monitoring sources."""
from copy import deepcopy
from dataclasses import dataclass

from integration.bank_debt_reader import BankDebtReader, _build_assembled_bank_snapshot_dispatcher
from integration.bank_monitoring_actions import BankMonitoringActionAssembler
from integration.bank_execution_wait_recovery import BankExecutionWaitRecoveryBridge
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.coordination.bank_monitoring_conditions import NOTICE_CODE, BankMonitoringConditionReading, bank_original_notice_delivery_profile
from src.coordination.bank_monitoring_terminal import EXISTING_CODE, BankExistingMeasureReading, bank_existing_measure_profile
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class BankMonitoringCurrentSelection:
    request: RoleContractInvocation


@dataclass(frozen=True)
class BankMonitoringTerminalSelection:
    request: RoleContractInvocation
    notice_refs: tuple[Reference, ...]


class BankMonitoringNoticeReader(BankDebtReader):
    ACTION_ID = 'BANK-A08'
    CONDITION_CODE = NOTICE_CODE
    TRIGGER = 'event'
    ASSEMBLER_TYPE = BankMonitoringActionAssembler
    SELECTION_TYPE = BankMonitoringCurrentSelection
    READING_TYPE = BankMonitoringConditionReading
    READER_SCHEMA = 'bank-monitoring-notice-reader.v1'

    def validate_original_wait(self, check, original_input):
        refs = check.condition.object_refs
        if (not refs or any(ref.kind != 'CovenantNotice' for ref in refs)
                or len({ref.key() for ref in refs}) != len(refs)
                or not {ref.key() for ref in refs} <= {ref.key() for ref in original_input.notice_refs}):
            raise TaskConflict('Monitoring reader replaces the original explicit notice-delivery gate')


class BankExistingMeasureReader(BankMonitoringNoticeReader):
    CONDITION_CODE = EXISTING_CODE
    SELECTION_TYPE = BankMonitoringTerminalSelection
    READING_TYPE = BankExistingMeasureReading
    READER_SCHEMA = 'bank-existing-monitoring-measure-reader.v1'
    CONDITION_CODES = (NOTICE_CODE, EXISTING_CODE)

    def _configuration(self):
        return super()._configuration() | {'condition_codes': list(self.CONDITION_CODES)}

    def accepts_condition(self, code):
        return code in self.CONDITION_CODES

    def query_refs(self, selected):
        return selected.notice_refs

    def __call__(self, check, *, execution_terminal=False):
        self._check()
        source = check.source['identity']
        if (execution_terminal is not True or source['action_id'] != self.ACTION_ID
                or source['role'] != 'Bank' or source['purpose'] != 'action'
                or not self.accepts_condition(check.condition.condition_code)
                or check.condition.trigger != self.TRIGGER or check.signal.run_id != source['run_id']
                or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Existing monitoring measure reading requires explicit original terminal observation')
        identity = TaskIdentity(**source)
        snapshot = self.snapshots.get(identity)
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Existing measure reading replaces original persisted invocation')
        original_context = ActionContext.model_validate(snapshot['context'])
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        self.validate_original_wait(check, original_input)
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, self.SELECTION_TYPE):
            raise TaskConflict('Original Bank terminal reading requires its typed actual query selector')
        queried_refs = self.query_refs(selected)
        if (not isinstance(queried_refs, tuple) or any(not isinstance(ref, Reference) for ref in queried_refs)):
            raise TaskConflict('Existing measure reading requires typed actual original-notice query versions')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        queries = deepcopy(queried_refs)
        context = request.context
        if (request.action_input != snapshot['action_input'] or context.run_id != source['run_id']
                or context.contract_ref != original_context.contract_ref or context.scope != original_context.scope
                or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
                or context.operation_id != source['request_id'] or context.business_time != check.signal.business_time
                or context.business_time.clock_ref != original_context.business_time.clock_ref
                or context.business_time.offset < original_context.business_time.offset or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or not {ref.key() for ref in (*walk_references(original_input), *queries)}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Existing measure reading replaces original input, actor, scope or current query visibility')
        prepared = self.assembler.build(context, **deepcopy(snapshot['action_input']))
        try:
            for ref in queries:
                prepared.reading.resolve(ref)
            return self.READING_TYPE(prepared.context, prepared.reading, original_context,
                original_input, prepared.action_input, queries)
        finally:
            prepared.reading.recheck()
            self._check()
            if self.snapshots.get(identity) != snapshot:
                raise TaskConflict('Existing measure reading rewrote original persisted input/context')


@dataclass(frozen=True)
class BankMonitoringRecoveryBridge(BankExecutionWaitRecoveryBridge):
    terminal_reader: object = None
    native_validator: object = None

    def _components(self):
        return (*super()._components(), self.terminal_reader, self.native_validator)

    def _check(self):
        super()._check()
        self.terminal_reader._check()


def build_assembled_bank_monitoring_notice_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    reader = BankMonitoringNoticeReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    bridge = _build_assembled_bank_snapshot_dispatcher(inbox=inbox, store=store, reader=reader,
        condition_factory=bank_original_notice_delivery_profile, read_guard=read_guard,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare,
        revalidate=revalidate, extra_profiles=(bank_existing_measure_profile(), *extra_profiles))
    terminal_reader = BankExistingMeasureReader(assembler=assembler, snapshots=reader.snapshots,
        select_current=select_current)
    return BankMonitoringRecoveryBridge(dispatch=bridge.dispatch, dispatcher=bridge.dispatcher,
        read_guard=bridge.read_guard, check_binding=bridge.check_binding, action_id='BANK-A08',
        terminal_reader=terminal_reader, native_validator=validate_relation)
