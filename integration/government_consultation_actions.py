"""Freeze original Government A05 disclosure, channels and received opinions."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_objects import (
    GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.government_review_objects import GovReviewSubmissionView
from src.actions.contracts.government_consultation_objects import (
    GovConsultationCaseView, GovConsultationRuleView, GovConsultationApplicabilityView,
    GovDisclosurePackageView, GovDisclosureAuthorityView, GovConsultationRecipientView,
    GovConsultationClockView, GovConsultationView, GovConsultationDeliveryView,
    GovConsultationResponseView, GovParticipationView, GovConsultationTaskView,
    GovConsultationResultView, GovConsultationQuestionView, GovConsultationProcedureView,
    government_consultation_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentConsultation(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A05'


class GovernmentConsultationActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve original disclosure and opinion provenance for the processor.

    Delivery, opinions, participation and independent disclosure permission stay
    distinct. Assembly neither sends a package nor registers a consultation.
    """
    ACTION_ID = 'GOV-A05'
    SOURCE_SCHEMAS = staticmethod(government_consultation_schemas)

    def build(self, context, *, scope, case_ref, consultation_rule_ref, disclosure_package_ref,
            recipient_refs, prior_consultation_ref, response_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'case_ref': case_ref, 'consultation_rule_ref': consultation_rule_ref,
            'disclosure_package_ref': disclosure_package_ref, 'recipient_refs': recipient_refs,
            'prior_consultation_ref': prior_consultation_ref, 'response_refs': response_refs},
            prepared_type=PreparedGovernmentConsultation,
            validate_sources=validate_government_consultation_sources)


