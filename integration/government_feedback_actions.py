"""Freeze original Government A12 visible feedback, statistics and working authority."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.government_feedback_objects import (
    GovObservationProfileView, GovWorkingAuthorityView, GovReceivedFeedbackView,
    GovVisibleStatisticView, GovStatisticSnapshotView, GovAvailableProjectView,
    GovFeedbackWorkView, GovFeedbackRequestEstimateView, GovFeedbackTaskView,
    GovFeedbackEstimateView, GovFeedbackDependencyView, GovFeedbackAssignmentView,
    GovFeedbackCalendarView, GovPolicyControlView, GovPolicyInstrumentView,
    GovFeedbackRuleView, GovFeedbackRequirementView, GovFeedbackExecutionView,
    government_feedback_schemas,
)
from src.actions.contracts.government_objects import GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_scheduling_objects import GovReviewResourceView
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityCommitment
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentFeedback(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A12'


class GovernmentFeedbackActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve observed sources without applying policy or changing assignments.

    Observation lag, source digests, independent working permission and actual
    capacity remain original processor checks. Policy output is a proposal.
    """
    ACTION_ID = 'GOV-A12'
    SOURCE_SCHEMAS = staticmethod(government_feedback_schemas)

    def build(self, context, *, scope, feedback_refs, visible_statistic_refs,
            observation_profile_ref, working_authority_ref, policy_control_profile_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'feedback_refs': feedback_refs, 'visible_statistic_refs': visible_statistic_refs,
            'observation_profile_ref': observation_profile_ref, 'working_authority_ref': working_authority_ref,
            'policy_control_profile_ref': policy_control_profile_ref}, prepared_type=PreparedGovernmentFeedback,
            validate_sources=validate_government_feedback_sources)


