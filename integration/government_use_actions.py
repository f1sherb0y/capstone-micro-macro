"""Freeze original Government A11 use proofs, review plans and retained obligations."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.government_use_objects import (
    GovUseApplicationView, GovUseApplicationAuthorityView, GovUseProcedureView,
    GovUseWorkFactView, GovUseConditionView, GovUseDecisionBasisView, GovUseRuleView,
    GovUseQuestionView, GovUsePlanView, GovUseCapacityResultView, GovUseCaseView,
    GovReviewSubmissionView, GovDecisionAuthorityView, GovDecisionFindingView,
    GovDecisionAssessmentView, GovDecisionApplicabilityView, GovProcedureCompletionView,
    GovProcedureVerificationView, GovProcedureRequirementView, GovDecisionConditionBasisView,
    GovDecisionBindingView, GovPermitView, GovRecipientView, GovResponseRequirementView,
    GovSchedulingTaskView, GovSchedulingWorkProfileView, GovSchedulingEstimateView,
    GovSchedulingDependencyView, GovReviewCalendarView, GovReviewResourceView,
    GovReviewAssignmentView, government_use_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityCommitment
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentUse(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A11'


class GovernmentUseActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve original use-specific proofs without signing or releasing obligations.

    Actual completion, necessary checks, review capacity and retained conditions
    remain original processor decisions. A07 signs; A10 continues supervision.
    """
    ACTION_ID = 'GOV-A11'
    SOURCE_SCHEMAS = staticmethod(government_use_schemas)

    def build(self, context, *, scope, case_ref, use_application_ref, completed_scope_refs,
            professional_proof_refs, test_result_refs, permit_refs, remaining_condition_refs, procedure_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'case_ref': case_ref, 'use_application_ref': use_application_ref,
            'completed_scope_refs': completed_scope_refs, 'professional_proof_refs': professional_proof_refs,
            'test_result_refs': test_result_refs, 'permit_refs': permit_refs,
            'remaining_condition_refs': remaining_condition_refs, 'procedure_ref': procedure_ref},
            prepared_type=PreparedGovernmentUse, validate_sources=validate_government_use_sources)


