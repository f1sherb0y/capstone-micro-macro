"""Bind original A05 waits to saved evidence and current authorized financing."""
from dataclasses import dataclass

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings
from integration.owner_financing_actions import OwnerFinancingActionAssembler, validate_owner_financing_sources
from integration.owner_financing_results import OwnerFinancingResultWorker
from integration.owner_saved_wait_recovery_reader import OwnerSavedWaitRecoveryReader
from src.actions.roles.owner_financing import plan_financing
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_financing_conditions import CODE, OwnerFinancingConditionReading, owner_original_financing_profile


class OwnerFinancingRecoverySettings(OwnerContinuationRecoverySettings):
    """Versioned actual sources; a financing wait has no terminal archive."""


@dataclass(frozen=True)
class OwnerFinancingCurrentSelection(ContractorCloseoutCurrentSelection):
    """Explicit new invocation and actual current FundingProfile version."""


@dataclass(frozen=True)
class OwnerFinancingRecoveryBindings(OwnerContinuationRecoveryBindings):
    assembler: OwnerFinancingActionAssembler
    snapshots: InvocationSnapshotStore

    def __post_init__(self):
        if (type(self.assembler) is not OwnerFinancingActionAssembler
                or not isinstance(self.snapshots, InvocationSnapshotStore)
                or not all(callable(value) for value in super().components()[1:])):
            raise ValueError('Owner financing recovery requires its actual assembler, same journal and callbacks')
        object.__setattr__(self, '_reader', OwnerFinancingRecoveryReader(assembler=self.assembler,
            snapshots=self.snapshots, select_current=self.select_current))

    def components(self):
        return (*super().components(), self.snapshots, self.snapshots.store)


class OwnerFinancingRecoveryReader(OwnerSavedWaitRecoveryReader):
    ACTION_ID = 'OWN-A05'
    ROLE = 'Owner'
    ASSEMBLER_TYPE = OwnerFinancingActionAssembler
    SELECTION_TYPE = OwnerFinancingCurrentSelection
    READING_TYPE = OwnerFinancingConditionReading
    PROFILE_FACTORY = staticmethod(owner_original_financing_profile)
    RESULT_WORKER_TYPE = OwnerFinancingResultWorker
    VALIDATE_ORIGINAL_SOURCES = staticmethod(validate_owner_financing_sources)
    ROOT_FIELD = 'funding_profile_ref'
    SCOPE_FIELD = 'scope_ref'
    READER_SCHEMA = 'owner-financing-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: ('FundingProfile',)}
    CONDITION_REF_KIND_SEQUENCES = {CODE: ('FundingProfile',)}
    _same_scope = staticmethod(same_closeout_scope)

    def _components(self):
        return (*super()._components(), plan_financing)

    def _configuration(self):
        result = super()._configuration()
        result['financing_checks'] = module_factory_descriptor(plan_financing, 'financing_checks')
        return result


def build_assembled_owner_financing_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or OwnerFinancingRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, OwnerFinancingRecoveryReader):
        raise ValueError('Owner financing recovery requires its actual typed same-journal reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
