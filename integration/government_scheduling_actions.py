"""Freeze original Government A03 queues, review tasks and reviewer occupancy."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.government_objects import (
    GovMatterView, GovJurisdictionView, GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingCaseView, GovCaseQueueView, GovQueueRuleView, GovQueueProfileView,
    GovSchedulingWorkProfileView, GovSchedulingTaskView, GovSchedulingEstimateView,
    GovSchedulingWorkFactView, GovSchedulingDependencyView, GovReviewCalendarView,
    GovReviewResourceView, GovReviewAssignmentView, GovSchedulingPriorityView,
    GovPriorityAuthorityView, GovSchedulingQuestionView, government_scheduling_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityCommitment


@dataclass(frozen=True)
class PreparedGovernmentScheduling(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A03'


class GovernmentSchedulingActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve the original queue and sources for the existing scheduling processor.

    Lawful priority, remaining effort, reviewer eligibility and exact capacity
    remain processor decisions. Assembly creates no assignments or reservations.
    """
    ACTION_ID = 'GOV-A03'
    SOURCE_SCHEMAS = staticmethod(government_scheduling_schemas)

    def build(self, context, *, scope, case_ref, queue_ref, task_refs, capacity_ref,
            ordering_profile_ref, existing_assignment_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'case_ref': case_ref, 'queue_ref': queue_ref,
            'task_refs': task_refs, 'capacity_ref': capacity_ref,
            'ordering_profile_ref': ordering_profile_ref,
            'existing_assignment_refs': existing_assignment_refs},
            prepared_type=PreparedGovernmentScheduling,
            validate_sources=validate_government_scheduling_sources)