def validate_government_use_sources(action_input, *, context, organization_id, sources):
    """Bind current use versions and actual source identities without inferring use approval."""
    def read(ref, schema, *, linked=False, identity_field='ref'):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or getattr(row, identity_field).key() != ref.key():
            raise TaskConflict('Government use lacks its exact original concrete source')
        if hasattr(row, 'scope') and not linked and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government use source leaves its original application scope')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government use input leaves its original invocation scope')
    fields = ('completed_scope_refs', 'professional_proof_refs', 'test_result_refs',
        'permit_refs', 'remaining_condition_refs')
    for field in fields:
        unique_refs(getattr(action_input, field))
    case = read(action_input.case_ref, GovUseCaseView)
    application = read(action_input.use_application_ref, GovUseApplicationView)
    procedure = read(action_input.procedure_ref, GovUseProcedureView)
    if (case.organization_id != organization_id or application.case_ref != case.ref
            or application.applicant_id != case.applicant_id or application.recipient_organization_id != organization_id
            or application.scope != action_input.scope or case.current_submission_ref != application.submission_ref
            or procedure.organization_id != organization_id or procedure.case_ref != case.ref
            or procedure.application_ref != application.ref or procedure.content_sha256 != application.content_sha256
            or procedure.ref != case.procedure_ref or procedure.ref != application.procedure_ref
            or procedure.actor_id != context.actor_id or procedure.function_ref != context.function_ref
            or procedure.authorization_ref not in context.authorization_refs):
        raise TaskConflict('Government use substitutes its original agency, applicant, version or acting procedure')
    if application.submission_ref.key() in sources:
        submission = read(application.submission_ref, GovReviewSubmissionView)
        if (submission.applicant_id != application.applicant_id or submission.recipient_organization_id != organization_id
                or submission.content_sha256 != application.content_sha256 or submission.procedure_ref != procedure.ref
                or submission.matter_ref != case.matter_ref or submission.jurisdiction_ref != case.jurisdiction_ref):
            raise TaskConflict('Government use submission substitutes its original current content or procedure')

    def bound(row):
        if (row.case_ref != case.ref or row.submission_ref != application.submission_ref
                or row.content_sha256 != application.content_sha256):
            raise TaskConflict('Government use proof substitutes its original current case, submission or content')

    def original_rule(ref):
        row = read(ref, GovUseRuleView)
        if row.application_ref != application.ref:
            raise TaskConflict('Government use rule substitutes its original application')
        return row

    if application.application_authority_ref.key() in sources:
        authority = read(application.application_authority_ref, GovUseApplicationAuthorityView)
        if (authority.application_ref != application.ref or authority.applicant_id != application.applicant_id
                or authority.submitter_id != application.submitter_id):
            raise TaskConflict('Government use delegation substitutes its original applicant or submitter')
    for ref in action_input.completed_scope_refs:
        fact = read(ref, GovUseWorkFactView)
        if fact.case_ref != case.ref or fact.work_kind != 'completed_scope':
            raise TaskConflict('Government use completion source substitutes its original case or work type')
    for ref in action_input.professional_proof_refs:
        assessment = read(ref, GovDecisionAssessmentView)
        bound(assessment)
        for result_ref in assessment.check_result_refs:
            if result_ref.key() in sources:
                result = read(result_ref, GovDecisionFindingView)
                if (result.assessment_ref != assessment.ref or result.submission_ref != application.submission_ref
                        or result.content_sha256 != application.content_sha256):
                    raise TaskConflict('Government use finding substitutes its original proof or version')
    for ref in action_input.test_result_refs:
        result = read(ref, GovDecisionFindingView)
        if result.submission_ref != application.submission_ref or result.content_sha256 != application.content_sha256:
            raise TaskConflict('Government use test result substitutes its original current submission')
        if result.applicability_basis_ref is not None and result.applicability_basis_ref.key() in sources:
            applicability = read(result.applicability_basis_ref, GovDecisionApplicabilityView)
            if (applicability.check_ref != result.check_ref or applicability.submission_ref != application.submission_ref
                    or applicability.content_sha256 != application.content_sha256):
                raise TaskConflict('Government use applicability substitutes its original check or version')
    for ref in action_input.permit_refs:
        permit = read(ref, GovPermitView, linked=True)
        if permit.organization_id != organization_id or not scope_covers(permit.scope, action_input.scope):
            raise TaskConflict('Government use permit substitutes its original agency or coverage')
    for ref in action_input.remaining_condition_refs:
        condition = read(ref, GovUseConditionView, linked=True)
        if condition.permit_ref not in action_input.permit_refs:
            raise TaskConflict('Government remaining condition substitutes its original existing permit')
        if condition.condition_rule_ref.key() in sources:
            if original_rule(condition.condition_rule_ref).condition_ref != condition.ref:
                raise TaskConflict('Government remaining condition substitutes its original independent rule')
    for ref in procedure.question_refs:
        if ref.key() not in sources:
            continue
        row = read(ref, GovUseQuestionView)
        question = row.question
        if (row.application_ref != application.ref or not scope_covers(action_input.scope, question.scope)
                or row.ref not in question.target_refs):
            raise TaskConflict('Government use question substitutes its original application, scope or targets')
        if question.requirement_ref.key() in sources:
            if original_rule(question.requirement_ref).question_ref != row.ref:
                raise TaskConflict('Government use question substitutes its original legal rule')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref or response.scope != question.scope:
                raise TaskConflict('Government use response requirement substitutes its original rule or scope')
        for target_ref in question.target_refs:
            if target_ref.key() in sources:
                target = read(target_ref, GovUseQuestionView)
                if target.application_ref != application.ref or target.question != question:
                    raise TaskConflict('Government use targets substitute their original question')
        for recipient_ref in question.recipient_refs:
            if recipient_ref.key() in sources:
                recipient = read(recipient_ref, GovRecipientView)
                if not scope_covers(recipient.scope, question.scope):
                    raise TaskConflict('Government use recipient lacks its original question coverage')

    if procedure.choice in {'plan_verification', 'continue_supervision'}:
        if procedure.plan_ref is None or procedure.plan_ref.key() not in sources:
            return
        plan = read(procedure.plan_ref, GovUsePlanView)
        purpose = 'use_verification' if procedure.choice == 'plan_verification' else 'continuing_supervision'
        if (plan.application_ref != application.ref or plan.content_sha256 != application.content_sha256
                or plan.purpose != purpose):
            raise TaskConflict('Government use plan substitutes its original application version or purpose')
        if plan.plan.work_profile_ref.key() in sources:
            work = read(plan.plan.work_profile_ref, GovSchedulingWorkProfileView)
            if work.organization_id != organization_id:
                raise TaskConflict('Government use plan borrows another agency work profile')
        if plan.resource_calendar_ref.key() in sources:
            calendar = read(plan.resource_calendar_ref, GovReviewCalendarView)
            if calendar.organization_id != organization_id:
                raise TaskConflict('Government use calendar substitutes its original agency')
            for embedded in calendar.resources:
                if embedded.ref.key() in sources:
                    resource = read(embedded.ref, GovReviewResourceView)
                    if resource != embedded or resource.organization_id != organization_id:
                        raise TaskConflict('Government use calendar substitutes its original resource projection')
            for embedded in calendar.commitments:
                if embedded.commitment_ref.key() in sources:
                    commitment = read(embedded.commitment_ref, CapacityCommitment, identity_field='commitment_ref')
                    if commitment != embedded:
                        raise TaskConflict('Government use calendar substitutes its original occupancy projection')
        for item in plan.plan.items:
            if item.task_ref.key() not in sources:
                continue
            task = read(item.task_ref, GovSchedulingTaskView)
            if (task.organization_id != organization_id or task.case_ref != case.ref
                    or task.work_profile_ref != plan.plan.work_profile_ref):
                raise TaskConflict('Government use plan task substitutes its original agency, case or profile')
            if task.estimate_ref.key() in sources:
                estimate = read(task.estimate_ref, GovSchedulingEstimateView)
                if estimate.task_ref != task.ref or estimate.work_profile_ref != task.work_profile_ref:
                    raise TaskConflict('Government use effort estimate substitutes its original task or profile')
            for ref in task.work_fact_refs:
                if ref.key() in sources:
                    fact = read(ref, GovUseWorkFactView)
                    if fact.task_ref != task.ref or fact.case_ref != case.ref or fact.work_kind != 'review_effort':
                        raise TaskConflict('Government use review investment substitutes its original task or work type')
            for ref in task.dependency_refs:
                if ref.key() in sources and read(ref, GovSchedulingDependencyView).task_ref != task.ref:
                    raise TaskConflict('Government use dependency substitutes its original task')
        if plan.capacity_result_ref.key() in sources:
            capacity = read(plan.capacity_result_ref, GovUseCapacityResultView)
            if capacity.plan_ref != plan.ref:
                raise TaskConflict('Government use capacity result substitutes its original plan')
        return
    if (procedure.choice != 'propose_use_decision' or procedure.decision_basis_ref is None
            or procedure.decision_basis_ref.key() not in sources):
        return
    basis = read(procedure.decision_basis_ref, GovUseDecisionBasisView)
    draft = basis.draft
    if (basis.application_ref != application.ref or basis.content_sha256 != application.content_sha256
            or draft.case_ref != case.ref or draft.submission_ref != application.submission_ref
            or draft.covered_scope != action_input.scope or draft.decision_basis_ref != basis.ref):
        raise TaskConflict('Government use draft substitutes its original use case, application or basis')
    if basis.decision_rule_ref.key() in sources:
        original_rule(basis.decision_rule_ref)
    if basis.authority_ref.key() in sources:
        authority = read(basis.authority_ref, GovDecisionAuthorityView)
        if (authority.organization_id != organization_id or authority.actor_id != basis.signer_actor_id
                or authority.function_ref != basis.signer_function_ref or authority.case_ref != case.ref
                or authority.submission_ref != application.submission_ref or authority.decision_basis_ref != basis.ref):
            raise TaskConflict('Government use signing authority substitutes its independent A07 signer or basis')
    if procedure.completion_ref is not None and procedure.completion_ref.key() in sources:
        completion = read(procedure.completion_ref, GovProcedureCompletionView)
        bound(completion)
        if completion.procedure_ref != procedure.ref:
            raise TaskConflict('Government use completion substitutes its original procedure')
        for ref in completion.verification_refs:
            if ref.key() in sources:
                verification = read(ref, GovProcedureVerificationView)
                bound(verification)
                if verification.requirement_ref.key() in sources:
                    requirement = read(verification.requirement_ref, GovProcedureRequirementView)
                    if requirement.procedure_ref != procedure.ref:
                        raise TaskConflict('Government use verification substitutes its original procedure requirement')
    for ref in basis.condition_basis_refs:
        if ref.key() in sources:
            condition_basis = read(ref, GovDecisionConditionBasisView)
            if condition_basis.decision_basis_ref != basis.ref:
                raise TaskConflict('Government use condition basis substitutes its original draft')
    bindings = [draft.expiry_rule_ref] if draft.expiry_rule_ref is not None else []
    for condition in draft.conditions:
        bindings.extend(condition.affected_action_refs)
        bindings.extend(condition.required_evidence_refs)
        if condition.due_rule_ref is not None:
            bindings.append(condition.due_rule_ref)
    for ref in set(bindings):
        if ref.key() in sources and read(ref, GovDecisionBindingView).decision_basis_ref != basis.ref:
            raise TaskConflict('Government use requirement substitutes its original authorized basis')
    for ref in case.review_assignment_refs:
        if ref.key() in sources:
            assignment = read(ref, GovReviewAssignmentView)
            if assignment.organization_id != organization_id or assignment.case_ref != case.ref:
                raise TaskConflict('Government use closure substitutes its original review assignment')
    # The processor owns actual completed scope, proof/method coverage, independent
    # A07 signing permission, plan capacity and qualifications, continuing duties
    # and release of only unused assignments. Assembly creates no use permission,
    # physical handover, fee clearance, loan discharge or obligation release.
