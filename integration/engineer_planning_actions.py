"""Assemble original Engineer A04 task planning and actual investment sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_planning_objects import (
    EngineerPlanningAllocationView, EngineerPlanningCalendarView, EngineerPlanningAccessView,
    EngineerPlanningDependencyView, EngineerPlanningEstimateView, EngineerPlanningProfileView,
    EngineerPlanningQualificationView, EngineerPlanningReservationView, EngineerPlanningTaskView,
    EngineerPlanningWorkFactView, EngineerPlanningQuestionTargetView, EngineerPlanningObservationMethodView,
    engineer_planning_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_appointment_objects import QSWorkPlanView
from src.actions.contracts.common import ActionContext, EvidenceRecord
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedEngineerPlanning(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A04'


class EngineerPlanningActionAssembler(EngineerOpportunityActionAssembler):
    """Freeze exact tasks and actual commitments under the application's read guard.

    Original processor checks active authority, personnel qualifications, equipment, site access, independent review,
    supported work methods, remaining effort, dependencies and shared capacity.
    Missing coverage and pending facts stay explicit. Assembly creates no
    allocation, reservation conversion, task completion or internal cost.
    """
    ACTION_ID = 'ENGINEER-A04'
    SOURCE_SCHEMAS = staticmethod(engineer_planning_schemas)

    def build_from_investigation_task(self, context, *, research_submission, research_identity,
            research_execution_versions, research_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Bind actual A13 investigation intake and continuation confirmation to A04 planning."""
        from integration.engineer_investigation_task_handoff import prepare_engineer_investigation_task_handoff
        from integration.engineer_research_results import EngineerResearchResultWorker
        from integration.engineer_submission import EngineerResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.engineer_research_objects import engineer_research_schemas

        if (not isinstance(research_submission, EngineerResultSubmission)
                or research_submission.ACTION_ID != 'ENGINEER-A13'
                or not isinstance(research_submission.worker, EngineerResearchResultWorker)
                or research_submission.worker.registry is not self.registry
                or research_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Investigation task requires original A13 submission/worker and actual guarded source checks')
        context = self._context(context)
        own_context = ActionContext.model_validate(research_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != 'ENGINEER-A13'
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Investigation intake requires independently authorized A13 history at the current A04 scope/time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        with read_guard(context.model_copy(deep=True)):
            receipt = research_submission.read_receipt(research_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected investigation proposal cannot establish actual revision intake')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, engineer_research_schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, 'ENGINEER-A13', 'Engineer')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, 'ENGINEER-A13', 'Engineer')
            reading = None
            try:
                saved = research_submission.worker.read_completed(research_identity, current_context=own_context,
                    reading=own_reading, execution_versions=research_execution_versions, validate_current=validate_history)
                reading = self.build_result_reading(context)
                preflight = SimpleNamespace(context=context, action_input=action_input, reading=reading)

                def validate_link(**sources):
                    if (sources['saved'].identity.as_dict() != receipt['identity']
                            or sources['saved'].record_sha256 != receipt['record_sha256']):
                        raise TaskConflict('Investigation proposal receipt substitutes its original saved result')
                    return (validate_current(**sources) is True
                        and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

                handoff = prepare_engineer_investigation_task_handoff(saved, invocation=preflight,
                    registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
                    native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
                    validate_current=validate_link)
                if research_submission.read_receipt(research_identity) != receipt:
                    raise TaskConflict('Original investigation receipt changed during actual task linkage')
                if handoff['kind'] != 'prepared':
                    return handoff
                invocation = self.build(context, **source_refs)
                if any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items()):
                    raise TaskConflict('Actual change task differs from the frozen A04 source snapshot')
                invocation.reading.recheck()
                if research_submission.read_receipt(research_identity) != receipt:
                    raise TaskConflict('Original investigation receipt changed before A04 assembly completed')
                return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
                    'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
            finally:
                if reading is not None:
                    reading.recheck()
                own_reading.recheck()

    def build(self, context, *, scope, task_refs, dependency_refs, work_profile_ref, capacity_ref, existing_allocation_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'task_refs': task_refs, 'dependency_refs': dependency_refs,
            'work_profile_ref': work_profile_ref, 'capacity_ref': capacity_ref,
            'existing_allocation_refs': existing_allocation_refs}, prepared_type=PreparedEngineerPlanning,
            validate_sources=validate_engineer_planning_sources)


def validate_engineer_planning_sources(action_input, *, context, organization_id, sources):
    """Preserve original appointment, task and investment identities without calculating."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer planning lacks its exact original concrete source')
        if hasattr(row, 'scope') and row.scope != action_input.scope:
            raise TaskConflict('Engineer planning source changes its original scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer planning input changes its original invocation scope')
    for refs in (action_input.task_refs, action_input.dependency_refs, action_input.existing_allocation_refs):
        unique_refs(refs)
    profile = read(action_input.work_profile_ref, EngineerPlanningProfileView)
    calendar = read(action_input.capacity_ref, EngineerPlanningCalendarView)
    if profile.organization_id != organization_id or calendar.organization_id != organization_id:
        raise TaskConflict('Engineer planning changes its original private profile or calendar')
    appointment = None
    if profile.appointment_ref.key() in sources:
        appointment = read(profile.appointment_ref, EngineerAppointmentView)
        if appointment.provider_organization_id != organization_id:
            raise TaskConflict('Engineer planning changes its original appointment provider')
    prior = None
    if profile.prior_plan_ref is not None and profile.prior_plan_ref.key() in sources:
        prior = read(profile.prior_plan_ref, QSWorkPlanView)
        if prior.organization_id != organization_id or prior.appointment_ref.key() != profile.appointment_ref.key():
            raise TaskConflict('Engineer prior plan changes its original organization or appointment')
    tasks = {ref.key(): read(ref, EngineerPlanningTaskView) for ref in action_input.task_refs}
    for task in tasks.values():
        if (task.organization_id != organization_id or task.appointment_ref.key() != profile.appointment_ref.key()
                or task.work_profile_ref.key() != profile.ref.key()
                or appointment is not None and task.accepted_terms_ref.key() != appointment.terms_ref.key()):
            raise TaskConflict('Engineer task changes original organization, appointment, terms or work profile')
        if task.access_ref is not None and task.access_ref.key() in sources:
            access = read(task.access_ref, EngineerPlanningAccessView)
            if access.organization_id != organization_id or access.task_ref.key() != task.ref.key():
                raise TaskConflict('Engineer site access changes its original organization or task')
        # Site permission, equipment demand, actual remaining effort and readiness
        # remain original processor decisions; a request never completes work.
        if task.estimate_ref.key() in sources:
            estimate = read(task.estimate_ref, EngineerPlanningEstimateView)
            if estimate.task_ref.key() != task.ref.key() or estimate.work_profile_ref.key() != profile.ref.key():
                raise TaskConflict('Engineer work estimate changes its original task or method profile')
        for ref in task.work_fact_refs:
            if ref.key() in sources:
                fact = read(ref, EngineerPlanningWorkFactView)
                if fact.organization_id != organization_id or fact.task_ref.key() != task.ref.key():
                    raise TaskConflict('Engineer investment fact changes its original organization or task')
        for ref in task.dependency_refs:
            if ref.key() in sources:
                dependency = read(ref, EngineerPlanningDependencyView)
                if dependency.task_ref.key() != task.ref.key():
                    raise TaskConflict('Engineer dependency changes its original task')
                if dependency.predecessor_task_ref is not None and dependency.predecessor_task_ref.key() in sources:
                    predecessor = read(dependency.predecessor_task_ref, EngineerPlanningTaskView)
                    if (predecessor.organization_id != organization_id
                            or predecessor.appointment_ref.key() != profile.appointment_ref.key()):
                        raise TaskConflict('Engineer predecessor changes its original organization or appointment')
    for ref in action_input.dependency_refs:
        read(ref, EvidenceRecord)
    for ref in action_input.existing_allocation_refs:
        allocation = read(ref, EngineerPlanningAllocationView)
        if (allocation.organization_id != organization_id
                or allocation.appointment_ref.key() != profile.appointment_ref.key()
                or allocation.task_ref.key() not in tasks
                or prior is not None and allocation.work_plan_ref.key() != prior.ref.key()):
            raise TaskConflict('Engineer allocation changes its original organization, task, appointment or plan')
    for ref in profile.reservation_refs:
        if ref.key() in sources:
            reservation = read(ref, EngineerPlanningReservationView)
            if (reservation.organization_id != organization_id
                    or reservation.appointment_ref.key() != profile.appointment_ref.key()):
                raise TaskConflict('Engineer reservation changes its original organization or appointment')
    for resource in calendar.resources:
        for ref in resource.qualification_refs:
            if ref.key() in sources and read(ref, EngineerPlanningQualificationView).organization_id != organization_id:
                raise TaskConflict('Engineer personnel qualification changes its original organization')
    for ref in profile.question_target_refs:
        if ref.key() in sources:
            question = read(ref, EngineerPlanningQuestionTargetView)
            if appointment is not None and question.request_ref.key() != appointment.request_ref.key():
                raise TaskConflict('Engineer planning question changes its original appointment request')
            if question.response_requirement_ref.key() in sources:
                response = read(question.response_requirement_ref, ServiceResponseRequirementView)
                if response.request_ref.key() != question.request_ref.key():
                    raise TaskConflict('Engineer investigation response changes its original request')
    if profile.observation_method_ref is not None and profile.observation_method_ref.key() in sources:
        read(profile.observation_method_ref, EngineerPlanningObservationMethodView)
    # Executor authority, allowed targets and actual observation evidence remain
    # processor/independent executor inputs, including absent or unknown facts.
