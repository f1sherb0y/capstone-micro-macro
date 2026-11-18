"""Freeze original Government A09 requests, prior effects and decision-change bases."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_transition_objects import (
    GovTransitionDecisionView, GovTransitionPermitView, GovTransitionApplicationView,
    GovTransitionApplicantAuthorityView, GovTransitionRuleView, GovChangeBasisView,
    GovChangeAuthorityView, GovChangeProcedureView, GovChangeEffectView, GovExpiryFactView,
    GovTransitionQuestionView, GovReviewSubmissionView, GovDecisionCommandView,
    GovDecisionNotificationView, GovDecisionAssessmentView, GovDecisionFindingView,
    GovProcedureCompletionView, GovProcedureVerificationView, GovProcedureRequirementView,
    GovDecisionConditionBasisView, GovDecisionBindingView, GovRecipientView,
    GovResponseRequirementView, government_transition_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentTransition(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A09'


class GovernmentTransitionActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve prior effects without extending, stopping or changing a decision.

    Independent change authority, applicable policy and received expiry facts
    remain original processor decisions. Applications and drafts create no effect.
    """
    ACTION_ID = 'GOV-A09'
    SOURCE_SCHEMAS = staticmethod(government_transition_schemas)

    def build(self, context, *, scope, application_ref, prior_decision_ref, permit_ref,
            affected_submission_ref, evidence_refs, transition_rule_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'application_ref': application_ref, 'prior_decision_ref': prior_decision_ref,
            'permit_ref': permit_ref, 'affected_submission_ref': affected_submission_ref,
            'evidence_refs': evidence_refs, 'transition_rule_ref': transition_rule_ref},
            prepared_type=PreparedGovernmentTransition,
            validate_sources=validate_government_transition_sources)


