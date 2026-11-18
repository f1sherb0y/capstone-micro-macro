"""Reassemble original A04 task and capacity waits through formal planning sources."""
from dataclasses import dataclass, replace

from integration.engineer_planning_actions import EngineerPlanningActionAssembler
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from src.actions.roles.engineer_planning import plan_professional_work, recheck_original_engineer_planning_capacity
from src.coordination.engineer_planning_conditions import (
    TASK_CODE, CAPACITY_CODE, EngineerPlanningConditionReading, engineer_original_planning_profile,
)
from src.coordination.invocations import InvocationSnapshotStore


class EngineerPlanningRecoverySettings(EngineerSubmissionRecoverySettings):
    """Actual task/dependency/calendar queries; no terminal archive."""


@dataclass(frozen=True)
class EngineerPlanningCurrentSelection(ContractorCloseoutCurrentSelection):
    """Current history of the first original task/dependency/profile/calendar condition."""


@dataclass(frozen=True)
class EngineerPlanningRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Actual guarded history, independent native authority and successor callbacks."""


class EngineerPlanningRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ENGINEER-A04'
    ROLE = 'Engineer'
    ASSEMBLER_TYPE = EngineerPlanningActionAssembler
    SELECTION_TYPE = EngineerPlanningCurrentSelection
    READING_TYPE = EngineerPlanningConditionReading
    PROFILE_FACTORY = staticmethod(engineer_original_planning_profile)
    ROOT_FIELD = 'work_profile_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'engineer-planning-recovery-reader.v1'
    CONDITION_CODES = (TASK_CODE, CAPACITY_CODE)
    CONDITION_KINDS = {TASK_CODE: ['Task', 'Dependency', 'WorkProfile'], CAPACITY_CODE: 'ResourceCalendar'}
    MULTI_REF_CONDITION_CODES = (TASK_CODE,)

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract, plan_professional_work,
            recheck_original_engineer_planning_capacity)

    def _configuration(self):
        result = super()._configuration()
        result['planning_checks'] = module_factory_descriptor(plan_professional_work, 'planning_checks')
        result['historical_capacity_checks'] = module_factory_descriptor(recheck_original_engineer_planning_capacity, 'historical_capacity_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal:
            raise ValueError('Original engineering task recovery must resume planning; no terminal archive is available')
        selected = super().__call__(check, history_terminal=False)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)


def build_assembled_engineer_planning_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or EngineerPlanningRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, EngineerPlanningRecoveryReader):
        raise ValueError('Planning recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
