"""Reassemble original A13 research task waits through actual guarded sources."""
from dataclasses import dataclass, replace

from integration.engineer_research_actions import EngineerResearchActionAssembler
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from src.actions.roles.engineer_research import assess_preliminary_options, recheck_original_engineer_research_wait
from src.coordination.engineer_research_conditions import (
    CODE, EngineerResearchConditionReading, engineer_original_research_profile,
)
from src.coordination.invocations import InvocationSnapshotStore


class EngineerResearchRecoverySettings(EngineerSubmissionRecoverySettings):
    """Actual research task queries; no terminal archive."""


@dataclass(frozen=True)
class EngineerResearchCurrentSelection(ContractorCloseoutCurrentSelection):
    """Current original research task and separately selected authorized research input."""


@dataclass(frozen=True)
class EngineerResearchRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Actual guarded task readiness, native delegation and successor callbacks."""


class EngineerResearchRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ENGINEER-A13'
    ROLE = 'Engineer'
    ASSEMBLER_TYPE = EngineerResearchActionAssembler
    SELECTION_TYPE = EngineerResearchCurrentSelection
    READING_TYPE = EngineerResearchConditionReading
    PROFILE_FACTORY = staticmethod(engineer_original_research_profile)
    ROOT_FIELD = 'task_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'engineer-research-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: 'Task'}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            assess_preliminary_options, recheck_original_engineer_research_wait)

    def _configuration(self):
        result = super()._configuration()
        result['research_checks'] = module_factory_descriptor(assess_preliminary_options, 'research_checks')
        result['historical_task_checks'] = module_factory_descriptor(recheck_original_engineer_research_wait, 'historical_task_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal:
            raise ValueError('Research tasks must resume the actual bounded processor; no terminal archive is available')
        selected = super().__call__(check, history_terminal=False)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)


def build_assembled_engineer_research_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or EngineerResearchRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, EngineerResearchRecoveryReader):
        raise ValueError('Research recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
