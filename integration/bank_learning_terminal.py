"""Read and archive actual same-business learning executions without repeating learning."""
from dataclasses import dataclass

from integration.bank_learning_actions import BankLearningActionAssembler
from integration.bank_monitoring_reader import BankExistingMeasureReader
from integration.bank_monitoring_terminal import _reconcile_bank_terminal_wait
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.coordination.bank_learning_terminal import BankLearningTerminalReading, check_bank_learning_terminal, EXECUTION_CODE
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class BankLearningTerminalSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class BankLearningTerminalReader(BankExistingMeasureReader):
    ACTION_ID = 'BANK-A12'
    CONDITION_CODE = EXECUTION_CODE
    CONDITION_CODES = (EXECUTION_CODE,)
    TRIGGER = 'dependency_change'
    ASSEMBLER_TYPE = BankLearningActionAssembler
    SELECTION_TYPE = BankLearningTerminalSelection
    READING_TYPE = BankLearningTerminalReading
    READER_SCHEMA = 'bank-learning-terminal-reader.v1'

    def query_refs(self, selected):
        return (selected.execution_ref,)

    def validate_original_wait(self, check, original_input):
        if tuple(ref.kind for ref in check.condition.object_refs) != ('BankLearningExecution',):
            raise TaskConflict('Learning terminal reading replaces original execution gate')


def reconcile_bank_learning_execution(*, identity, signal, bridge, validate_relation):
    return _reconcile_bank_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_bank_learning_terminal,
        proof=lambda resolution: resolution['execution'], action_id='BANK-A12',
        accepts_condition=lambda code: code == EXECUTION_CODE)
