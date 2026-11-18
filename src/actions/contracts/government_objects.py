"""Sourced Government intake projections; these are not a second case ledger."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    EvidenceRef, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.service_objects import (
    ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView, ServiceUse,
)
from src.methods.models import Digest


class GovProjection(StrictRecord):
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class GovIntakeQuestion(StrictRecord):
    scope: ScopeRef
    target_refs: list[ref_type("EvidenceTarget")]
    question: TextId
    recipient_refs: list[ref_type("RegulatoryRecipient")]
    requirement_ref: ref_type("Rule")
    response_requirement_ref: ref_type("ResponseRequirement")
    evidence_refs: list[EvidenceRef]


class GovMaterial(StrictRecord):
    requirement_ref: ref_type("InformationRequirement")
    evidence_ref: EvidenceRef


class GovSubmissionView(GovProjection):
    ref: ref_type("Submission")
    scope: ScopeRef
    applicant_id: TextId
    submitter_id: TextId
    recipient_organization_id: TextId
    agency_authority_ref: ref_type("Authority") | None
    matter_ref: ref_type("RegulatoryMatter")
    jurisdiction_ref: ref_type("Jurisdiction")
    procedure_ref: ref_type("Procedure")
    prior_case_ref: ref_type("RegulatoryCase") | None
    project_region_id: ValueState[TextId]
    applicant_registration_region_id: ValueState[TextId]
    applicant_operating_region_ids: ValueState[list[TextId]]
    submitted_at: TimePoint
    receipt_status: Literal["received", "unknown", "failed", "not_submitted"]
    status: Literal["active", "withdrawn"]
    signed: ValueState[bool]
    applicant_eligible: ValueState[bool]
    materials: list[GovMaterial]

    @model_validator(mode="after")
    def unique_materials(self):
        keys = [(item.requirement_ref.kind, item.requirement_ref.id) for item in self.materials]
        if len(keys) != len(set(keys)):
            raise ValueError("Submission repeats a requirement category")
        return self


class GovArchitectDeliverableReceiptView(GovProjection):
    """Actual received material mapping, supplied independently by the application."""
    ref: ref_type('ArchitectDeliverableReceipt')
    run_id: TextId
    scope: ScopeRef
    recipient_organization_id: TextId
    author_organization_id: TextId
    publication_recipient_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    publication_receipt_sha256: Digest
    submission_ref: ref_type('Submission')
    submission_sha256: Digest
    deliverable_ref: ref_type('Deliverable')
    deliverable_content_sha256: Digest
    requested_use: ServiceUse
    requirement_ref: ref_type('InformationRequirement')
    document_evidence_ref: EvidenceRef
    native_evidence_ref: EvidenceRef
    received_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow


class GovMatterView(GovProjection):
    ref: ref_type("RegulatoryMatter")
    scope: ScopeRef
    matter_code: TextId
    project_region_id: ValueState[TextId]


class GovReferral(StrictRecord):
    recipient_id: TextId
    basis_ref: ref_type("Rule")


class GovJurisdictionView(GovProjection):
    ref: ref_type("Jurisdiction")
    organization_id: TextId
    effective_window: TimeWindow
    covered_matter_codes: ValueState[list[TextId]]
    covered_project_region_ids: ValueState[list[TextId]]
    covered_scopes: list[ScopeRef]
    referral: GovReferral | None
    outside_coverage_rule_ref: ref_type("Rule") | None


class GovProcedureView(GovProjection):
    ref: ref_type("Procedure")
    matter_ref: ref_type("RegulatoryMatter")
    jurisdiction_ref: ref_type("Jurisdiction")
    effective_window: TimeWindow
    intake_mode: ValueState[Literal["receipt_only", "completeness"]]
    requirement_refs: Annotated[list[ref_type("InformationRequirement")], Field(min_length=1)]
    ineligible_decline_rule_ref: ref_type("Rule") | None
    withdrawal_rule_ref: ref_type("Rule") | None

    @model_validator(mode="after")
    def unique_requirements(self):
        if len({(ref.kind, ref.id) for ref in self.requirement_refs}) != len(self.requirement_refs):
            raise ValueError("Procedure repeats an intake requirement")
        return self


class GovRequirementView(GovProjection):
    ref: ref_type("InformationRequirement")
    procedure_ref: ref_type("Procedure")
    scope: ScopeRef
    check_kind: Literal["document", "signature", "applicant_eligibility"]
    correction_question: GovIntakeQuestion


class GovRuleView(GovProjection):
    ref: ref_type("Rule")
    scope: ScopeRef
    organization_id: TextId
    matter_ref: ref_type("RegulatoryMatter")
    procedure_ref: ref_type("Procedure")
    purpose: Literal["correction", "refer", "decline_outside_coverage", "decline_ineligible", "withdrawal"]
    recipient_id: TextId | None
    effective_window: TimeWindow


class GovAgencyAuthorityView(GovProjection):
    ref: ref_type("Authority")
    applicant_id: TextId
    submitter_id: TextId
    scope: ScopeRef
    matter_ref: ref_type("RegulatoryMatter")
    procedure_ref: ref_type("Procedure")
    effective_window: TimeWindow
    permitted: ValueState[bool]


class GovCaseView(GovProjection):
    ref: ref_type("RegulatoryCase")
    organization_id: TextId
    applicant_id: TextId
    scope: ScopeRef
    matter_ref: ref_type("RegulatoryMatter")
    procedure_ref: ref_type("Procedure")
    current_submission_ref: ref_type("Submission")
    linked_submission_refs: list[ref_type("Submission")]


class GovEvidenceTargetView(GovProjection):
    ref: ref_type("EvidenceTarget")
    submission_ref: ref_type("Submission")
    scope: ScopeRef


class GovRecipientView(GovProjection):
    ref: ref_type("RegulatoryRecipient")
    actor_id: TextId
    scope: ScopeRef


class GovResponseRequirementView(GovProjection):
    ref: ref_type("ResponseRequirement")
    rule_ref: ref_type("Rule")
    scope: ScopeRef
    description: TextId


def government_intake_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ("Submission", GovSubmissionView), ("RegulatoryMatter", GovMatterView),
        ("Jurisdiction", GovJurisdictionView), ("Procedure", GovProcedureView),
        ("InformationRequirement", GovRequirementView), ("Rule", GovRuleView),
        ("Authority", GovAgencyAuthorityView), ("RegulatoryCase", GovCaseView),
        ("EvidenceTarget", GovEvidenceTargetView), ("RegulatoryRecipient", GovRecipientView),
        ("ResponseRequirement", GovResponseRequirementView),
        ("ArchitectDeliverableReceipt", GovArchitectDeliverableReceiptView),
        ("OwnerCase", ServiceScopeCaseView), ("Organization", ServiceScopeOrganizationView),
        ("Project", ServiceScopeProjectView), ("WorkScope", ServiceWorkScopeView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
