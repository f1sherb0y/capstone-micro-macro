"""Freeze original Government A07 signing bases and recoverable decision facts."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.government_objects import GovJurisdictionView, GovMatterView
from src.actions.contracts.government_review_objects import GovReviewSubmissionView
from src.actions.contracts.government_decision_objects import (
    GovDecisionCaseView, GovDecisionBasisView, GovDecisionAuthorityView, GovDecisionProcedureView,
    GovDecisionRuleView, GovDecisionFindingView, GovDecisionAssessmentView, GovDecisionReuseView,
    GovDecisionApplicabilityView, GovDecisionIssueView, GovProcedureRequirementView,
    GovProcedureVerificationView, GovProcedureCompletionView, GovDecisionConditionBasisView,
    GovDecisionEffectView, GovDecisionBindingView, GovDecisionCommandView, GovFormalDecisionView,
    GovDecisionNotificationView, government_decision_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentDecision(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A07'


class GovernmentDecisionActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve original signer and draft identities without signing or submitting.

    Necessary checks, independent signing authority and formal-fact recovery
    remain original processor decisions. The formal service creates the signed ID.
    """
    ACTION_ID = 'GOV-A07'
    SOURCE_SCHEMAS = staticmethod(government_decision_schemas)

    def build(self, context, *, scope, case_ref, current_submission_ref, assessment_refs,
            unresolved_issue_refs, procedure_completion_ref, decision_basis_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'case_ref': case_ref, 'current_submission_ref': current_submission_ref,
            'assessment_refs': assessment_refs, 'unresolved_issue_refs': unresolved_issue_refs,
            'procedure_completion_ref': procedure_completion_ref, 'decision_basis_ref': decision_basis_ref},
            prepared_type=PreparedGovernmentDecision, validate_sources=validate_government_decision_sources)


