"""BANK-A02 intake checks against immutable application and product versions."""
from decimal import Decimal

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.bank_objects import (
    BorrowerOrganizationView, FinanceApplicationView, FinanceIntakeRequirementView,
    FinanceProductProfileView, FundingPurposeView,
)
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class IntakeGap(Exception):
    def __init__(self, result):
        self.result = result


def _needs(field, refs=()):
    raise IntakeGap({"kind": "needs_information", "missing_fields": [field], "requested_refs": list(refs)})


def _unsupported(identity):
    raise IntakeGap({"kind": "unsupported", "capability_ref": {
        "kind": "Capability", "id": identity, "version": "1"}})


def _known(state, field):
    if isinstance(state, Known):
        return state.value
    if state.state == "not_supported":
        raise IntakeGap({"kind": "unsupported", "capability_ref": state.capability_ref})
    if state.state == "not_applicable":
        _unsupported(f"bank-intake-applicability:{field}")
    _needs(field, state.missing_refs)


def intake_application(context, action_input, reading):
    def evidence(ref, point=None):
        value = reading.resolve(ref)
        if not isinstance(value, EvidenceRecord):
            _unsupported("bank-intake-evidence-schema")
        if value.effective_window is not None:
            if value.effective_window.start.clock_ref != context.business_time.clock_ref:
                _unsupported("bank-intake-clock-alignment")
            if not value.effective_window.contains(point or context.business_time):
                _needs("applicable_intake_evidence", [ref])

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"bank-intake-projection:{ref.kind}")
        for source in value.evidence_refs:
            evidence(source)
        return value

    def current(window):
        if window.start.clock_ref != context.business_time.clock_ref:
            _unsupported("bank-intake-clock-alignment")
        return window.contains(context.business_time)

    def completed(choice, note, **extra):
        return {"kind": "completed", "payload": {"choice": choice,
                "application_ref": action_input.application_ref, "finding_refs": [], "note": note, **extra}}

    def eligible_product(product, application, borrower, purpose):
        if product.lender_id != reading.organization_id or not current(product.effective_window):
            return False
        checks = (
            (borrower.registration_region_id, product.allowed_registration_region_ids, "registration_region"),
            (purpose.project_region_id, product.allowed_project_region_ids, "project_region"),
            (purpose.purpose_code, product.allowed_purpose_codes, "funding_purpose"),
            (purpose.stage, product.allowed_stages, "application_stage"),
        )
        for actual, allowed, field in checks:
            if _known(actual, field) not in _known(allowed, f"product:{field}"):
                return False
        operating = _known(borrower.operating_region_ids, "borrower_operating_regions")
        if not operating:
            _needs("borrower_operating_regions")
        if not set(operating) <= set(_known(product.allowed_operating_region_ids, "product:operating_regions")):
            return False
        if application.requested.currency not in _known(product.allowed_currencies, "product:currencies"):
            return False
        minimum = _known(product.minimum_request, "product:minimum_request")
        maximum = _known(product.maximum_request, "product:maximum_request")
        if minimum.currency != application.requested.currency or maximum.currency != application.requested.currency:
            _unsupported("bank-intake-currency-conversion")
        evidence(minimum.basis_ref)
        evidence(maximum.basis_ref)
        if not Decimal(minimum.value) <= Decimal(application.requested.value) <= Decimal(maximum.value):
            return False
        submissions = {item.disclosure_code: item.evidence_ref for item in application.disclosures}
        for code in _known(product.required_disclosure_codes, "product:required_disclosures"):
            if code not in submissions:
                _needs(f"disclosure:{code}")
            evidence(submissions[code])
        for ref in product.required_condition_refs:
            condition = read(ref, FinanceIntakeRequirementView)
            if condition.product_ref != product.ref or condition.scope_ref != application.scope_ref:
                raise ValueError("Intake condition differs from the selected product version or application scope")
        return True

    try:
        application = read(action_input.application_ref, FinanceApplicationView)
        if (action_input.borrower_id != application.borrower_id
                or action_input.purpose_ref != application.purpose_ref
                or action_input.applicant_authority_ref != application.applicant_authority_ref
                or action_input.requested.currency != application.requested.currency
                or action_input.requested.basis_ref != application.requested.basis_ref
                or Decimal(action_input.requested.value) != Decimal(application.requested.value)
                or len(action_input.product_candidates) != len(application.product_candidates)
                or len(action_input.disclosure_refs) != len(application.disclosure_refs)
                or {ref.key() for ref in action_input.product_candidates} != {ref.key() for ref in application.product_candidates}
                or {ref.key() for ref in action_input.disclosure_refs} != {ref.key() for ref in application.disclosure_refs}):
            raise ValueError("Intake input differs from the exact submitted application version")
        if application.lender_id != reading.organization_id:
            raise ValueError("Application is addressed to another lender")
        if context.scope.kind == "organization":
            if context.scope.ref.id != reading.organization_id:
                raise ValueError("Intake organization scope differs from the current lender")
        elif not scope_covers(context.scope, application.scope_ref):
            raise ValueError("Application scope exceeds the intake scope")
        if application.submitted_at.clock_ref != context.business_time.clock_ref:
            _unsupported("bank-intake-clock-alignment")
        if application.status == "draft" or application.submitted_at.offset > context.business_time.offset:
            _needs("submitted_application_at_current_read_point", [application.ref])
        if application.status == "withdrawn":
            return completed("decline", "The exact application version has been withdrawn")
        evidence(application.requested.basis_ref)
        for ref in application.disclosure_refs:
            evidence(ref)
        borrower = read(application.borrower_ref, BorrowerOrganizationView)
        purpose = read(application.purpose_ref, FundingPurposeView)
        if purpose.borrower_ref != borrower.ref or purpose.scope_ref != application.scope_ref:
            raise ValueError("Funding purpose differs from the submitted borrower or scope")
        for label, value in (("borrower", borrower), ("purpose", purpose)):
            if not current(value.effective_window):
                _needs(f"current_{label}", [value.ref])
        if not _known(borrower.legal_standing, "borrower_legal_standing"):
            return completed("decline", "The supplied legal-standing evidence rules out the borrower")
        authority = reading.resolve(application.applicant_authority_ref)
        if not isinstance(authority, Authorization):
            _unsupported("bank-intake-applicant-authority-schema")
        assignment = reading.resolve(application.applicant_function_ref)
        if not isinstance(assignment, RoleAssignment):
            _unsupported("bank-intake-applicant-function-schema")
        for ref in [*authority.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                evidence(ref, application.submitted_at)
            else:
                reading.resolve(ref)
        if authority.validity.start.clock_ref != context.business_time.clock_ref:
            _unsupported("bank-intake-clock-alignment")
        if (authority.organization_id != application.borrower_id
                or authority.actor_id != application.applicant_actor_id
                or authority.function_ref != application.applicant_function_ref
                or assignment.function_ref != application.applicant_function_ref
                or assignment.role != {'OWN-A05': 'Owner', 'CONTRACTOR-A10': 'Contractor',
                    'SUPPLIER-A10': 'Supplier'}[application.originating_action_id]
                or application.originating_action_id not in authority.action_ids
                or not authority.validity.contains(application.submitted_at)
                or not any(scope_covers(scope, application.scope_ref) for scope in authority.scopes)):
            return completed("decline", "The submitted applicant lacks applicable borrower authority")
        if Decimal(application.requested.value) <= 0:
            return completed("decline", "The submitted request is not positive")
        if not application.product_candidates:
            _needs("product_candidates")
        eligible, gaps = [], []
        for ref in application.product_candidates:
            try:
                product = read(ref, FinanceProductProfileView)
                if eligible_product(product, application, borrower, purpose):
                    eligible.append(product)
            except IntakeGap as gap:
                gaps.append(gap.result)
        if not eligible:
            missing = [gap for gap in gaps if gap["kind"] == "needs_information"]
            if missing:
                fields = list(dict.fromkeys(field for gap in missing for field in gap["missing_fields"]))
                requested = {ref.key(): ref for gap in missing for ref in gap["requested_refs"]}
                return {"kind": "needs_information", "missing_fields": fields, "requested_refs": list(requested.values())}
            if gaps:
                return gaps[0]
            return completed("decline", "No supplied product version applies to the borrower, location, purpose, stage and amount")
        if len(eligible) == 1:
            selected = eligible[0]
        else:
            priorities = [(_known(product.selection_priority, "product_selection_priority"), product) for product in eligible]
            first = min(priority for priority, _ in priorities)
            preferred = [product for priority, product in priorities if priority == first]
            if len(preferred) != 1:
                _needs("unambiguous_product_selection", [product.ref for product in preferred])
            selected = preferred[0]
        return completed("accept_for_review", "Applicable borrower authority, disclosed facts and product conditions support review only",
                         product_ref=selected.ref, required_condition_refs=selected.required_condition_refs)
    except IntakeGap as gap:
        return gap.result
