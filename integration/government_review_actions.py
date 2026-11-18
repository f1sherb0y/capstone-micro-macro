"""Freeze original Government A04 submissions and independently saved review sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_objects import (
    GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingCaseView, GovReviewAssignmentView, GovSchedulingDependencyView,
)
from src.actions.contracts.government_review_objects import (
    GovReviewSubmissionView, GovReviewTaskView, GovReviewRuleView, GovReviewApplicabilityView,
    GovReviewFactView, GovProfessionalFinding, GovProfessionalOpinionView, GovReviewResultView,
    GovReviewQuestionView, GovReviewConditionView, GovReviewConditionAuthorityView,
    GovReviewConditionBindingView, GovReviewReuseView, government_review_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentReview(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A04'


class GovernmentReviewActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve original review versions without creating verification evidence.

    Independent authorship, applicability, supported methods and evidence
    recomputation remain original processor decisions. No decision is signed.
    """
    ACTION_ID = 'GOV-A04'
    SOURCE_SCHEMAS = staticmethod(government_review_schemas)

    def build(self, context, *, scope, case_ref, submission_ref, task_ref, rule_refs,
            professional_refs, verified_evidence_refs, method_result_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'case_ref': case_ref, 'submission_ref': submission_ref,
            'task_ref': task_ref, 'rule_refs': rule_refs, 'professional_refs': professional_refs,
            'verified_evidence_refs': verified_evidence_refs, 'method_result_refs': method_result_refs},
            prepared_type=PreparedGovernmentReview, validate_sources=validate_government_review_sources)


