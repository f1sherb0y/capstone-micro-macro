"""Freeze original Government A10 inspection tasks, observations and remedy sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.government_inspection_objects import (
    GovInspectionTaskView, GovInspectionView, GovInspectionRuleView, GovInspectionApplicabilityView,
    GovInspectionMethodView, GovInspectionAccessView, GovInspectionObservationView,
    GovInspectionResultView, GovInspectionQuestionView, GovInspectionIssueView,
    GovInspectionRequirementView, GovInspectionResponseView, GovRemedyVerificationView,
    GovInspectionAssessmentView, GovRemedyResponderAuthorityView, GovMeasureBasisView,
    GovInspectionAuthorityView, GovMeasureBindingView, GovMeasureProcedureVerificationView,
    GovRecipientView, GovResponseRequirementView, GovPermitView, GovSchedulingWorkProfileView,
    GovSchedulingEstimateView, GovSchedulingWorkFactView, GovSchedulingDependencyView,
    GovReviewResourceView, GovReviewCalendarView, GovReviewAssignmentView,
    government_inspection_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityCommitment
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentInspection(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A10'


class GovernmentInspectionActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve actual inspection provenance without performing or ordering work.

    Resource planning, site access, actual observations, remedy verification and
    independent measure authority remain original processor decisions.
    """
    ACTION_ID = 'GOV-A10'
    SOURCE_SCHEMAS = staticmethod(government_inspection_schemas)

    def build(self, context, *, scope, inspection_basis_ref, permit_ref, task_ref,
            access_ref, observation_method_ref, observation_refs, prior_issue_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'inspection_basis_ref': inspection_basis_ref, 'permit_ref': permit_ref,
            'task_ref': task_ref, 'access_ref': access_ref, 'observation_method_ref': observation_method_ref,
            'observation_refs': observation_refs, 'prior_issue_refs': prior_issue_refs},
            prepared_type=PreparedGovernmentInspection,
            validate_sources=validate_government_inspection_sources)


