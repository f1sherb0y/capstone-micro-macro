"""Recover original Owner A12 decisions through the guarded snapshot journal."""
from dataclasses import dataclass
from pydantic import model_serializer

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.owner_closeout_actions import OwnerCloseoutActionAssembler
from integration.module_host import module_factory_descriptor
from integration.owner_continuation_execution_reader import (
    OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings,
)
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.owner_closeout_conditions import (
    CODE, OwnerCloseoutConditionReading, owner_original_closeout_profile, same_closeout_scope,
)


@dataclass(frozen=True)
class OwnerCloseoutCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


class OwnerCloseoutRecoverySettings(OwnerContinuationRecoverySettings):
    terminal_closeout_history_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = super().preserve_original_configuration(handler)
        if not self.terminal_closeout_history_enabled:
            result.pop('terminal_closeout_history_enabled', None)
        return result


@dataclass(frozen=True)
class OwnerCloseoutRecoveryBindings(OwnerContinuationRecoveryBindings):
    assembler: OwnerCloseoutActionAssembler
    snapshots: InvocationSnapshotStore

    def __post_init__(self):
        if (not isinstance(self.assembler, OwnerCloseoutActionAssembler)
                or not isinstance(self.snapshots, InvocationSnapshotStore)
                or not all(callable(value) for value in super().components()[1:])):
            raise ValueError('Owner closeout recovery requires its actual assembler, snapshots and callbacks')
        object.__setattr__(self, '_reader', OwnerCloseoutRecoveryReader(assembler=self.assembler,
            snapshots=self.snapshots, select_current=self.select_current))

    def components(self):
        return (*super().components(), self.snapshots, self.snapshots.store)


class OwnerCloseoutRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'OWN-A12'
    ROLE = 'Owner'
    ASSEMBLER_TYPE = OwnerCloseoutActionAssembler
    SELECTION_TYPE = OwnerCloseoutCurrentSelection
    READING_TYPE = OwnerCloseoutConditionReading
    PROFILE_FACTORY = staticmethod(owner_original_closeout_profile)
    ROOT_FIELD = None
    SCOPE_FIELD = 'scope_ref'
    READER_SCHEMA = 'owner-closeout-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: 'OwnerCloseoutDecision'}
    _same_scope = staticmethod(same_closeout_scope)

    def _configuration(self):
        return super()._configuration() | {
            'execution_condition': module_factory_descriptor(self.PROFILE_FACTORY, 'execution_condition')}


def build_assembled_owner_closeout_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or OwnerCloseoutRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, OwnerCloseoutRecoveryReader):
        raise ValueError('Owner closeout requires its original same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
