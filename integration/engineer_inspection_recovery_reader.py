"""Reassemble original A08 task authorization waits through formal planning sources."""
from dataclasses import dataclass, replace
from pydantic import BaseModel, model_serializer

from integration.engineer_inspection_actions import EngineerInspectionActionAssembler
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from src.actions.roles.engineer_inspection import (
    inspect_and_support, recheck_original_engineer_inspection_observation_wait, recheck_original_engineer_inspection_investment,
    recheck_original_engineer_inspection_personnel,
    recheck_original_engineer_inspection_qualification,
    recheck_original_engineer_inspection_equipment,
    recheck_original_engineer_inspection_capacity,
    recheck_original_engineer_inspection_design_change,
)
from src.coordination.engineer_inspection_conditions import (
    AUTHORIZATION_CODE, OBSERVATION_CODE, INVESTMENT_CODE, PERSONNEL_CODE, QUALIFICATION_CODE, EQUIPMENT_CODE, CAPACITY_CODE, CHANGE_CODE,
    EngineerInspectionConditionReading, engineer_original_inspection_profile,
)
from src.actions.contracts.engineer_inspection_objects import EngineerInspectionTaskView, EngineerPlanningCalendarView
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.references import ActionReadView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, task_digest


class EngineerInspectionRecoverySettings(EngineerSubmissionRecoverySettings):
    """Actual original inspection queries; invested-work archival is explicitly enabled."""
    terminal_investment_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_investment_enabled:
            result.pop('terminal_investment_enabled', None)
        return result


@dataclass(frozen=True)
class EngineerInspectionCurrentSelection(ContractorCloseoutCurrentSelection):
    """Current original inspection task history."""


@dataclass(frozen=True)
class EngineerInspectionRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Actual guarded history, independent native authority and successor callbacks."""


@dataclass(frozen=True)
class _EngineerInspectionHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class EngineerInspectionRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ENGINEER-A08'
    ROLE = 'Engineer'
    ASSEMBLER_TYPE = EngineerInspectionActionAssembler
    SELECTION_TYPE = EngineerInspectionCurrentSelection
    READING_TYPE = EngineerInspectionConditionReading
    PROFILE_FACTORY = staticmethod(engineer_original_inspection_profile)
    ROOT_FIELD = 'inspection_task_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'engineer-inspection-recovery-reader.v1'
    CONDITION_CODES = (AUTHORIZATION_CODE, OBSERVATION_CODE, INVESTMENT_CODE, PERSONNEL_CODE, QUALIFICATION_CODE, EQUIPMENT_CODE, CAPACITY_CODE, CHANGE_CODE)
    CONDITION_KINDS = {AUTHORIZATION_CODE: 'Task', OBSERVATION_CODE: 'Task', INVESTMENT_CODE: 'Task',
        PERSONNEL_CODE: 'Resource', QUALIFICATION_CODE: 'Qualification', EQUIPMENT_CODE: 'Resource', CAPACITY_CODE: 'ResourceCalendar',
        CHANGE_CODE: 'Issue'}
    CONDITION_REF_KIND_SEQUENCES = {CHANGE_CODE: ['Issue', 'Deliverable']}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract, inspect_and_support,
            recheck_original_engineer_inspection_observation_wait, recheck_original_engineer_inspection_investment,
            recheck_original_engineer_inspection_personnel, recheck_original_engineer_inspection_qualification,
            recheck_original_engineer_inspection_equipment, recheck_original_engineer_inspection_capacity,
            recheck_original_engineer_inspection_design_change)

    def _configuration(self):
        result = super()._configuration()
        result['inspection_checks'] = module_factory_descriptor(inspect_and_support, 'inspection_checks')
        result['historical_observation_checks'] = module_factory_descriptor(
            recheck_original_engineer_inspection_observation_wait, 'historical_observation_checks')
        result['historical_investment_checks'] = module_factory_descriptor(
            recheck_original_engineer_inspection_investment, 'historical_investment_checks')
        result['historical_personnel_checks'] = module_factory_descriptor(
            recheck_original_engineer_inspection_personnel, 'historical_personnel_checks')
        result['historical_qualification_checks'] = module_factory_descriptor(
            recheck_original_engineer_inspection_qualification, 'historical_qualification_checks')
        result['historical_equipment_checks'] = module_factory_descriptor(
            recheck_original_engineer_inspection_equipment, 'historical_equipment_checks')
        result['historical_capacity_checks'] = module_factory_descriptor(
            recheck_original_engineer_inspection_capacity, 'historical_capacity_checks')
        result['historical_design_change_checks'] = module_factory_descriptor(
            recheck_original_engineer_inspection_design_change, 'historical_design_change_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal and check.condition.condition_code != INVESTMENT_CODE:
            raise ValueError('Only original fully invested inspection waits support archival')
        selected = super().__call__(check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)


    def _assemble_current(self, context, action_input, history_terminal):
        if not history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        assembler = self.assembler
        registration = assembler.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.skill is None or registration.role != self.ROLE:
            raise TaskConflict('Inspection history reading requires its original implemented Engineer contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _EngineerInspectionHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


    def _resolve_recovery_ref(self, reading, ref, *, original_input, action_input):
        if ref.kind != 'Resource':
            return super()._resolve_recovery_ref(reading, ref, original_input=original_input, action_input=action_input)
        matches = []
        for values in (original_input, action_input):
            task = reading.resolve(values.inspection_task_ref)
            if not isinstance(task, EngineerInspectionTaskView) or task.resource_calendar_ref is None:
                raise TaskConflict('Inspection resource history requires its original task/calendar linkage')
            calendar = reading.resolve(task.resource_calendar_ref)
            if not isinstance(calendar, EngineerPlanningCalendarView) or calendar.organization_id != reading.organization_id:
                raise TaskConflict('Inspection resource history requires its original authorized private calendar')
            matches.extend(row for row in calendar.resources if row.resource_ref == ref)
        if not matches or any(row != matches[0] for row in matches):
            raise TaskConflict('Inspection recovery cannot resolve an exact immutable embedded resource version')
        return matches[0]


def build_assembled_engineer_inspection_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or EngineerInspectionRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, EngineerInspectionRecoveryReader):
        raise ValueError('Inspection recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
