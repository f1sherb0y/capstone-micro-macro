"""Read actual original finance closeout without scheduling the same closure again."""
from dataclasses import dataclass

from integration.bank_closeout_actions import BankCloseoutActionAssembler
from integration.bank_monitoring_reader import BankExistingMeasureReader
from integration.bank_monitoring_terminal import _reconcile_bank_terminal_wait
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.actions.implementation import callable_implementation
from src.coordination.bank_closeout_terminal import (
    EXECUTION_CODE, check_bank_closeout_terminal, check_original_closeout_ledger,
)
from src.coordination.bank_resolution_terminal import BankResolutionTerminalReading, check_bank_resolution_terminal
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class BankCloseoutTerminalSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class BankCloseoutTerminalReader(BankExistingMeasureReader):
    ACTION_ID = 'BANK-A11'
    CONDITION_CODE = EXECUTION_CODE
    CONDITION_CODES = (EXECUTION_CODE,)
    TRIGGER = 'dependency_change'
    ASSEMBLER_TYPE = BankCloseoutActionAssembler
    SELECTION_TYPE = BankCloseoutTerminalSelection
    READING_TYPE = BankResolutionTerminalReading
    READER_SCHEMA = 'bank-closeout-terminal-reader.v2'

    def _components(self):
        return (*super()._components(), check_bank_closeout_terminal,
            check_original_closeout_ledger, check_bank_resolution_terminal)

    def _configuration(self):
        return super()._configuration() | {'terminal_implementation': {
            'closeout': callable_implementation(check_bank_closeout_terminal),
            'original_ledger': callable_implementation(check_original_closeout_ledger),
            'finance_terminal': callable_implementation(check_bank_resolution_terminal)}}

    def query_refs(self, selected):
        return (selected.execution_ref,)

    def validate_original_wait(self, check, original_input):
        if tuple(ref.kind for ref in check.condition.object_refs) != ('FinanceCloseoutExecution',):
            raise TaskConflict('Closeout terminal reading replaces original finance closeout execution gate')


def reconcile_bank_closeout_execution(*, identity, signal, bridge, validate_relation):
    return _reconcile_bank_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_bank_closeout_terminal,
        proof=lambda resolution: resolution['execution'], action_id='BANK-A11',
        accepts_condition=lambda code: code == EXECUTION_CODE)
