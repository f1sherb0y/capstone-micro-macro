"""Assemble original Government A02 submissions and sourced intake procedures."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_objects import (
    GovSubmissionView, GovMatterView, GovJurisdictionView, GovProcedureView,
    GovAgencyAuthorityView, GovCaseView, GovRequirementView, GovRuleView,
    GovEvidenceTargetView, GovRecipientView, GovResponseRequirementView,
    government_intake_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentIntake(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A02'


class GovernmentIntakeActionAssembler(GovernmentAdviceActionAssembler):
    """Freeze original submission sources under the application's current guard.

    Receipt status, jurisdiction, agency authority and procedural completeness
    remain original processor decisions. Assembly creates no submission receipt,
    registered case, technical approval or permission to proceed.
    """
    ACTION_ID = 'GOV-A02'
    SOURCE_SCHEMAS = staticmethod(government_intake_schemas)

    def build(self, context, *, scope, submission_ref, applicant_id, agency_authority_ref,
            matter_ref, jurisdiction_ref, procedure_ref, prior_case_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'submission_ref': submission_ref, 'applicant_id': applicant_id,
            'agency_authority_ref': agency_authority_ref, 'matter_ref': matter_ref,
            'jurisdiction_ref': jurisdiction_ref, 'procedure_ref': procedure_ref,
            'prior_case_ref': prior_case_ref}, prepared_type=PreparedGovernmentIntake,
            validate_sources=validate_government_intake_sources)

    def build_from_architect_deliverable(self, context, *, architect_decision, publication_receipt,
            receipt_ref, validate_reception, **intake_inputs):
        """Bind actually received A07 material without creating or approving it."""
        from integration.architect_government_intake_handoff import validate_received_architect_deliverable

        prepared = self.build(context, **intake_inputs)
        validate_received_architect_deliverable(architect_decision, prepared=prepared,
            publication_receipt=publication_receipt, receipt_ref=receipt_ref,
            validate_reception=validate_reception)
        return prepared


def validate_government_intake_sources(action_input, *, context, organization_id, sources):
    """Check original submitted versions without accepting or registering a case."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government intake lacks its exact original concrete source')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Government intake changes its original invocation scope')
    submission = read(action_input.submission_ref, GovSubmissionView)
    if (submission.recipient_organization_id != organization_id
            or any(getattr(submission, field) != getattr(action_input, field)
                for field in ('scope', 'applicant_id', 'agency_authority_ref', 'matter_ref',
                    'jurisdiction_ref', 'procedure_ref', 'prior_case_ref'))):
        raise TaskConflict('Government intake substitutes its original recipient, applicant or submitted versions')
    matter = read(action_input.matter_ref, GovMatterView)
    jurisdiction = read(action_input.jurisdiction_ref, GovJurisdictionView)
    procedure = read(action_input.procedure_ref, GovProcedureView)
    if (matter.scope != submission.scope or jurisdiction.organization_id != organization_id
            or procedure.matter_ref != matter.ref or procedure.jurisdiction_ref != jurisdiction.ref):
        raise TaskConflict('Government intake substitutes its original matter, jurisdiction or procedure')
    if action_input.agency_authority_ref is not None:
        authority = read(action_input.agency_authority_ref, GovAgencyAuthorityView)
        if (authority.applicant_id != submission.applicant_id or authority.submitter_id != submission.submitter_id
                or authority.matter_ref != matter.ref or authority.procedure_ref != procedure.ref
                or not scope_covers(authority.scope, submission.scope)):
            raise TaskConflict('Government agency authority substitutes its original applicant, submitter or scope')
    if action_input.prior_case_ref is not None:
        case = read(action_input.prior_case_ref, GovCaseView)
        if (case.organization_id != organization_id or case.applicant_id != submission.applicant_id
                or case.scope != submission.scope or case.matter_ref != matter.ref
                or case.procedure_ref != procedure.ref
                or submission.ref not in [case.current_submission_ref, *case.linked_submission_refs]):
            raise TaskConflict('Government prior case substitutes its original submitted identity or version chain')
    rule_refs = [ref for ref in (procedure.ineligible_decline_rule_ref, procedure.withdrawal_rule_ref,
        jurisdiction.outside_coverage_rule_ref) if ref is not None]
    if jurisdiction.referral is not None:
        rule_refs.append(jurisdiction.referral.basis_ref)
    for ref in procedure.requirement_refs:
        if ref.key() not in sources:
            continue
        requirement = read(ref, GovRequirementView)
        if requirement.procedure_ref != procedure.ref or requirement.scope != submission.scope:
            raise TaskConflict('Government intake requirement substitutes its original procedure or scope')
        question = requirement.correction_question
        if question.scope != submission.scope:
            raise TaskConflict('Government correction question substitutes its original submission scope')
        unique_refs(question.target_refs)
        unique_refs(question.recipient_refs)
        rule_refs.append(question.requirement_ref)
        for target_ref in question.target_refs:
            if target_ref.key() in sources:
                target = read(target_ref, GovEvidenceTargetView)
                if target.submission_ref != submission.ref or target.scope != submission.scope:
                    raise TaskConflict('Government correction target substitutes its original submission')
        for recipient_ref in question.recipient_refs:
            if recipient_ref.key() in sources:
                recipient = read(recipient_ref, GovRecipientView)
                if recipient.actor_id not in {submission.applicant_id, submission.submitter_id} or recipient.scope != submission.scope:
                    raise TaskConflict('Government correction recipient substitutes its original applicant or submitter')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref or response.scope != submission.scope:
                raise TaskConflict('Government correction response substitutes its original rule or scope')
    for ref in set(rule_refs):
        if ref.key() not in sources:
            continue
        rule = read(ref, GovRuleView)
        if (rule.organization_id != organization_id or rule.matter_ref != matter.ref
                or rule.procedure_ref != procedure.ref or not scope_covers(rule.scope, submission.scope)):
            raise TaskConflict('Government intake rule substitutes its original organization, matter or procedure')
    for material in submission.materials:
        if material.evidence_ref.key() in sources:
            read(material.evidence_ref, EvidenceRecord)
    # Received/failed/unknown status, project-region jurisdiction, applicability,
    # independent agency permission and each procedural branch stay in the processor.
