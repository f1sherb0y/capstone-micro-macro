"""Read original operating execution without repeating policy, budgets or allocations."""
from dataclasses import dataclass

from integration.owner_operating_actions import OwnerOperatingActionAssembler
from integration.owner_continuation_terminal import OwnerContinuationTerminalReader, _reconcile_owner_terminal_wait
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.coordination.owner_operating_terminal import EXECUTION_CODE, OwnerOperatingTerminalReading, check_owner_operating_terminal


@dataclass(frozen=True)
class OwnerOperatingTerminalSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class OwnerOperatingTerminalReader(OwnerContinuationTerminalReader):
    ACTION_ID = 'OWN-A15'
    ASSEMBLER_TYPE = OwnerOperatingActionAssembler
    CONDITION_CODE = EXECUTION_CODE
    EXECUTION_KIND = 'OwnerOperatingExecution'
    SELECTION_TYPE = OwnerOperatingTerminalSelection
    READING_TYPE = OwnerOperatingTerminalReading
    READER_SCHEMA = 'owner-operating-terminal-reader.v1'


def reconcile_owner_operating_execution(*, identity, signal, bridge, validate_relation):
    return _reconcile_owner_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_owner_operating_terminal,
        action_id='OWN-A15', condition_code=EXECUTION_CODE)