def validate_government_review_sources(action_input, *, context, organization_id, sources):
    """Bind original sources while retaining historical professional opinions."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government review lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government review source leaves its original requested scope')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government review input leaves its original invocation scope')
    for refs in (action_input.rule_refs, action_input.professional_refs,
            action_input.verified_evidence_refs, action_input.method_result_refs):
        unique_refs(refs)
    case = read(action_input.case_ref, GovSchedulingCaseView)
    submission = read(action_input.submission_ref, GovReviewSubmissionView)
    task = read(action_input.task_ref, GovReviewTaskView)
    if (case.organization_id != organization_id or task.organization_id != organization_id
            or task.case_ref != case.ref or case.current_submission_ref != submission.ref
            or task.submission_ref != submission.ref or task.content_sha256 != submission.content_sha256
            or task.ref not in case.task_refs or task.function_ref != context.function_ref
            or submission.recipient_organization_id != organization_id
            or submission.matter_ref != case.matter_ref or submission.jurisdiction_ref != case.jurisdiction_ref
            or submission.procedure_ref != case.procedure_ref):
        raise TaskConflict('Government review substitutes its original agency, task or final submission')

    def bound(row, rule_ref=None):
        if (row.submission_ref != submission.ref or row.content_sha256 != submission.content_sha256
                or hasattr(row, 'case_ref') and row.case_ref != case.ref
                or rule_ref is not None and row.rule_ref != rule_ref):
            raise TaskConflict('Government review source substitutes its original submission content, case or rule')

    if case.matter_ref.key() in sources:
        read(case.matter_ref, GovMatterView)
    if case.jurisdiction_ref.key() in sources:
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView)
        if jurisdiction.organization_id != organization_id:
            raise TaskConflict('Government review borrows another agency jurisdiction')
    if task.assignment_ref.key() in sources:
        assignment = read(task.assignment_ref, GovReviewAssignmentView)
        if (assignment.organization_id != organization_id or assignment.case_ref != case.ref
                or assignment.task_ref != task.ref):
            raise TaskConflict('Government review assignment substitutes its original task or agency')
    for ref in task.dependency_refs:
        if ref.key() in sources:
            dependency = read(ref, GovSchedulingDependencyView)
            if dependency.task_ref != task.ref:
                raise TaskConflict('Government review dependency substitutes its original task')
    for ref in action_input.verified_evidence_refs:
        read(ref, EvidenceRecord)

    question_refs = list(task.question_refs)
    for ref in action_input.rule_refs:
        rule = read(ref, GovReviewRuleView)
        bound(rule)
        if rule.organization_id != organization_id or rule.jurisdiction_ref != case.jurisdiction_ref:
            raise TaskConflict('Government review rule substitutes its original agency or jurisdiction')
        question_refs.extend(rule.question_refs)
        if rule.applicability_ref.key() in sources:
            bound(read(rule.applicability_ref, GovReviewApplicabilityView), rule.ref)
        if rule.fact_ref is not None and rule.fact_ref.key() in sources:
            bound(read(rule.fact_ref, GovReviewFactView), rule.ref)
        if rule.result_ref is not None and rule.result_ref.key() in sources:
            result = read(rule.result_ref, GovReviewResultView)
            bound(result, rule.ref)
            if result.task_ref != task.ref:
                raise TaskConflict('Government review rule execution substitutes its original task')
    for ref in action_input.method_result_refs:
        result = read(ref, GovReviewResultView)
        bound(result)
        if result.task_ref != task.ref or result.rule_ref not in action_input.rule_refs:
            raise TaskConflict('Government review execution substitutes its original task or rule set')

    for ref in action_input.professional_refs:
        opinion = read(ref, GovProfessionalOpinionView)
        # Older opinions remain original historical versions. Independent
        # current reuse permission and profession coverage belong to the processor.
        for finding_ref in opinion.verification_refs:
            if finding_ref.key() in sources:
                finding = read(finding_ref, GovProfessionalFinding)
                if (finding.assessment_ref != opinion.ref or finding.submission_ref != opinion.submission_ref
                        or finding.content_sha256 != opinion.content_sha256
                        or finding.author_organization_id != opinion.author_organization_id):
                    raise TaskConflict('Government professional opinion substitutes its original verification')
    for ref in task.reuse_basis_refs:
        if ref.key() in sources:
            reuse = read(ref, GovReviewReuseView)
            bound(reuse)
            if (reuse.task_ref != task.ref or reuse.rule_ref not in action_input.rule_refs
                    or reuse.assessment_ref not in action_input.professional_refs):
                raise TaskConflict('Government review reuse substitutes its original task, rule or opinion')

    for ref in set(question_refs):
        if ref.key() not in sources:
            continue
        row = read(ref, GovReviewQuestionView)
        bound(row)
        question = row.question
        if (row.task_ref != task.ref or question.scope != row.scope or row.ref not in question.target_refs
                or question.requirement_ref not in action_input.rule_refs):
            raise TaskConflict('Government review question substitutes its original task, scope or legal rule')
        for target_ref in question.target_refs:
            if target_ref.key() in sources:
                target = read(target_ref, GovReviewQuestionView)
                bound(target)
                if target.task_ref != task.ref or target.question != question:
                    raise TaskConflict('Government review targets substitute their original question')
        for recipient_ref in question.recipient_refs:
            if recipient_ref.key() in sources:
                recipient = read(recipient_ref, GovRecipientView)
                if recipient.scope != question.scope:
                    raise TaskConflict('Government review recipient substitutes its original question scope')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref or response.scope != question.scope:
                raise TaskConflict('Government review response substitutes its original rule or scope')

    for ref in task.condition_refs:
        if ref.key() not in sources:
            continue
        condition = read(ref, GovReviewConditionView)
        bound(condition)
        if condition.task_ref != task.ref or condition.condition_rule_ref not in action_input.rule_refs:
            raise TaskConflict('Government condition proposal substitutes its original task or rule')
        if condition.proposal_authority_ref.key() in sources:
            authority = read(condition.proposal_authority_ref, GovReviewConditionAuthorityView)
            if (authority.organization_id != organization_id or authority.actor_id != context.actor_id
                    or authority.function_ref != context.function_ref or authority.condition_ref != condition.ref
                    or any(getattr(authority, field) != getattr(condition, field) for field in (
                        'responsible_party_ids', 'verifier_binding_ref', 'affected_action_refs',
                        'required_evidence_refs', 'verification_method_ref', 'due_rule_ref'))):
                raise TaskConflict('Government condition proposal substitutes its independent authority or requirements')
        bindings = [*condition.affected_action_refs, *condition.required_evidence_refs]
        if condition.due_rule_ref is not None:
            bindings.append(condition.due_rule_ref)
        for binding_ref in bindings:
            if binding_ref.key() in sources:
                binding = read(binding_ref, GovReviewConditionBindingView)
                if (binding.condition_ref != condition.ref or binding.rule_ref != condition.condition_rule_ref
                        or binding.scope != condition.scope):
                    raise TaskConflict('Government condition requirement substitutes its original proposal or scope')
    # Readiness, current lawful jurisdiction, exact declared source sets, author
    # authority, evidence verification, method reports and unknown/failed results
    # stay with the original processor. No quality finding or permission is invented.
