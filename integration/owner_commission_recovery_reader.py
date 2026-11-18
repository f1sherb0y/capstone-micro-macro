"""Bind original A04 waits to saved evidence and current authorized procurement."""
from dataclasses import dataclass

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings
from integration.owner_commission_actions import OwnerCommissionActionAssembler, validate_owner_commission_sources
from integration.owner_commission_results import OwnerCommissionResultWorker
from integration.owner_saved_wait_recovery_reader import OwnerSavedWaitRecoveryReader
from src.actions.roles.owner_commission import commission_services
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_commission_conditions import CODE, OwnerCommissionConditionReading, owner_original_commission_profile


class OwnerCommissionRecoverySettings(OwnerContinuationRecoverySettings):
    """Versioned actual sources; a commission wait has no terminal archive."""


@dataclass(frozen=True)
class OwnerCommissionCurrentSelection(ContractorCloseoutCurrentSelection):
    """Explicit new invocation and actual current ProcurementProfile version."""


@dataclass(frozen=True)
class OwnerCommissionRecoveryBindings(OwnerContinuationRecoveryBindings):
    assembler: OwnerCommissionActionAssembler
    snapshots: InvocationSnapshotStore

    def __post_init__(self):
        if (type(self.assembler) is not OwnerCommissionActionAssembler
                or not isinstance(self.snapshots, InvocationSnapshotStore)
                or not all(callable(value) for value in super().components()[1:])):
            raise ValueError('Owner commission recovery requires its actual assembler, same journal and callbacks')
        object.__setattr__(self, '_reader', OwnerCommissionRecoveryReader(assembler=self.assembler,
            snapshots=self.snapshots, select_current=self.select_current))

    def components(self):
        return (*super().components(), self.snapshots, self.snapshots.store)


class OwnerCommissionRecoveryReader(OwnerSavedWaitRecoveryReader):
    ACTION_ID = 'OWN-A04'
    ROLE = 'Owner'
    ASSEMBLER_TYPE = OwnerCommissionActionAssembler
    SELECTION_TYPE = OwnerCommissionCurrentSelection
    READING_TYPE = OwnerCommissionConditionReading
    PROFILE_FACTORY = staticmethod(owner_original_commission_profile)
    RESULT_WORKER_TYPE = OwnerCommissionResultWorker
    VALIDATE_ORIGINAL_SOURCES = staticmethod(validate_owner_commission_sources)
    ROOT_FIELD = 'service_scope_ref'
    SCOPE_FIELD = 'scope_ref'
    READER_SCHEMA = 'owner-commission-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: ('ProcurementProfile', 'ServiceScope', 'ManagementCapacity')}
    CONDITION_REF_KIND_SEQUENCES = {CODE: ('ProcurementProfile', 'ServiceScope', 'ManagementCapacity')}
    _same_scope = staticmethod(same_closeout_scope)

    def _components(self):
        return (*super()._components(), commission_services)

    def _configuration(self):
        result = super()._configuration()
        result['commission_checks'] = module_factory_descriptor(commission_services, 'commission_checks')
        return result


def build_assembled_owner_commission_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or OwnerCommissionRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, OwnerCommissionRecoveryReader):
        raise ValueError('Owner commission recovery requires its actual typed same-journal reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