def validate_government_decision_sources(action_input, *, context, organization_id, sources):
    """Bind original final-version sources while preserving historical review facts."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government decision lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government decision source leaves its original requested scope')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government decision input leaves its original invocation scope')
    unique_refs(action_input.assessment_refs)
    unique_refs(action_input.unresolved_issue_refs)
    case = read(action_input.case_ref, GovDecisionCaseView)
    submission = read(action_input.current_submission_ref, GovReviewSubmissionView)
    basis = read(action_input.decision_basis_ref, GovDecisionBasisView)
    draft = basis.draft

    def bound(row):
        if (getattr(row, 'case_ref', case.ref) != case.ref or row.submission_ref != submission.ref
                or row.content_sha256 != submission.content_sha256):
            raise TaskConflict('Government decision source substitutes its original final submission content or case')

    bound(basis)
    if (case.organization_id != organization_id or case.current_submission_ref != submission.ref
            or submission.recipient_organization_id != organization_id or submission.applicant_id != case.applicant_id
            or submission.matter_ref != case.matter_ref or submission.jurisdiction_ref != case.jurisdiction_ref
            or submission.procedure_ref != case.procedure_ref
            or draft.case_ref != case.ref or draft.submission_ref != submission.ref
            or draft.covered_scope != action_input.scope or draft.decision_basis_ref != basis.ref
            or basis.signer_actor_id != context.actor_id or basis.signer_function_ref != context.function_ref):
        raise TaskConflict('Government decision substitutes its original agency, applicant, draft or acting signer')
    if case.jurisdiction_ref.key() in sources:
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView)
        if jurisdiction.organization_id != organization_id:
            raise TaskConflict('Government decision borrows another agency jurisdiction')
    if case.matter_ref.key() in sources:
        read(case.matter_ref, GovMatterView)
    if basis.decision_authority_ref.key() in sources:
        authority = read(basis.decision_authority_ref, GovDecisionAuthorityView)
        if (authority.organization_id != organization_id or authority.actor_id != context.actor_id
                or authority.function_ref != context.function_ref or authority.case_ref != case.ref
                or authority.submission_ref != submission.ref or authority.decision_basis_ref != basis.ref):
            raise TaskConflict('Government signing authority substitutes its original signer, case or basis')
    if basis.procedure_ref.key() in sources:
        procedure = read(basis.procedure_ref, GovDecisionProcedureView)
        if (procedure.case_ref != case.ref
                or (procedure.source_procedure_ref or procedure.ref) != case.procedure_ref):
            raise TaskConflict('Government decision procedure substitutes its original case or received source procedure')
    elif basis.procedure_ref != case.procedure_ref:
        raise TaskConflict('Government decision lacks its case-specific source procedure binding')
    if basis.decision_rule_ref.key() in sources:
        rule = read(basis.decision_rule_ref, GovDecisionRuleView)
        if rule.case_ref != case.ref or rule.procedure_ref != basis.procedure_ref:
            raise TaskConflict('Government decision rule substitutes its original case or procedure')
    if draft.effect_rule_ref.key() in sources:
        effect = read(draft.effect_rule_ref, GovDecisionEffectView)
        if effect.decision_rule_ref != basis.decision_rule_ref or effect.outcome != draft.outcome:
            raise TaskConflict('Government decision effect substitutes its original outcome or rule')

    command = None
    if basis.command_ref.key() in sources:
        command = read(basis.command_ref, GovDecisionCommandView)
        if (command.case_ref != case.ref or command.submission_ref != submission.ref
                or command.decision_basis_ref != basis.ref or command.operation_id != context.operation_id):
            raise TaskConflict('Government decision command substitutes its original invocation or draft basis')
    for ref in case.decision_refs:
        if ref.key() not in sources:
            continue
        official = read(ref, GovFormalDecisionView)
        if official.case_ref != case.ref:
            raise TaskConflict('Government formal decision history substitutes its original case')
        if command is not None and official.business_key == command.business_key:
            if (official.command_ref != command.ref or official.submission_ref != submission.ref
                    or official.draft_sha256 != command.draft_sha256
                    or official.signer_actor_id != basis.signer_actor_id
                    or official.signer_function_ref != basis.signer_function_ref):
                raise TaskConflict('Government recovered decision substitutes its original command or signer')
            for notification_ref in official.notification_refs:
                if notification_ref.key() in sources:
                    notification = read(notification_ref, GovDecisionNotificationView)
                    if (notification.decision_ref != official.ref
                            or notification.recipient_id not in draft.notification_recipient_ids):
                        raise TaskConflict('Government decision notification substitutes its original record or recipient')

    for ref in action_input.assessment_refs:
        assessment = read(ref, GovDecisionAssessmentView)
        if assessment.case_ref != case.ref:
            raise TaskConflict('Government decision assessment substitutes its original case')
        # An older review retains its original submission/content. The processor
        # decides whether explicit current reuse permission covers each check.
        if assessment.reuse_basis_ref is not None and assessment.reuse_basis_ref.key() in sources:
            reuse = read(assessment.reuse_basis_ref, GovDecisionReuseView)
            bound(reuse)
            if (reuse.assessment_ref != assessment.ref or reuse.original_submission_ref != assessment.submission_ref
                    or reuse.original_content_sha256 != assessment.content_sha256):
                raise TaskConflict('Government decision reuse substitutes its original reviewed content')
        for result_ref in assessment.check_result_refs:
            if result_ref.key() not in sources:
                continue
            finding = read(result_ref, GovDecisionFindingView)
            if (finding.assessment_ref != assessment.ref or finding.submission_ref != assessment.submission_ref
                    or finding.content_sha256 != assessment.content_sha256):
                raise TaskConflict('Government decision finding substitutes its original assessment or content')
            if finding.applicability_basis_ref is not None and finding.applicability_basis_ref.key() in sources:
                applicability = read(finding.applicability_basis_ref, GovDecisionApplicabilityView)
                if applicability.check_ref != finding.check_ref:
                    raise TaskConflict('Government decision applicability substitutes its original check')
                # The processor checks current applicability when that finding is used.
    for ref in action_input.unresolved_issue_refs:
        issue = read(ref, GovDecisionIssueView)
        if issue.case_ref != case.ref or issue.submission_ref != submission.ref:
            raise TaskConflict('Government decision issue substitutes its original final case or submission')
    if action_input.procedure_completion_ref is not None:
        completion = read(action_input.procedure_completion_ref, GovProcedureCompletionView)
        bound(completion)
        if completion.procedure_ref != basis.procedure_ref:
            raise TaskConflict('Government procedure completion substitutes its original procedure')
        for ref in completion.verification_refs:
            if ref.key() in sources:
                verification = read(ref, GovProcedureVerificationView)
                bound(verification)
                if verification.requirement_ref.key() in sources:
                    requirement = read(verification.requirement_ref, GovProcedureRequirementView)
                    if requirement.procedure_ref != basis.procedure_ref:
                        raise TaskConflict('Government procedure verification substitutes its original requirement')
    for ref in basis.condition_basis_refs:
        if ref.key() in sources:
            condition_basis = read(ref, GovDecisionConditionBasisView)
            if condition_basis.decision_basis_ref != basis.ref:
                raise TaskConflict('Government conditional approval basis substitutes its original draft basis')
    bindings = [draft.expiry_rule_ref] if draft.expiry_rule_ref is not None else []
    for condition in draft.conditions:
        bindings.extend(condition.affected_action_refs)
        bindings.extend(condition.required_evidence_refs)
        if condition.due_rule_ref is not None:
            bindings.append(condition.due_rule_ref)
    for ref in set(bindings):
        if ref.key() in sources:
            binding = read(ref, GovDecisionBindingView)
            if binding.decision_basis_ref != basis.ref:
                raise TaskConflict('Government decision requirement substitutes its original authorized basis')
    # The processor owns full draft hashing, command lookup/recovery, formal
    # notification/effect, signer permission, required check/procedure evidence,
    # review reuse and lawful conditional/adverse outcomes. Assembly signs nothing.
