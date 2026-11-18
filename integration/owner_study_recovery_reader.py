"""Bind original A02 waits to their saved result and actual current study input."""
from dataclasses import dataclass

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings
from integration.owner_saved_wait_recovery_reader import OwnerSavedWaitRecoveryReader
from integration.owner_study_actions import OwnerStudyActionAssembler, validate_owner_study_sources
from integration.owner_study_results import OwnerStudyResultWorker
from src.actions.roles.owner_study import authorize_study
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_study_conditions import CODE, OwnerStudyConditionReading, owner_original_study_profile


class OwnerStudyRecoverySettings(OwnerContinuationRecoverySettings):
    """Versioned current source policy; no terminal archive for a study wait."""


@dataclass(frozen=True)
class OwnerStudyCurrentSelection(ContractorCloseoutCurrentSelection):
    """Explicit new invocation and actual current StudyProfile version."""


@dataclass(frozen=True)
class OwnerStudyRecoveryBindings(OwnerContinuationRecoveryBindings):
    assembler: OwnerStudyActionAssembler
    snapshots: InvocationSnapshotStore

    def __post_init__(self):
        if (type(self.assembler) is not OwnerStudyActionAssembler
                or not isinstance(self.snapshots, InvocationSnapshotStore)
                or not all(callable(value) for value in super().components()[1:])):
            raise ValueError('Owner study recovery requires its actual assembler, same journal and callbacks')
        object.__setattr__(self, '_reader', OwnerStudyRecoveryReader(assembler=self.assembler,
            snapshots=self.snapshots, select_current=self.select_current))

    def components(self):
        return (*super().components(), self.snapshots, self.snapshots.store)


class OwnerStudyRecoveryReader(OwnerSavedWaitRecoveryReader):
    ACTION_ID = 'OWN-A02'
    ROLE = 'Owner'
    ASSEMBLER_TYPE = OwnerStudyActionAssembler
    SELECTION_TYPE = OwnerStudyCurrentSelection
    READING_TYPE = OwnerStudyConditionReading
    PROFILE_FACTORY = staticmethod(owner_original_study_profile)
    RESULT_WORKER_TYPE = OwnerStudyResultWorker
    VALIDATE_ORIGINAL_SOURCES = staticmethod(validate_owner_study_sources)
    ROOT_FIELD = 'case_ref'
    SCOPE_FIELD = None
    READER_SCHEMA = 'owner-study-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: ('StudyProfile', 'FundingPosition')}
    CONDITION_REF_KIND_SEQUENCES = {CODE: ('StudyProfile', 'FundingPosition')}
    _same_scope = staticmethod(same_closeout_scope)

    def _components(self):
        return (*super()._components(), authorize_study)

    def _configuration(self):
        result = super()._configuration()
        result['study_checks'] = module_factory_descriptor(authorize_study, 'study_checks')
        return result


def build_assembled_owner_study_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or OwnerStudyRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, OwnerStudyRecoveryReader):
        raise ValueError('Owner study recovery requires its actual typed same-journal reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
