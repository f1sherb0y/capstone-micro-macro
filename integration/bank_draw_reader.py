"""Read actual original BANK-A06 batches without scheduling another approval."""
from dataclasses import dataclass

from integration.bank_debt_reader import _build_assembled_bank_snapshot_dispatcher
from integration.bank_draw_actions import BankDrawActionAssembler
from integration.bank_monitoring_reader import BankExistingMeasureReader, BankMonitoringRecoveryBridge
from integration.bank_monitoring_terminal import _reconcile_bank_terminal_wait
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.coordination.bank_draw_conditions import (
    DRAW_PREFIX, BankDrawBatchReading, BankDrawBatchRegistry, check_original_draw_batch,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class BankDrawBatchTerminalSelection:
    request: RoleContractInvocation
    capacity_ref: Reference


class BankDrawBatchReader(BankExistingMeasureReader):
    ACTION_ID = 'BANK-A06'
    CONDITION_CODE = DRAW_PREFIX
    CONDITION_CODES = (DRAW_PREFIX,)
    ASSEMBLER_TYPE = BankDrawActionAssembler
    SELECTION_TYPE = BankDrawBatchTerminalSelection
    READING_TYPE = BankDrawBatchReading
    READER_SCHEMA = 'bank-original-draw-batch-reader.v1'

    def accepts_condition(self, code):
        return code.startswith(DRAW_PREFIX) and bool(code[len(DRAW_PREFIX):])

    def query_refs(self, selected):
        return (selected.capacity_ref,)

    def validate_original_wait(self, check, original_input):
        refs = check.condition.object_refs
        if (not refs or any(ref.kind != 'DrawBatch' for ref in refs)
                or len({ref.key()[:2] for ref in refs}) != len(refs)):
            raise TaskConflict('Original draw batch reader replaces its explicit existing batch identities')


@dataclass(frozen=True)
class BankDrawBatchRecoveryBridge(BankMonitoringRecoveryBridge):
    """Reuse the same fixed original terminal reader/native/journal binding."""


def build_assembled_bank_draw_batch_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    reader = BankDrawBatchReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    bridge = _build_assembled_bank_snapshot_dispatcher(inbox=inbox, store=store, reader=reader,
        condition_factory=None, condition_registry=BankDrawBatchRegistry(extra_profiles),
        read_guard=read_guard, validate_relation=validate_relation, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate)
    return BankDrawBatchRecoveryBridge(dispatch=bridge.dispatch, dispatcher=bridge.dispatcher,
        read_guard=bridge.read_guard, check_binding=bridge.check_binding, action_id='BANK-A06',
        terminal_reader=reader, native_validator=validate_relation)


def reconcile_original_draw_batch(*, identity, signal, bridge, validate_relation):
    return _reconcile_bank_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_original_draw_batch,
        proof=lambda resolution: (resolution['batches'], resolution['executions']), action_id='BANK-A06',
        accepts_condition=lambda code: code.startswith(DRAW_PREFIX) and bool(code[len(DRAW_PREFIX):]))