def validate_government_transition_sources(action_input, *, context, organization_id, sources):
    """Bind original parties and versions while retaining broader prior coverage."""
    def read(ref, schema, *, linked=False):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government transition lacks its exact original concrete source')
        if hasattr(row, 'scope') and not linked and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government transition source leaves its original requested scope')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government transition input leaves its original invocation scope')
    unique_refs(action_input.evidence_refs)
    for ref in action_input.evidence_refs:
        read(ref, EvidenceRecord)
    prior = read(action_input.prior_decision_ref, GovTransitionDecisionView, linked=True)
    if (prior.organization_id != organization_id or not scope_covers(prior.scope, action_input.scope)
            or prior.permit_ref != action_input.permit_ref):
        raise TaskConflict('Government transition substitutes its original agency, prior decision or permit')
    permit = None
    if action_input.permit_ref is not None:
        permit = read(action_input.permit_ref, GovTransitionPermitView, linked=True)
        if (permit.decision_ref != prior.ref or permit.organization_id != organization_id
                or not scope_covers(permit.scope, action_input.scope)):
            raise TaskConflict('Government transition permit substitutes its original decision or coverage')
    submission = None
    if action_input.affected_submission_ref is not None:
        submission = read(action_input.affected_submission_ref, GovReviewSubmissionView)
        if submission.recipient_organization_id != organization_id or submission.applicant_id != prior.applicant_id:
            raise TaskConflict('Government transition submission substitutes its original applicant or recipient')
    content_hash = submission.content_sha256 if submission is not None else None
    if action_input.application_ref is not None:
        application = read(action_input.application_ref, GovTransitionApplicationView)
        if (application.applicant_id != prior.applicant_id or application.recipient_organization_id != organization_id
                or application.prior_decision_ref != prior.ref or application.permit_ref != action_input.permit_ref
                or application.affected_submission_ref != action_input.affected_submission_ref
                or application.content_sha256 != content_hash):
            raise TaskConflict('Government transition application substitutes its original parties, permit or affected content')
        if application.submitter_authority_ref.key() in sources:
            submitter = read(application.submitter_authority_ref, GovTransitionApplicantAuthorityView)
            if (submitter.application_ref != application.ref or submitter.applicant_id != prior.applicant_id
                    or submitter.submitter_actor_id != application.author_actor_id
                    or submitter.submitter_function_ref != application.author_function_ref
                    or submitter.submitter_organization_id != application.author_organization_id):
                raise TaskConflict('Government transition delegation substitutes its original applicant or submitter')

    def bound_rule(ref, purpose):
        row = read(ref, GovTransitionRuleView, linked=True)
        if (row.organization_id != organization_id or row.prior_decision_ref != prior.ref
                or row.permit_ref != action_input.permit_ref or row.application_ref != action_input.application_ref
                or row.affected_submission_ref != action_input.affected_submission_ref or row.content_sha256 != content_hash
                or row.purpose != purpose or not scope_covers(row.scope, action_input.scope)
                or not scope_covers(row.transition_scope, action_input.scope)):
            raise TaskConflict('Government transition rule substitutes its original target, version or coverage')
        return row

    rule = bound_rule(action_input.transition_rule_ref, 'transition')
    for ref in rule.coverage_rule_refs:
        if ref.key() in sources:
            bound_rule(ref, 'coverage')
    if rule.review_rule_ref is not None and rule.review_rule_ref.key() in sources:
        bound_rule(rule.review_rule_ref, 'review')
    if rule.expiry_rule_ref is not None and rule.expiry_rule_ref.key() in sources:
        bound_rule(rule.expiry_rule_ref, 'expiry')
    if permit is not None and permit.expiry_event_ref is not None and permit.expiry_event_ref.key() in sources:
        expiry = read(permit.expiry_event_ref, GovExpiryFactView, linked=True)
        if (expiry.permit_ref != permit.ref or expiry.prior_decision_ref != prior.ref
                or expiry.expiry_rule_ref != permit.expiry_rule_ref):
            raise TaskConflict('Government scheduled expiry substitutes its original core fact target')
    for ref in rule.question_refs:
        if ref.key() not in sources:
            continue
        row = read(ref, GovTransitionQuestionView)
        question = row.question
        if (row.prior_decision_ref != prior.ref or not scope_covers(action_input.scope, question.scope)
                or row.ref not in question.target_refs):
            raise TaskConflict('Government transition question substitutes its original decision, scope or targets')
        if question.requirement_ref.key() in sources:
            bound_rule(question.requirement_ref, 'question')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref or response.scope != question.scope:
                raise TaskConflict('Government transition response requirement substitutes its original rule or scope')
        for target_ref in question.target_refs:
            if target_ref.key() in sources:
                target = read(target_ref, GovTransitionQuestionView)
                if target.prior_decision_ref != prior.ref or target.question != question:
                    raise TaskConflict('Government transition targets substitute their original question')
        for recipient_ref in question.recipient_refs:
            if recipient_ref.key() in sources:
                recipient = read(recipient_ref, GovRecipientView)
                if not scope_covers(recipient.scope, question.scope):
                    raise TaskConflict('Government transition recipient lacks its original question coverage')

    def notifications(decision, effect):
        for ref in decision.notification_refs:
            if ref.key() in sources:
                notification = read(ref, GovDecisionNotificationView, linked=True)
                if (notification.decision_ref != decision.ref
                        or notification.recipient_id not in effect.notification_recipient_ids):
                    raise TaskConflict('Government transition notification substitutes its original decision or recipient')

    if rule.choice == 'confirm_coverage' and prior.effect_rule_ref.key() in sources:
        effect = read(prior.effect_rule_ref, GovChangeEffectView, linked=True)
        if effect.decision_ref != prior.ref or effect.outcome != prior.outcome:
            raise TaskConflict('Government original coverage effect substitutes its prior decision')
        notifications(prior, effect)
    if (rule.choice not in {'renew', 'suspend', 'revoke', 'restore'}
            or rule.decision_basis_ref is None or rule.decision_basis_ref.key() not in sources):
        return
    basis = read(rule.decision_basis_ref, GovChangeBasisView)
    draft = basis.draft
    if (submission is None or basis.transition_rule_ref != rule.ref or basis.application_ref != action_input.application_ref
            or basis.content_sha256 != content_hash or draft.outcome != rule.choice or draft.prior_decision_ref != prior.ref
            or draft.case_ref != prior.case_ref or draft.submission_ref != submission.ref
            or draft.covered_scope != action_input.scope or draft.decision_basis_ref != basis.ref):
        raise TaskConflict('Government change draft substitutes its original prior decision, version or basis')
    if basis.outcome_rule_ref.key() in sources:
        bound_rule(basis.outcome_rule_ref, 'outcome')
    if basis.authority_ref.key() in sources:
        authority = read(basis.authority_ref, GovChangeAuthorityView)
        if (authority.organization_id != organization_id or authority.actor_id != context.actor_id
                or authority.function_ref != context.function_ref or authority.prior_decision_ref != prior.ref
                or authority.permit_ref != action_input.permit_ref or authority.decision_basis_ref != basis.ref):
            raise TaskConflict('Government change authority substitutes its original signer or basis')
    effect = None
    if draft.effect_rule_ref.key() in sources:
        effect = read(draft.effect_rule_ref, GovChangeEffectView)
        if effect.decision_basis_ref != basis.ref or effect.outcome != draft.outcome:
            raise TaskConflict('Government change effect substitutes its original basis or outcome')
    command = None
    if basis.command_ref.key() in sources:
        command = read(basis.command_ref, GovDecisionCommandView)
        if (command.case_ref != prior.case_ref or command.submission_ref != submission.ref
                or command.decision_basis_ref != basis.ref or command.operation_id != context.operation_id):
            raise TaskConflict('Government change command substitutes its original operation or draft basis')
    for ref in prior.history_refs:
        if ref.key() not in sources:
            continue
        official = read(ref, GovTransitionDecisionView, linked=True)
        if official.case_ref != prior.case_ref:
            raise TaskConflict('Government change history substitutes its original case')
        if command is not None and official.business_key == command.business_key:
            if (official.command_ref != command.ref or official.draft_sha256 != command.draft_sha256
                    or official.submission_ref != submission.ref or official.signer_actor_id != context.actor_id
                    or official.signer_function_ref != context.function_ref):
                raise TaskConflict('Government recovered change substitutes its original command, draft or signer')
            if effect is not None:
                notifications(official, effect)
    for ref in draft.assessment_refs:
        if ref.key() not in sources:
            continue
        assessment = read(ref, GovDecisionAssessmentView)
        if (assessment.case_ref != prior.case_ref or assessment.submission_ref != submission.ref
                or assessment.content_sha256 != content_hash):
            raise TaskConflict('Government change assessment substitutes its original current submission')
        for result_ref in assessment.check_result_refs:
            if result_ref.key() in sources:
                finding = read(result_ref, GovDecisionFindingView)
                if (finding.assessment_ref != assessment.ref or finding.submission_ref != submission.ref
                        or finding.content_sha256 != content_hash):
                    raise TaskConflict('Government change finding substitutes its original assessment or version')
    if basis.procedure_ref.key() in sources:
        procedure = read(basis.procedure_ref, GovChangeProcedureView)
        if procedure.decision_basis_ref != basis.ref:
            raise TaskConflict('Government change procedure substitutes its original independent basis')
        if procedure.completion_ref.key() in sources:
            completion = read(procedure.completion_ref, GovProcedureCompletionView)
            if (completion.procedure_ref != procedure.ref or completion.case_ref != prior.case_ref
                    or completion.submission_ref != submission.ref or completion.content_sha256 != content_hash):
                raise TaskConflict('Government change completion substitutes its original procedure or version')
            for ref in completion.verification_refs:
                if ref.key() in sources:
                    verification = read(ref, GovProcedureVerificationView)
                    if (verification.case_ref != prior.case_ref or verification.submission_ref != submission.ref
                            or verification.content_sha256 != content_hash):
                        raise TaskConflict('Government change verification substitutes its original current case or version')
                    if verification.requirement_ref.key() in sources:
                        requirement = read(verification.requirement_ref, GovProcedureRequirementView)
                        if requirement.procedure_ref != procedure.ref:
                            raise TaskConflict('Government change verification substitutes its original procedure requirement')
    for ref in basis.condition_basis_refs:
        if ref.key() in sources:
            condition_basis = read(ref, GovDecisionConditionBasisView)
            if condition_basis.decision_basis_ref != basis.ref:
                raise TaskConflict('Government change condition basis substitutes its original draft')
    for ref in basis.removed_condition_rule_refs:
        if ref.key() in sources:
            bound_rule(ref, 'condition')
    bindings = [draft.expiry_rule_ref] if draft.expiry_rule_ref is not None else []
    for condition in draft.conditions:
        if condition.condition_rule_ref.key() in sources:
            bound_rule(condition.condition_rule_ref, 'condition')
        bindings.extend(condition.affected_action_refs)
        bindings.extend(condition.required_evidence_refs)
        if condition.due_rule_ref is not None:
            bindings.append(condition.due_rule_ref)
    for ref in set(bindings):
        if ref.key() in sources:
            binding = read(ref, GovDecisionBindingView)
            if binding.decision_basis_ref != basis.ref:
                raise TaskConflict('Government change requirement substitutes its original authorized basis')
    # Policy applicability, actual expiry, full draft hashing, command lookup,
    # independent signer rights, complete checks/procedures, condition retention
    # and actual delivery remain processor checks. Assembly changes no prior effect.
