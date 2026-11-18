"""Authorized intake projections, without financing or payment state ownership."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    EvidenceRef, Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow,
    ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas
from src.methods.models import Digest


class SourcedBankProjection(StrictRecord):
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class DisclosureSubmission(StrictRecord):
    disclosure_code: TextId
    evidence_ref: EvidenceRef


class FinanceApplicationView(SourcedBankProjection):
    ref: ref_type("FinanceApplication")
    borrower_id: TextId
    borrower_ref: ref_type("Organization")
    lender_id: TextId
    scope_ref: ScopeRef
    requested: Money
    purpose_ref: ref_type("FundingPurpose")
    product_candidates: list[ref_type("FinanceProductProfile")]
    disclosure_refs: list[EvidenceRef]
    disclosures: list[DisclosureSubmission]
    applicant_authority_ref: ref_type("Authorization")
    applicant_actor_id: TextId
    applicant_function_ref: ref_type("FunctionAssignment")
    originating_action_id: Literal["OWN-A05", "CONTRACTOR-A10", "SUPPLIER-A10"]
    submitted_at: TimePoint
    status: Literal["draft", "submitted", "withdrawn"]

    @model_validator(mode="after")
    def consistent_submission(self):
        if self.borrower_ref.id != self.borrower_id:
            raise ValueError("Application borrower identity differs from its organization reference")
        for values in (self.product_candidates, self.disclosure_refs):
            if len({value.key() for value in values}) != len(values):
                raise ValueError("Application submission reference repeated")
        codes = [entry.disclosure_code for entry in self.disclosures]
        if len(set(codes)) != len(codes):
            raise ValueError("Disclosure category repeated")
        if any(entry.evidence_ref not in self.disclosure_refs for entry in self.disclosures):
            raise ValueError("Disclosure category refers outside the submitted evidence version set")
        return self


class OwnerFinanceApplicationReceiptView(SourcedBankProjection):
    """Actual original Owner application received by the bank, without credit approval."""
    ref: ref_type('OwnerFinanceApplicationReceipt')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    application_ref: ref_type('FinanceApplication')
    application_sha256: Digest
    scope: ScopeRef
    received_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class BorrowerOrganizationView(SourcedBankProjection):
    ref: ref_type("Organization")
    legal_standing: ValueState[bool]
    registration_region_id: ValueState[TextId]
    operating_region_ids: ValueState[list[TextId]]
    effective_window: TimeWindow


class FundingPurposeView(SourcedBankProjection):
    ref: ref_type("FundingPurpose")
    borrower_ref: ref_type("Organization")
    scope_ref: ScopeRef
    project_region_id: ValueState[TextId]
    purpose_code: ValueState[TextId]
    stage: ValueState[TextId]
    effective_window: TimeWindow


class FinanceProductProfileView(SourcedBankProjection):
    ref: ref_type("FinanceProductProfile")
    lender_id: TextId
    effective_window: TimeWindow
    allowed_registration_region_ids: ValueState[list[TextId]]
    allowed_operating_region_ids: ValueState[list[TextId]]
    allowed_project_region_ids: ValueState[list[TextId]]
    allowed_purpose_codes: ValueState[list[TextId]]
    allowed_stages: ValueState[list[TextId]]
    allowed_currencies: ValueState[list[TextId]]
    minimum_request: ValueState[Money]
    maximum_request: ValueState[Money]
    required_disclosure_codes: ValueState[list[TextId]]
    required_condition_refs: list[ref_type("Requirement")]
    selection_priority: ValueState[int]

    @model_validator(mode="after")
    def valid_amount_limits(self):
        for bound in (self.minimum_request, self.maximum_request):
            if bound.state == "known" and Decimal(bound.value.value) < 0:
                raise ValueError("Product intake amount limit cannot be negative")
        if (self.minimum_request.state == self.maximum_request.state == "known"
                and self.minimum_request.value.currency == self.maximum_request.value.currency
                and Decimal(self.minimum_request.value.value) > Decimal(self.maximum_request.value.value)):
            raise ValueError("Product intake minimum exceeds maximum")
        return self


class FinanceIntakeRequirementView(SourcedBankProjection):
    ref: ref_type("Requirement")
    product_ref: ref_type("FinanceProductProfile")
    scope_ref: ScopeRef
    description: TextId


def bank_intake_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ("FinanceApplication", FinanceApplicationView),
        ('OwnerFinanceApplicationReceipt', OwnerFinanceApplicationReceiptView),
        ("Organization", BorrowerOrganizationView),
        ("FundingPurpose", FundingPurposeView),
        ("FinanceProductProfile", FinanceProductProfileView),
        ("Requirement", FinanceIntakeRequirementView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