def validate_government_scheduling_sources(action_input, *, context, organization_id, sources):
    """Bind original case/task/resource identities without deciding readiness."""
    def read(ref, schema, identity_field='ref'):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or getattr(row, identity_field).key() != ref.key():
            raise TaskConflict('Government scheduling lacks its exact original concrete source')
        if hasattr(row, 'scope') and row.scope != action_input.scope:
            raise TaskConflict('Government scheduling source substitutes its original scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Government scheduling changes its original invocation scope')
    unique_refs(action_input.task_refs)
    unique_refs(action_input.existing_assignment_refs)
    case = read(action_input.case_ref, GovSchedulingCaseView)
    queue = read(action_input.queue_ref, GovCaseQueueView)
    profile = read(action_input.ordering_profile_ref, GovQueueProfileView)
    calendar = read(action_input.capacity_ref, GovReviewCalendarView)
    if (any(row.organization_id != organization_id for row in (case, queue, profile, calendar))
            or case.queue_ref != queue.ref or profile.case_ref != case.ref
            or profile.queue_ref != queue.ref):
        raise TaskConflict('Government scheduling substitutes its original agency, case or queue')
    if profile.work_profile_ref.key() in sources:
        work = read(profile.work_profile_ref, GovSchedulingWorkProfileView)
        if work.organization_id != organization_id:
            raise TaskConflict('Government scheduling borrows another agency work profile')
    if queue.ordering_rule_ref.key() in sources:
        rule = read(queue.ordering_rule_ref, GovQueueRuleView)
        if rule.organization_id != organization_id or rule.queue_ref != queue.ref:
            raise TaskConflict('Government scheduling substitutes its original queue rule')
    if case.matter_ref.key() in sources:
        read(case.matter_ref, GovMatterView)
    if case.jurisdiction_ref.key() in sources:
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView)
        if jurisdiction.organization_id != organization_id:
            raise TaskConflict('Government scheduling borrows another agency jurisdiction')

    tasks = {}
    for ref in action_input.task_refs:
        task = read(ref, GovSchedulingTaskView)
        if (task.organization_id != organization_id or task.case_ref != case.ref
                or task.work_profile_ref != profile.work_profile_ref):
            raise TaskConflict('Government scheduling task substitutes its original agency, case or work profile')
        tasks[ref.key()] = task
        if task.estimate_ref.key() in sources:
            estimate = read(task.estimate_ref, GovSchedulingEstimateView)
            if estimate.task_ref != task.ref or estimate.work_profile_ref != task.work_profile_ref:
                raise TaskConflict('Government review estimate substitutes its original task or work profile')
        for fact_ref in task.work_fact_refs:
            if fact_ref.key() in sources:
                fact = read(fact_ref, GovSchedulingWorkFactView)
                if fact.task_ref != task.ref or fact.organization_id != organization_id:
                    raise TaskConflict('Government review investment substitutes its original task or agency')
        for dependency_ref in task.dependency_refs:
            if dependency_ref.key() in sources:
                dependency = read(dependency_ref, GovSchedulingDependencyView)
                if dependency.task_ref != task.ref:
                    raise TaskConflict('Government review dependency substitutes its original task')

    for embedded in calendar.resources:
        if embedded.ref.key() in sources:
            resource = read(embedded.ref, GovReviewResourceView)
            if resource != embedded or resource.organization_id != organization_id:
                raise TaskConflict('Government review calendar substitutes its original resource projection')
    for embedded in calendar.commitments:
        if embedded.commitment_ref.key() in sources:
            commitment = read(embedded.commitment_ref, CapacityCommitment, 'commitment_ref')
            if commitment != embedded:
                raise TaskConflict('Government review calendar substitutes its original occupancy projection')
    for ref in action_input.existing_assignment_refs:
        assignment = read(ref, GovReviewAssignmentView)
        task = tasks.get(assignment.task_ref.key())
        if (task is None or task.existing_assignment_ref != assignment.ref
                or assignment.organization_id != organization_id or assignment.case_ref != case.ref
                or assignment.work_profile_ref != profile.work_profile_ref):
            raise TaskConflict('Government continued assignment substitutes its original case or task')
        for commitment_ref in assignment.commitment_refs:
            if commitment_ref.key() in sources:
                commitment = read(commitment_ref, CapacityCommitment, 'commitment_ref')
                if commitment.resource_ref not in assignment.resource_refs or commitment.window != assignment.window:
                    raise TaskConflict('Government continued assignment substitutes its original occupancy')

    if profile.priority_basis_ref is not None and profile.priority_basis_ref.key() in sources:
        priority = read(profile.priority_basis_ref, GovSchedulingPriorityView)
        if (priority.organization_id != organization_id or priority.case_ref != case.ref
                or priority.queue_ref != queue.ref or priority.ordering_rule_ref != queue.ordering_rule_ref):
            raise TaskConflict('Government priority basis substitutes its original agency, case or queue rule')
        if priority.priority_authority_ref.key() in sources:
            grant = read(priority.priority_authority_ref, GovPriorityAuthorityView)
            if (grant.organization_id != organization_id or grant.actor_id != context.actor_id
                    or grant.function_ref != context.function_ref or grant.case_ref != case.ref
                    or grant.queue_ref != queue.ref or grant.ordering_rule_ref != queue.ordering_rule_ref):
                raise TaskConflict('Government priority authority substitutes its original actor, case or queue rule')

    for ref in profile.question_refs:
        if ref.key() not in sources:
            continue
        row = read(ref, GovSchedulingQuestionView)
        question = row.question
        if (row.case_ref != case.ref or not set(row.task_refs) <= set(action_input.task_refs)
                or question.scope != action_input.scope or question.requirement_ref != queue.ordering_rule_ref
                or row.ref not in question.target_refs):
            raise TaskConflict('Government cooperation question substitutes its original case, tasks or rule')
        for target_ref in question.target_refs:
            if target_ref.key() in sources:
                target = read(target_ref, GovSchedulingQuestionView)
                if target.case_ref != case.ref or target.question != question:
                    raise TaskConflict('Government cooperation targets substitute their original question')
        for recipient_ref in question.recipient_refs:
            if recipient_ref.key() in sources:
                read(recipient_ref, GovRecipientView)
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != queue.ordering_rule_ref:
                raise TaskConflict('Government cooperation response substitutes its original queue rule')
    # The processor owns exact task/assignment completeness, queue order and
    # lawful exceptions, unknown/current inputs, qualifications and arithmetic.
