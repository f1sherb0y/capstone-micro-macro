"""Reassemble original Owner screening waits from its same-run invocation journal."""
from dataclasses import dataclass

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutCurrentSelection,
    build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.owner_observation_actions import OwnerObservationActionAssembler, validate_owner_observation_sources
from integration.owner_observation_results import OwnerObservationResultWorker
from integration.owner_saved_wait_recovery_reader import OwnerSavedWaitRecoveryReader
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings
from src.actions.roles.owner import observe_opportunities
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_observation_conditions import (
    CODE, OwnerObservationConditionReading, owner_original_observation_profile,
)


class OwnerObservationRecoverySettings(OwnerContinuationRecoverySettings):
    """Actual source and policy versions; screening has no terminal archive."""


@dataclass(frozen=True)
class OwnerObservationCurrentSelection(ContractorCloseoutCurrentSelection):
    """Explicit actual current capacity version and independently authorized invocation."""


@dataclass(frozen=True)
class OwnerObservationRecoveryBindings(OwnerContinuationRecoveryBindings):
    assembler: OwnerObservationActionAssembler
    snapshots: InvocationSnapshotStore

    def __post_init__(self):
        if (type(self.assembler) is not OwnerObservationActionAssembler
                or not isinstance(self.snapshots, InvocationSnapshotStore)
                or not all(callable(value) for value in super().components()[1:])):
            raise ValueError('Owner screening recovery requires original assembler, snapshots and actual callbacks')
        object.__setattr__(self, '_reader', OwnerObservationRecoveryReader(assembler=self.assembler,
            snapshots=self.snapshots, select_current=self.select_current))

    def components(self):
        return (*super().components(), self.snapshots, self.snapshots.store)


class OwnerObservationRecoveryReader(OwnerSavedWaitRecoveryReader):
    ACTION_ID = 'OWN-A01'
    ROLE = 'Owner'
    ASSEMBLER_TYPE = OwnerObservationActionAssembler
    SELECTION_TYPE = OwnerObservationCurrentSelection
    READING_TYPE = OwnerObservationConditionReading
    PROFILE_FACTORY = staticmethod(owner_original_observation_profile)
    RESULT_WORKER_TYPE = OwnerObservationResultWorker
    VALIDATE_ORIGINAL_SOURCES = staticmethod(validate_owner_observation_sources)
    ROOT_FIELD = 'capacity_ref'
    SCOPE_FIELD = 'scope_ref'
    READER_SCHEMA = 'owner-observation-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: 'ManagementCapacity'}
    _same_scope = staticmethod(same_closeout_scope)

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract, observe_opportunities)

    def _configuration(self):
        result = super()._configuration()
        result['screening_checks'] = module_factory_descriptor(observe_opportunities, 'screening_checks')
        return result

def build_assembled_owner_observation_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or OwnerObservationRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, OwnerObservationRecoveryReader):
        raise ValueError('Owner screening recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