def validate_government_consultation_sources(action_input, *, context, organization_id, sources):
    """Bind original case/package/channel identities without inferring replies."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government consultation lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government consultation source leaves its original requested scope')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government consultation input leaves its original invocation scope')
    unique_refs(action_input.recipient_refs)
    unique_refs(action_input.response_refs)
    case = read(action_input.case_ref, GovConsultationCaseView)
    rule = read(action_input.consultation_rule_ref, GovConsultationRuleView)
    package = read(action_input.disclosure_package_ref, GovDisclosurePackageView)
    if (case.organization_id != organization_id or rule.organization_id != organization_id
            or rule.case_ref != case.ref or rule.procedure_ref != case.procedure_ref
            or package.case_ref != case.ref):
        raise TaskConflict('Government consultation substitutes its original agency, case or procedure')
    if case.procedure_ref.key() in sources:
        procedure = read(case.procedure_ref, GovConsultationProcedureView)
        if procedure.case_ref != case.ref or procedure.rule_ref != rule.ref:
            raise TaskConflict('Government consultation procedure substitutes its original case or rule')
    if case.jurisdiction_ref.key() in sources:
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView)
        if jurisdiction.organization_id != organization_id:
            raise TaskConflict('Government consultation borrows another agency jurisdiction')
    if case.matter_ref.key() in sources:
        read(case.matter_ref, GovMatterView)
    if case.current_submission_ref.key() in sources:
        submission = read(case.current_submission_ref, GovReviewSubmissionView)
        if package.submission_ref != submission.ref or package.submission_sha256 != submission.content_sha256:
            raise TaskConflict('Government disclosure package substitutes its original final submission content')
    if rule.disclosure_authority_ref.key() in sources:
        disclosure = read(rule.disclosure_authority_ref, GovDisclosureAuthorityView)
        if (disclosure.organization_id != organization_id or disclosure.actor_id != context.actor_id
                or disclosure.function_ref != context.function_ref or disclosure.case_ref != case.ref
                or disclosure.rule_ref != rule.ref or disclosure.package_ref != package.ref
                or disclosure.content_sha256 != package.content_sha256):
            raise TaskConflict('Government disclosure authority substitutes its original actor, case or package')
    for ref in package.disclosed_evidence_refs:
        if ref.key() in sources:
            read(ref, EvidenceRecord)
    if rule.applicability_basis_ref.key() in sources:
        applicability = read(rule.applicability_basis_ref, GovConsultationApplicabilityView)
        if applicability.case_ref != case.ref or applicability.rule_ref != rule.ref:
            raise TaskConflict('Government consultation applicability substitutes its original case or rule')
    if rule.clock_rule_ref.key() in sources:
        clock_rule = read(rule.clock_rule_ref, GovConsultationClockView)
        if (clock_rule.case_ref != case.ref or clock_rule.rule_ref != rule.ref
                or clock_rule.procedure_ref != case.procedure_ref):
            raise TaskConflict('Government consultation clock substitutes its original procedure')

    recipients = {}
    for ref in action_input.recipient_refs:
        recipient = read(ref, GovConsultationRecipientView)
        if recipient.case_ref != case.ref or recipient.procedure_ref != case.procedure_ref:
            raise TaskConflict('Government consultation channel substitutes its original case or procedure')
        recipients[ref.key()] = recipient
    for ref in case.consultation_refs:
        if ref.key() in sources:
            historical = read(ref, GovConsultationView)
            if historical.case_ref != case.ref:
                raise TaskConflict('Government consultation history substitutes its original case')
    consultation = None
    continuation = rule.choice in {'register_response', 'analyze'}
    if action_input.prior_consultation_ref is not None:
        consultation = read(action_input.prior_consultation_ref, GovConsultationView)
        if consultation.organization_id != organization_id or consultation.case_ref != case.ref:
            raise TaskConflict('Government prior consultation substitutes its original agency or case')
        if continuation and (consultation.rule_ref != rule.ref or consultation.procedure_ref != case.procedure_ref
                or consultation.disclosure_package_ref != package.ref
                or consultation.content_sha256 != package.content_sha256
                or consultation.clock_rule_ref != rule.clock_rule_ref
                or set(consultation.recipient_refs) != set(action_input.recipient_refs)):
            raise TaskConflict('Government continued consultation substitutes its original package or channels')
        # Initiation may query an existing consultation before creating anything;
        # its historical package is not rewritten to match a proposed new one.

    question_refs = list(rule.question_refs)
    for ref in action_input.response_refs:
        response = read(ref, GovConsultationResponseView)
        if consultation is not None and continuation:
            recipient = recipients.get(response.recipient_ref.key())
            if (recipient is None or response.consultation_ref != consultation.ref
                    or response.package_ref != package.ref or response.content_sha256 != package.content_sha256
                    or response.author_actor_id != recipient.representative_actor_id
                    or response.author_organization_id != recipient.organization_id
                    or response.author_function_ref != recipient.representative_function_ref
                    or response.author_action_id != recipient.response_action_id):
                raise TaskConflict('Government consultation response substitutes its original channel, content or author')
            question_refs.extend(response.issue_question_refs)
    if consultation is not None and continuation:
        for ref in consultation.delivery_refs:
            if ref.key() in sources:
                delivery = read(ref, GovConsultationDeliveryView)
                if (delivery.consultation_ref != consultation.ref or delivery.recipient_ref.key() not in recipients
                        or delivery.package_ref != package.ref or delivery.content_sha256 != package.content_sha256):
                    raise TaskConflict('Government delivery receipt substitutes its original consultation or content')
        for ref in consultation.participation_refs:
            if ref.key() in sources:
                participation = read(ref, GovParticipationView)
                if (participation.consultation_ref != consultation.ref
                        or participation.recipient_ref.key() not in recipients or participation.rule_ref != rule.ref):
                    raise TaskConflict('Government participation verification substitutes its original consultation or rule')
    if rule.analysis_task_ref is not None and rule.analysis_task_ref.key() in sources:
        task = read(rule.analysis_task_ref, GovConsultationTaskView)
        if (task.organization_id != organization_id or task.case_ref != case.ref
                or consultation is not None and continuation and task.consultation_ref != consultation.ref):
            raise TaskConflict('Government consultation analysis task substitutes its original agency or case')
    if rule.analysis_result_ref is not None and rule.analysis_result_ref.key() in sources:
        result = read(rule.analysis_result_ref, GovConsultationResultView)
        if (result.rule_ref != rule.ref or result.task_ref != rule.analysis_task_ref
                or consultation is not None and continuation and result.consultation_ref != consultation.ref):
            raise TaskConflict('Government consultation analysis result substitutes its original task or rule')

    for ref in set(question_refs):
        if ref.key() not in sources:
            continue
        row = read(ref, GovConsultationQuestionView)
        question = row.question
        if (row.case_ref != case.ref or question.scope != row.scope
                or question.requirement_ref != rule.ref or row.ref not in question.target_refs):
            raise TaskConflict('Government consultation question substitutes its original case, scope or rule')
        for target_ref in question.target_refs:
            if target_ref.key() in sources:
                target = read(target_ref, GovConsultationQuestionView)
                if target.case_ref != case.ref or target.question != question:
                    raise TaskConflict('Government consultation targets substitute their original question')
        for recipient_ref in question.recipient_refs:
            if recipient_ref.key() in sources:
                read(recipient_ref, GovRecipientView)
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != rule.ref or response.scope != question.scope:
                raise TaskConflict('Government consultation response requirement substitutes its original rule or scope')
    if rule.referral_recipient_ref is not None and rule.referral_recipient_ref.key() in sources:
        read(rule.referral_recipient_ref, GovRecipientView)
    # Original processor owns applicability, disclosure permission/content limits,
    # recipient completeness, actual delivery/opinion distinction, event dedup,
    # timing, public participation and saved analysis recomputation. No veto or
    # unanimity, substantive compliance, signed decision or permit is inferred.