def validate_government_feedback_sources(action_input, *, context, organization_id, sources):
    """Bind original recipient and source identities without inferring policy effects."""
    def read(ref, schema, *, linked=False, identity_field='ref'):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or getattr(row, identity_field).key() != ref.key():
            raise TaskConflict('Government feedback lacks its exact original concrete source')
        if hasattr(row, 'scope') and not linked and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government feedback source leaves its original working scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Government feedback changes its original invocation scope')
    unique_refs(action_input.feedback_refs)
    unique_refs(action_input.visible_statistic_refs)
    profile = read(action_input.observation_profile_ref, GovObservationProfileView)
    authority = read(action_input.working_authority_ref, GovWorkingAuthorityView)
    if (profile.organization_id != organization_id or profile.scope != action_input.scope
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.working_authority_ref != authority.ref
            or profile.policy_control_profile_ref != action_input.policy_control_profile_ref
            or authority.organization_id != organization_id or authority.actor_id != context.actor_id
            or authority.function_ref != context.function_ref
            or set(profile.feedback_refs) != set(action_input.feedback_refs)
            or set(profile.statistic_refs) != set(action_input.visible_statistic_refs)):
        raise TaskConflict('Government feedback substitutes its original agency, actor, authority or visible input set')
    if action_input.policy_control_profile_ref is not None:
        control = read(action_input.policy_control_profile_ref, GovPolicyControlView)
        if control.organization_id != organization_id:
            raise TaskConflict('Government policy control profile substitutes its original agency')
    for ref in profile.execution_refs:
        if ref.key() in sources:
            execution = read(ref, GovFeedbackExecutionView, linked=True)
            if execution.organization_id != organization_id or execution.run_id != context.run_id:
                raise TaskConflict('Government feedback execution history substitutes its original agency or run')
            if execution.profile_ref.key() in sources:
                original = read(execution.profile_ref, GovObservationProfileView, linked=True)
                if (original.organization_id != execution.organization_id or original.scope != execution.scope
                        or original.business_key != execution.business_key):
                    raise TaskConflict('Government feedback execution substitutes its original profile agency, scope or business')
    for ref in action_input.feedback_refs:
        feedback = read(ref, GovReceivedFeedbackView, linked=True)
        if feedback.recipient_organization_id != organization_id:
            raise TaskConflict('Government feedback substitutes its original receiving agency')
        # The processor compares the original event source digest and chronology,
        # preserving repeated physical events without inventing an observed fact.
    for ref in action_input.visible_statistic_refs:
        statistic = read(ref, GovVisibleStatisticView, linked=True)
        if statistic.recipient_organization_id != organization_id:
            raise TaskConflict('Government statistic substitutes its original receiving agency')
        if statistic.source_ref.key() in sources:
            original = read(statistic.source_ref, GovStatisticSnapshotView, linked=True)
            if any(getattr(original, field) != getattr(statistic, field) for field in (
                    'metric', 'measure', 'sampling_scope', 'reporting_window', 'case_ids',
                    'project_ids', 'available_project_refs', 'coverage')):
                raise TaskConflict('Government statistic substitutes its original reported snapshot')
        for project_ref in statistic.available_project_refs:
            if project_ref.key() in sources:
                read(project_ref, GovAvailableProjectView, linked=True)

    def question_sources(questions):
        for question in questions:
            if question.scope != action_input.scope:
                raise TaskConflict('Government feedback question substitutes its original working scope')
            if question.requirement_ref.key() in sources:
                rule = read(question.requirement_ref, GovFeedbackRuleView)
                if rule.organization_id != organization_id or rule.purpose != 'information_request':
                    raise TaskConflict('Government feedback question substitutes its original legal rule purpose')
            if question.response_requirement_ref.key() in sources:
                response = read(question.response_requirement_ref, GovResponseRequirementView, linked=True)
                if response.rule_ref != question.requirement_ref or not scope_covers(response.scope, action_input.scope):
                    raise TaskConflict('Government feedback response requirement substitutes its original rule or scope')
            for ref in question.recipient_refs:
                if ref.key() in sources:
                    recipient = read(ref, GovRecipientView, linked=True)
                    if not scope_covers(recipient.scope, action_input.scope):
                        raise TaskConflict('Government feedback recipient lacks its original question coverage')

    def request_sources(request, purpose):
        if (request.scope != action_input.scope or request.purpose != purpose
                or request.authority_basis_refs != [authority.ref]):
            raise TaskConflict('Government feedback request substitutes its original purpose, scope or authority')
        question_sources(request.questions)
        for ref in request.output_requirement_refs:
            if ref.key() in sources:
                requirement = read(ref, GovFeedbackRequirementView)
                if requirement.organization_id != organization_id or requirement.requested_purpose != purpose:
                    raise TaskConflict('Government feedback output requirement substitutes its original agency or purpose')
        if request.work_profile_ref is not None and request.work_profile_ref.key() in sources:
            work = read(request.work_profile_ref, GovFeedbackWorkView)
            if work.organization_id != organization_id:
                raise TaskConflict('Government feedback request borrows another agency work profile')
            if work.request_estimate_ref is not None and work.request_estimate_ref.key() in sources:
                estimate = read(work.request_estimate_ref, GovFeedbackRequestEstimateView)
                if (estimate.organization_id != organization_id or estimate.work_profile_ref != work.ref
                        or estimate.purpose != purpose or set(estimate.input_refs) != set(request.input_refs)
                        or set(estimate.output_requirement_refs) != set(request.output_requirement_refs)):
                    raise TaskConflict('Government feedback estimate substitutes its original request inputs or purpose')

    if profile.choice == 'investigate':
        question_sources(profile.questions)
        if profile.investigation_request is not None:
            request_sources(profile.investigation_request, 'investigation')
    if profile.choice == 'propose_policy' and profile.policy_proposal is not None:
        proposal = profile.policy_proposal
        if (proposal.observation_profile_ref != profile.ref or proposal.target_scope != action_input.scope
                or set(proposal.issue_refs) != set(action_input.feedback_refs)
                or set(proposal.statistic_refs) != set(action_input.visible_statistic_refs)):
            raise TaskConflict('Government policy proposal substitutes its original observations or target scope')
        for ref in proposal.proposed_instrument_refs:
            if ref.key() in sources:
                instrument = read(ref, GovPolicyInstrumentView)
                if instrument.organization_id != organization_id or instrument.target_scope != action_input.scope:
                    raise TaskConflict('Government policy instrument substitutes its original agency or target scope')
                for basis_ref in instrument.legal_basis_refs:
                    if basis_ref.key() in sources:
                        rule = read(basis_ref, GovFeedbackRuleView)
                        if rule.organization_id != organization_id or rule.purpose != 'proposal_basis':
                            raise TaskConflict('Government policy proposal substitutes its original legal basis')
        request_sources(proposal.evaluation_request, 'policy_evaluation')
    if profile.choice != 'change_work_arrangement' or profile.work_plan is None:
        return
    plan = profile.work_plan
    if plan.work_profile_ref.key() in sources:
        work = read(plan.work_profile_ref, GovFeedbackWorkView)
        if work.organization_id != organization_id:
            raise TaskConflict('Government work arrangement borrows another agency work profile')
    if authority.calendar_ref.key() in sources:
        calendar = read(authority.calendar_ref, GovFeedbackCalendarView)
        if calendar.organization_id != organization_id:
            raise TaskConflict('Government feedback calendar substitutes its original agency')
        for embedded in calendar.resources:
            if embedded.ref.key() in sources:
                resource = read(embedded.ref, GovReviewResourceView)
                if resource != embedded or resource.organization_id != organization_id:
                    raise TaskConflict('Government feedback calendar substitutes its original resource projection')
        for embedded in calendar.commitments:
            if embedded.commitment_ref.key() in sources:
                commitment = read(embedded.commitment_ref, CapacityCommitment, identity_field='commitment_ref')
                if commitment != embedded:
                    raise TaskConflict('Government feedback calendar substitutes its original occupancy projection')
    for item in plan.items:
        if item.task_ref.key() not in sources:
            continue
        task = read(item.task_ref, GovFeedbackTaskView)
        if task.organization_id != organization_id or task.work_profile_ref != plan.work_profile_ref:
            raise TaskConflict('Government work arrangement substitutes its original task agency or profile')
        if task.estimate_ref.key() in sources:
            estimate = read(task.estimate_ref, GovFeedbackEstimateView)
            if estimate.task_ref != task.ref or estimate.work_profile_ref != task.work_profile_ref:
                raise TaskConflict('Government work estimate substitutes its original task or profile')
        for ref in task.dependency_refs:
            if ref.key() in sources and read(ref, GovFeedbackDependencyView).task_ref != task.ref:
                raise TaskConflict('Government feedback dependency substitutes its original task')
        if item.existing_assignment_ref is not None and item.existing_assignment_ref.key() in sources:
            assignment = read(item.existing_assignment_ref, GovFeedbackAssignmentView)
            if assignment.task_ref != task.ref or assignment.organization_id != organization_id:
                raise TaskConflict('Government work arrangement substitutes its original assignment')
    # The processor owns source digests, observed/received chronology and lag,
    # distinct cases/projects/available stock, execution dedup/query, independent
    # working permission, policy control and physical capacity/atomic replacement.
    # No policy parameters, formal tasks or assignments are changed during assembly.
