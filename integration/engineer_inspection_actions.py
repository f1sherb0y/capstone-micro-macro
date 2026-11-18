"""Assemble original Engineer A08 visible inspection and technical support inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_inspection_objects import (
    EngineerInspectionTaskView, EngineerInspectionDesignView, EngineerInspectionMethodView,
    EngineerInspectionAccessView, EngineerInspectionScopeView, EngineerInspectionSpecView,
    EngineerInspectionObservationView, EngineerInspectionResultView, EngineerInspectionIssueView,
    EngineerInspectionQuestionView, EngineerInspectionDependencyView, engineer_inspection_schemas,
    EngineerInspectionCheckPreparation,
)
from src.actions.contracts.engineer_planning_objects import (
    EngineerPlanningWorkFactView, EngineerPlanningEstimateView, EngineerPlanningCalendarView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedEngineerInspection(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A08'


class EngineerInspectionActionAssembler(EngineerOpportunityActionAssembler):
    """Freeze original task, design and observations under the current read guard.

    The processor checks authority, actual site access, people/equipment capacity,
    method support, observed physical coverage and received evidence. Planning,
    report, remote response and test requests retain their original branches.
    A nullable site access stays null; assembly creates no observation or work.
    """
    ACTION_ID = 'ENGINEER-A08'
    SOURCE_SCHEMAS = staticmethod(engineer_inspection_schemas)

    def prepare_check_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one original observation check under the caller's source guard."""
        from integration.engineer_inspection_check_calculations import prepare_engineer_inspection_check_calculation

        context, action_input, reading = self._build_check_reading(context, preparation=preparation, **source_refs)
        return prepare_engineer_inspection_check_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def _build_check_reading(self, context, *, preparation, **source_refs):
        """Retain actual observations while isolating the reserved check target."""
        from integration.engineer_design_actions import EngineerDesignActionAssembler

        preparation = EngineerInspectionCheckPreparation.model_validate(preparation).model_copy(deep=True)
        return EngineerDesignActionAssembler._build_calculation_reading(self, context, preparation=preparation,
            preparation_model=EngineerInspectionCheckPreparation,
            validate_sources=validate_engineer_inspection_check_preparation_sources,
            future_result_refs=[preparation.calculation_ref], **source_refs)

    def save_check_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain one original A08 check; publish separately."""
        from integration.engineer_inspection_check_publication import EngineerInspectionCheckPublicationStore
        from integration.engineer_inspection_check_calculations import prepare_engineer_inspection_check_calculation

        if (not isinstance(publications, EngineerInspectionCheckPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Inspection check save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_check_reading(context, preparation=preparation, **source_refs)
            calculation = prepare_engineer_inspection_check_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def build(self, context, *, scope, inspection_task_ref, applicable_design_ref,
            access_ref, observation_method_ref, observation_refs, query_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'inspection_task_ref': inspection_task_ref,
            'applicable_design_ref': applicable_design_ref, 'access_ref': access_ref,
            'observation_method_ref': observation_method_ref, 'observation_refs': observation_refs,
            'query_refs': query_refs}, prepared_type=PreparedEngineerInspection,
            validate_sources=validate_engineer_inspection_sources)


def validate_engineer_inspection_check_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Bind the original report observation/spec without reading its output."""
    task = sources.get(action_input.inspection_task_ref.key())
    spec = sources.get(preparation.check_spec_ref.key())
    observation = sources.get(preparation.observation_ref.key())
    if (not isinstance(task, EngineerInspectionTaskView) or task.choice != 'report'
            or not isinstance(spec, EngineerInspectionSpecView)
            or not isinstance(observation, EngineerInspectionObservationView)
            or spec.ref not in task.check_spec_refs or observation.ref not in action_input.observation_refs
            or spec.observation_ref != observation.ref or observation.check_spec_ref != spec.ref
            or observation.check_result_ref != preparation.calculation_ref
            or preparation.calculation_ref.key() in sources):
        raise TaskConflict('Inspection preparation changes original report observation/spec/result association')
    return validate_engineer_inspection_sources(action_input, context=context,
        organization_id=organization_id, sources=sources)


