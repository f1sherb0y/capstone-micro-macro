"""Read actual original asset operation without repeating disposition or receipt work."""
from dataclasses import dataclass

from integration.owner_asset_actions import OwnerAssetActionAssembler
from integration.owner_continuation_terminal import OwnerContinuationTerminalReader, _reconcile_owner_terminal_wait
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.coordination.owner_asset_terminal import EXECUTION_CODE, OwnerAssetTerminalReading, check_owner_asset_terminal


@dataclass(frozen=True)
class OwnerAssetTerminalSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class OwnerAssetTerminalReader(OwnerContinuationTerminalReader):
    ACTION_ID = 'OWN-A14'
    ASSEMBLER_TYPE = OwnerAssetActionAssembler
    CONDITION_CODE = EXECUTION_CODE
    EXECUTION_KIND = 'AssetOperationExecution'
    SELECTION_TYPE = OwnerAssetTerminalSelection
    READING_TYPE = OwnerAssetTerminalReading
    READER_SCHEMA = 'owner-asset-terminal-reader.v1'


def reconcile_owner_asset_execution(*, identity, signal, bridge, validate_relation):
    return _reconcile_owner_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_owner_asset_terminal,
        action_id='OWN-A14', condition_code=EXECUTION_CODE)