def validate_government_inspection_sources(action_input, *, context, organization_id, sources):
    """Bind original task/event/requirement identities without inferring completion."""
    def read(ref, schema, *, linked=False, identity_field='ref'):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or getattr(row, identity_field).key() != ref.key():
            raise TaskConflict('Government inspection lacks its exact original concrete source')
        if hasattr(row, 'scope') and not linked and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government inspection source leaves its original task coverage')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government inspection input leaves its original invocation scope')
    unique_refs(action_input.observation_refs)
    unique_refs(action_input.prior_issue_refs)
    task = read(action_input.task_ref, GovInspectionTaskView)
    if (task.organization_id != organization_id or task.scope != action_input.scope
            or task.execution_action_id != 'GOV-A10' or task.inspection_basis_ref != action_input.inspection_basis_ref
            or task.permit_ref != action_input.permit_ref or task.observation_method_ref != action_input.observation_method_ref
            or task.function_ref != context.function_ref or task.authority_ref not in context.authorization_refs
            or set(task.received_observation_refs) != set(action_input.observation_refs)
            or set(task.prior_issue_refs) != set(action_input.prior_issue_refs)):
        raise TaskConflict('Government inspection substitutes its original agency, task, method or received source sets')

    def bound(row):
        if row.task_ref != task.ref:
            raise TaskConflict('Government inspection source substitutes its original task')

    def legal(ref, purpose):
        row = read(ref, GovInspectionRuleView)
        bound(row)
        if row.organization_id != organization_id or row.inspection_ref != task.inspection_ref or row.purpose != purpose:
            raise TaskConflict('Government inspection rule substitutes its original agency, inspection or purpose')
        return row

    legal(action_input.inspection_basis_ref, 'inspection')
    if task.inspection_ref.key() in sources:
        inspection = read(task.inspection_ref, GovInspectionView)
        bound(inspection)
        if inspection.organization_id != organization_id or inspection.permit_ref != task.permit_ref:
            raise TaskConflict('Government inspection substitutes its original agency or permit')
    if action_input.permit_ref is not None:
        permit = read(action_input.permit_ref, GovPermitView, linked=True)
        if permit.organization_id != organization_id or not scope_covers(permit.scope, action_input.scope):
            raise TaskConflict('Government inspection borrows another agency permit or coverage')
    read(action_input.observation_method_ref, GovInspectionMethodView)
    if action_input.access_ref is not None:
        bound(read(action_input.access_ref, GovInspectionAccessView))
    for ref in action_input.observation_refs:
        observation = read(ref, GovInspectionObservationView)
        bound(observation)
        if (observation.inspection_ref != task.inspection_ref or observation.permit_ref != task.permit_ref
                or observation.method_ref != task.observation_method_ref):
            raise TaskConflict('Government observation substitutes its original inspection, permit or method')

    if task.choice == 'plan':
        if task.work_profile_ref.key() in sources:
            work = read(task.work_profile_ref, GovSchedulingWorkProfileView)
            if work.organization_id != organization_id:
                raise TaskConflict('Government inspection borrows another agency work profile')
        if task.estimate_ref.key() in sources:
            estimate = read(task.estimate_ref, GovSchedulingEstimateView)
            bound(estimate)
            if estimate.work_profile_ref != task.work_profile_ref:
                raise TaskConflict('Government inspection estimate substitutes its original work profile')
        for ref in task.dependency_refs:
            if ref.key() in sources:
                bound(read(ref, GovSchedulingDependencyView))
        for ref in task.work_fact_refs:
            if ref.key() in sources:
                fact = read(ref, GovSchedulingWorkFactView)
                bound(fact)
                if fact.organization_id != organization_id:
                    raise TaskConflict('Government inspection investment substitutes its original agency')
        if task.resource_calendar_ref is not None and task.resource_calendar_ref.key() in sources:
            calendar = read(task.resource_calendar_ref, GovReviewCalendarView)
            if calendar.organization_id != organization_id:
                raise TaskConflict('Government inspection calendar substitutes its original agency')
            for embedded in calendar.resources:
                if embedded.ref.key() in sources:
                    resource = read(embedded.ref, GovReviewResourceView)
                    if resource != embedded or resource.organization_id != organization_id:
                        raise TaskConflict('Government inspection calendar substitutes its original resource projection')
            for embedded in calendar.commitments:
                if embedded.commitment_ref.key() in sources:
                    commitment = read(embedded.commitment_ref, CapacityCommitment, identity_field='commitment_ref')
                    if commitment != embedded:
                        raise TaskConflict('Government inspection calendar substitutes its original occupancy projection')
        if task.existing_assignment_ref is not None and task.existing_assignment_ref.key() in sources:
            assignment = read(task.existing_assignment_ref, GovReviewAssignmentView)
            bound(assignment)
            if (assignment.organization_id != organization_id or assignment.case_ref != task.case_ref
                    or assignment.work_profile_ref != task.work_profile_ref):
                raise TaskConflict('Government inspection continuation substitutes its original assignment')
    if task.choice == 'report':
        for ref in task.check_rule_refs:
            if ref.key() in sources:
                check = legal(ref, 'check')
                if check.applicability_basis_ref is not None and check.applicability_basis_ref.key() in sources:
                    applicability = read(check.applicability_basis_ref, GovInspectionApplicabilityView)
                    bound(applicability)
                    if applicability.rule_ref != check.ref:
                        raise TaskConflict('Government inspection applicability substitutes its original rule')
                if check.result_ref is not None and check.result_ref.key() in sources:
                    result = read(check.result_ref, GovInspectionResultView)
                    bound(result)
                    if result.rule_ref != check.ref or result.observation_ref != check.observation_ref:
                        raise TaskConflict('Government inspection check result substitutes its original rule or observation')
    for ref in task.question_refs:
        if ref.key() not in sources:
            continue
        row = read(ref, GovInspectionQuestionView)
        bound(row)
        question = row.question
        if (row.issue_ref is not None and row.issue_ref not in task.prior_issue_refs
                or not scope_covers(action_input.scope, question.scope) or row.ref not in question.target_refs):
            raise TaskConflict('Government inspection question substitutes its original issue, coverage or targets')
        if question.requirement_ref.key() in sources:
            legal(question.requirement_ref, 'question')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref or response.scope != question.scope:
                raise TaskConflict('Government inspection response requirement substitutes its original rule or scope')
        for target_ref in question.target_refs:
            if target_ref.key() in sources:
                target = read(target_ref, GovInspectionQuestionView)
                bound(target)
                if target.issue_ref != row.issue_ref or target.question != question:
                    raise TaskConflict('Government inspection targets substitute their original question')
        for recipient_ref in question.recipient_refs:
            if recipient_ref.key() in sources:
                recipient = read(recipient_ref, GovRecipientView)
                if not scope_covers(recipient.scope, question.scope):
                    raise TaskConflict('Government inspection recipient lacks its original question coverage')

    for ref in action_input.prior_issue_refs:
        issue = read(ref, GovInspectionIssueView)
        bound(issue)
        if task.choice != 'recheck':
            continue
        for requirement_ref in issue.requirement_refs:
            if requirement_ref.key() in sources:
                requirement = read(requirement_ref, GovInspectionRequirementView)
                if requirement.issue_ref != issue.ref:
                    raise TaskConflict('Government inspection requirement substitutes its original issue')
                if requirement.verified_fact_ref is not None and requirement.verified_fact_ref.key() in sources:
                    fact = read(requirement.verified_fact_ref, GovRemedyVerificationView)
                    bound(fact)
                    if (fact.issue_ref != issue.ref or fact.requirement_ref != requirement.ref
                            or fact.requirement_content_sha256 != requirement.content_sha256):
                        raise TaskConflict('Government remedy verification substitutes its original issue or requirement content')
        for response_ref in issue.response_refs:
            if response_ref.key() in sources:
                response = read(response_ref, GovInspectionResponseView)
                bound(response)
                if response.issue_ref != issue.ref:
                    raise TaskConflict('Government inspection response substitutes its original issue')
                if response.responder_authority_ref.key() in sources:
                    delegation = read(response.responder_authority_ref, GovRemedyResponderAuthorityView)
                    if (delegation.issue_ref != issue.ref or delegation.actor_id != response.author_actor_id
                            or delegation.function_ref != response.author_function_ref
                            or delegation.organization_id != response.author_organization_id):
                        raise TaskConflict('Government remedy delegation substitutes its original responsible responder')
        for assessment_ref in issue.assessment_refs:
            if assessment_ref.key() in sources:
                assessment = read(assessment_ref, GovInspectionAssessmentView)
                if assessment.issue_ref != issue.ref:
                    raise TaskConflict('Government inspection reuse assessment substitutes its original issue')
        if issue.verification_result_ref is not None and issue.verification_result_ref.key() in sources:
            summary = read(issue.verification_result_ref, GovInspectionResultView)
            bound(summary)
            if summary.issue_ref != issue.ref or summary.rule_ref != action_input.inspection_basis_ref:
                raise TaskConflict('Government recheck summary substitutes its original issue or inspection basis')
    if task.choice == 'order_measure' and task.measure_basis_ref is not None and task.measure_basis_ref.key() in sources:
        basis = read(task.measure_basis_ref, GovMeasureBasisView)
        bound(basis)
        measure = basis.measure
        if measure.rule_ref.key() in sources:
            legal(measure.rule_ref, 'measure')
        if measure.authority_basis_ref.key() in sources:
            authority = read(measure.authority_basis_ref, GovInspectionAuthorityView)
            bound(authority)
            if (authority.organization_id != organization_id or authority.actor_id != context.actor_id
                    or authority.function_ref != context.function_ref or authority.measure_type_ref != measure.measure_type_ref
                    or authority.rule_ref != measure.rule_ref):
                raise TaskConflict('Government measure authority substitutes its original actor, type or rule')
        for ref in [*measure.affected_action_refs, measure.effect_rule_ref, measure.review_trigger_ref, basis.procedure_ref]:
            if ref.key() in sources:
                binding = read(ref, GovMeasureBindingView)
                if binding.measure_basis_ref != basis.ref:
                    raise TaskConflict('Government measure binding substitutes its original independent basis')
        if basis.procedure_verification_ref.key() in sources:
            verification = read(basis.procedure_verification_ref, GovMeasureProcedureVerificationView)
            if verification.measure_basis_ref != basis.ref or verification.procedure_ref != basis.procedure_ref:
                raise TaskConflict('Government measure verification substitutes its original procedure or basis')
    # The processor owns actual event/author/access validation, qualifications and
    # capacity, remedy fact and rule recomputation, measure permission/procedure,
    # complete issue coverage and assessment reuse. No work, measure or issue is changed.
