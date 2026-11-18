"""GOV-A02 checks only visible intake facts against sourced procedure rules."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_objects import (
    GovAgencyAuthorityView, GovCaseView, GovEvidenceTargetView, GovJurisdictionView, GovMatterView,
    GovProcedureView, GovRecipientView, GovRequirementView, GovResponseRequirementView,
    GovRuleView, GovSubmissionView,
)
from src.organization.registry import scope_covers


class IntakeGap(Exception):
    def __init__(self, result):
        self.result = result


def _needs(field, refs=()):
    raise IntakeGap({"kind": "needs_information", "missing_fields": [field], "requested_refs": list(refs)})


def _unsupported(code):
    raise IntakeGap({"kind": "unsupported", "capability_ref": {
        "kind": "Capability", "id": code, "version": "1"}})


def _known(state, field):
    if isinstance(state, Known):
        return state.value
    if state.state == "not_supported":
        raise IntakeGap({"kind": "unsupported", "capability_ref": state.capability_ref})
    if state.state == "not_applicable":
        _unsupported(f"government-intake-applicability:{field}")
    _needs(field, state.missing_refs)


def intake_submission(context, action_input, reading):
    def current(window, point=None):
        if window.start.clock_ref != context.business_time.clock_ref:
            _unsupported("government-intake-clock-alignment")
        return window.contains(point or context.business_time)

    def evidence(ref, point=None):
        record = reading.resolve(ref)
        if not isinstance(record, EvidenceRecord):
            _unsupported("government-intake-evidence-schema")
        if record.effective_window is not None and not current(record.effective_window, point):
            _needs("current_intake_evidence", [ref])

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"government-intake-projection:{ref.kind}")
        for source in value.evidence_refs:
            evidence(source)
        return value

    def completed(choice, **fields):
        return {"kind": "completed", "payload": {"choice": choice, "scope": action_input.scope,
            "note": "Intake output only; formal case registration and receipt require the authorized macro service",
            **fields}}

    def rule(ref, purpose, recipient=None):
        value = read(ref, GovRuleView)
        if (value.organization_id != reading.organization_id or value.matter_ref != action_input.matter_ref
                or value.procedure_ref != action_input.procedure_ref
                or not scope_covers(value.scope, action_input.scope) or value.purpose != purpose
                or value.recipient_id != recipient):
            raise ValueError("Intake rule differs from the authority, matter, procedure, scope or purpose")
        if not current(value.effective_window):
            _needs("current_intake_rule", [ref])
        return value

    try:
        submission = read(action_input.submission_ref, GovSubmissionView)
        for field in ("scope", "applicant_id", "agency_authority_ref", "matter_ref", "jurisdiction_ref",
                      "procedure_ref", "prior_case_ref"):
            if getattr(submission, field) != getattr(action_input, field):
                raise ValueError("Intake input differs from the exact submitted version")
        if submission.recipient_organization_id != reading.organization_id:
            raise ValueError("Submission is addressed to another government organization")
        if submission.submitted_at.clock_ref != context.business_time.clock_ref:
            _unsupported("government-intake-clock-alignment")
        if submission.submitted_at.offset > context.business_time.offset or submission.receipt_status == "not_submitted":
            _needs("submitted_application", [submission.ref])
        if submission.receipt_status in {"unknown", "failed"}:
            return {"kind": "technical_error", "error": {"kind": "unrecorded", "correlation_id": context.operation_id,
                    "code": f"receipt_{submission.receipt_status}"}, "retryability": "unknown"}
        if action_input.prior_case_ref is not None:
            case = read(action_input.prior_case_ref, GovCaseView)
            if (case.organization_id != reading.organization_id or case.applicant_id != submission.applicant_id
                    or case.scope != submission.scope or case.matter_ref != submission.matter_ref
                    or case.procedure_ref != submission.procedure_ref
                    or submission.ref not in [case.current_submission_ref, *case.linked_submission_refs]):
                raise ValueError("Prior case does not preserve the submitted identity and version chain")
        matter = read(action_input.matter_ref, GovMatterView)
        jurisdiction = read(action_input.jurisdiction_ref, GovJurisdictionView)
        procedure = read(action_input.procedure_ref, GovProcedureView)
        if (matter.scope != submission.scope or jurisdiction.organization_id != reading.organization_id
                or procedure.matter_ref != matter.ref or procedure.jurisdiction_ref != jurisdiction.ref):
            raise ValueError("Matter, jurisdiction or procedure differs from the submitted intake")
        for name, projection in (("jurisdiction", jurisdiction), ("procedure", procedure)):
            if not current(projection.effective_window):
                _needs(f"current_{name}", [projection.ref])
        region = _known(submission.project_region_id, "project_region")
        if _known(matter.project_region_id, "matter_project_region") != region:
            raise ValueError("Matter project region differs from the submitted version")
        covered = (matter.matter_code in _known(jurisdiction.covered_matter_codes, "covered_matters")
                   and region in _known(jurisdiction.covered_project_region_ids, "covered_regions")
                   and any(scope_covers(scope, submission.scope) for scope in jurisdiction.covered_scopes))
        if not covered:
            if jurisdiction.referral is not None:
                referral = jurisdiction.referral
                if referral.recipient_id == context.actor_id:
                    raise ValueError("Referral cannot redirect the submission to the same actor")
                rule(referral.basis_ref, "refer", referral.recipient_id)
                return completed("refer", recipient_id=referral.recipient_id, basis_ref=referral.basis_ref)
            if jurisdiction.outside_coverage_rule_ref is not None:
                rule(jurisdiction.outside_coverage_rule_ref, "decline_outside_coverage")
                return completed("decline_processing", reason="The sourced jurisdiction does not cover this matter and project scope",
                                 basis_refs=[jurisdiction.outside_coverage_rule_ref])
            _needs("lawful_outside_jurisdiction_route", [jurisdiction.ref])
        if submission.submitter_id != submission.applicant_id or submission.agency_authority_ref is not None:
            if submission.agency_authority_ref is None:
                _needs("agency_authority_ref")
            authority = read(submission.agency_authority_ref, GovAgencyAuthorityView)
            if (authority.applicant_id != submission.applicant_id or authority.submitter_id != submission.submitter_id
                    or authority.matter_ref != matter.ref or authority.procedure_ref != procedure.ref
                    or not scope_covers(authority.scope, submission.scope)):
                raise ValueError("Agency authority differs from the exact applicant, submitter or matter")
            if (not current(authority.effective_window, submission.submitted_at)
                    or not _known(authority.permitted, "agency_permission")):
                _needs("valid_applicant_agency_authority", [authority.ref])
        if submission.status == "withdrawn":
            if procedure.withdrawal_rule_ref is None:
                _needs("withdrawal_processing_rule", [procedure.ref])
            rule(procedure.withdrawal_rule_ref, "withdrawal")
            return completed("decline_processing", reason="The received submission was withdrawn under the sourced procedure",
                             basis_refs=[procedure.withdrawal_rule_ref])
        if _known(procedure.intake_mode, "intake_mode") == "receipt_only":
            return completed("acknowledge", submission_ref=submission.ref)
        materials = {item.requirement_ref.key(): item for item in submission.materials}
        checked, missing, questions = [], [], []
        requirements = [read(ref, GovRequirementView) for ref in procedure.requirement_refs]
        if not {"signature", "applicant_eligibility"} <= {item.check_kind for item in requirements}:
            _unsupported("government-intake-signature-and-eligibility-checklist")
        for requirement in requirements:
            ref = requirement.ref
            if requirement.procedure_ref != procedure.ref or requirement.scope != submission.scope:
                raise ValueError("Intake requirement differs from the procedure version or scope")
            question = requirement.correction_question
            if question.scope != submission.scope:
                raise ValueError("Correction question differs from the submitted scope")
            rule(question.requirement_ref, "correction")
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref or response.scope != submission.scope:
                raise ValueError("Correction response requirement differs from the rule or scope")
            if not question.target_refs or not question.recipient_refs:
                raise ValueError("Correction question requires an explicit target and recipient")
            for target_ref in question.target_refs:
                target = read(target_ref, GovEvidenceTargetView)
                if target.submission_ref != submission.ref or target.scope != submission.scope:
                    raise ValueError("Correction target differs from the submitted version")
            for recipient_ref in question.recipient_refs:
                recipient = read(recipient_ref, GovRecipientView)
                if recipient.actor_id not in {submission.applicant_id, submission.submitter_id} or recipient.scope != submission.scope:
                    raise ValueError("Correction recipient differs from the applicant or authorized submitter")
            for source in question.evidence_refs:
                evidence(source)
            checked.append(ref)
            if requirement.check_kind == "signature":
                present = _known(submission.signed, "submission_signature")
            elif requirement.check_kind == "applicant_eligibility":
                present = _known(submission.applicant_eligible, "applicant_eligibility")
                if not present and procedure.ineligible_decline_rule_ref is not None:
                    rule(procedure.ineligible_decline_rule_ref, "decline_ineligible")
                    return completed("decline_processing", reason="The sourced applicant eligibility condition is not met",
                                     basis_refs=[procedure.ineligible_decline_rule_ref])
            else:
                material = materials.get(ref.key())
                present = material is not None
                if present:
                    evidence(material.evidence_ref)
            if not present:
                missing.append(ref)
                questions.append(question.model_dump(mode="python"))
        check = {"submission_ref": submission.ref, "procedure_ref": procedure.ref,
                 "checked_requirement_refs": checked, "missing_requirement_refs": missing,
                 "unresolved_questions": questions, "scope": submission.scope}
        if missing:
            return completed("request_correction", check=check, questions=questions)
        return completed("accept_for_processing", check=check)
    except IntakeGap as gap:
        return gap.result
