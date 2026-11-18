"""Bind original debt resolution query to current authorized terminal observations."""
from dataclasses import dataclass

from integration.bank_resolution_actions import BankResolutionActionAssembler
from integration.bank_monitoring_reader import BankExistingMeasureReader
from integration.bank_monitoring_terminal import _reconcile_bank_terminal_wait
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.actions.implementation import callable_implementation
from src.coordination import bank_resolution_terminal as resolution_terminal
from src.coordination.bank_resolution_terminal import (
    EXECUTION_CODE, BankResolutionTerminalReading, check_bank_resolution_terminal,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class BankResolutionTerminalSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class BankResolutionTerminalReader(BankExistingMeasureReader):
    ACTION_ID = 'BANK-A10'
    CONDITION_CODE = EXECUTION_CODE
    CONDITION_CODES = (EXECUTION_CODE,)
    TRIGGER = 'dependency_change'
    ASSEMBLER_TYPE = BankResolutionActionAssembler
    SELECTION_TYPE = BankResolutionTerminalSelection
    READING_TYPE = BankResolutionTerminalReading
    READER_SCHEMA = 'bank-resolution-terminal-reader.v2'

    def _components(self):
        return (*super()._components(), check_bank_resolution_terminal,
            resolution_terminal.check_original_resolution_payments)

    def _configuration(self):
        return super()._configuration() | {'terminal_implementation': {
            'resolution': callable_implementation(check_bank_resolution_terminal),
            'original_payments': callable_implementation(resolution_terminal.check_original_resolution_payments)}}

    def query_refs(self, selected):
        return (selected.execution_ref,)

    def validate_original_wait(self, check, original_input):
        if tuple(ref.kind for ref in check.condition.object_refs) != ('DebtResolutionExecution',):
            raise TaskConflict('Resolution terminal reading replaces original resolution execution gate')


def reconcile_bank_resolution_execution(*, identity, signal, bridge, validate_relation):
    return _reconcile_bank_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_bank_resolution_terminal,
        proof=lambda resolution: resolution['execution'], action_id='BANK-A10',
        accepts_condition=lambda code: code == EXECUTION_CODE)