def validate_engineer_inspection_sources(action_input, *, context, organization_id, sources):
    """Check exact original source associations without planning or observing."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer inspection lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Engineer inspection source leaves its original authorized scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer inspection changes its original invocation scope')
    for refs in (action_input.observation_refs, action_input.query_refs):
        unique_refs(refs)
    task = read(action_input.inspection_task_ref, EngineerInspectionTaskView)
    design = read(action_input.applicable_design_ref, EngineerInspectionDesignView)
    read(action_input.observation_method_ref, EngineerInspectionMethodView)
    if (task.organization_id != organization_id or task.applicable_design_ref.key() != design.ref.key()
            or task.design_content_sha256 != design.content_sha256):
        raise TaskConflict('Engineer inspection changes its original organization, task or design content')

    def bound(row):
        if (row.task_ref.key() != task.ref.key() or row.applicable_design_ref.key() != design.ref.key()
                or row.design_content_sha256 != design.content_sha256):
            raise TaskConflict('Engineer inspection source changes its original task, design or content')

    if action_input.access_ref is not None:
        access = read(action_input.access_ref, EngineerInspectionAccessView)
        if access.task_ref.key() != task.ref.key():
            raise TaskConflict('Engineer inspection site access changes its original task')
    if task.appointment_ref.key() in sources:
        read(task.appointment_ref, EngineerAppointmentView)
    for ref in action_input.query_refs:
        bound(read(ref, EngineerInspectionIssueView))
    for ref in action_input.observation_refs:
        observation = read(ref, EngineerInspectionObservationView)
        bound(observation)
        if observation.check_result_ref is not None and observation.check_result_ref.key() in sources:
            result = read(observation.check_result_ref, EngineerInspectionResultView)
            bound(result)
            if result.observation_ref.key() != observation.ref.key():
                raise TaskConflict('Engineer inspection result changes its original observation')
        for fact_ref in observation.work_fact_refs:
            if fact_ref.key() in sources:
                fact = read(fact_ref, EngineerPlanningWorkFactView)
                if fact.task_ref.key() != task.ref.key() or fact.organization_id != observation.author_organization_id:
                    raise TaskConflict('Engineer observation investment changes its original task or executor')
    for refs, schema in (
            (task.engineering_scope_refs, EngineerInspectionScopeView),
            (task.check_spec_refs, EngineerInspectionSpecView),
            (task.question_refs, EngineerInspectionQuestionView)):
        for ref in refs:
            if ref.key() in sources:
                bound(read(ref, schema))
    for ref in task.dependency_refs:
        if ref.key() in sources and read(ref, EngineerInspectionDependencyView).task_ref.key() != task.ref.key():
            raise TaskConflict('Engineer inspection dependency changes its original task')
    if task.estimate_ref is not None and task.estimate_ref.key() in sources:
        estimate = read(task.estimate_ref, EngineerPlanningEstimateView)
        if (estimate.task_ref.key() != task.ref.key() or task.work_profile_ref is not None
                and estimate.work_profile_ref.key() != task.work_profile_ref.key()):
            raise TaskConflict('Engineer inspection estimate changes its original task or work profile')
    if task.resource_calendar_ref is not None and task.resource_calendar_ref.key() in sources:
        if read(task.resource_calendar_ref, EngineerPlanningCalendarView).organization_id != organization_id:
            raise TaskConflict('Engineer inspection borrows another organization resource calendar')
    for ref in task.work_fact_refs:
        if ref.key() in sources:
            fact = read(ref, EngineerPlanningWorkFactView)
            if fact.task_ref.key() != task.ref.key() or fact.organization_id != organization_id:
                raise TaskConflict('Engineer inspection investment changes its original task or organization')
    # Completeness, method identity/support, access permission, executor authority,
    # physical coverage and unknown/failed results remain processor decisions.
