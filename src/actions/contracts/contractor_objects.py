"""Read projections for CONTRACTOR-A01, based on CONTRACTOR-003/029 and OBJ-002.

These internal schemas describe authorized facts, not new macro endpoints.
The supported resource comparison is explicitly limited to homogeneous units,
one clock, fixed locations and half-open windows; no relocation is inferred.
"""
from decimal import Decimal
from src.actions.contracts.professional_outreach import ProfessionalOutreachLimits
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    EvidenceRef, Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow,
    ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas


class SourcedProjection(StrictRecord):
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class QualificationRequirement(StrictRecord):
    requirement_ref: ref_type("Requirement")
    qualification_code: TextId
    region_id: TextId
    work_type: TextId


class ResourceDemand(StrictRecord):
    requirement_ref: ref_type("Requirement")
    resource_kind: TextId
    region_id: TextId
    quantity: Measured
    window: TimeWindow

    @model_validator(mode="after")
    def positive(self):
        if Decimal(self.quantity.value) <= 0:
            raise ValueError("A resource demand must be positive")
        return self


class ProcurementPackageView(SourcedProjection):
    ref: ref_type("ProcurementPackage")
    employer_ref: ref_type("Organization")
    scope: ScopeRef
    access_mode: Literal["public", "invitation_only"]
    region_id: ValueState[TextId]
    work_types: ValueState[list[TextId]]
    participation_window: ValueState[TimeWindow]
    work_window: ValueState[TimeWindow]
    qualification_requirements: ValueState[list[QualificationRequirement]]
    required_method_refs: ValueState[list[ref_type("WorkMethod")]]
    resource_demands: ValueState[list[ResourceDemand]]
    funding_signal: ValueState[bool]
    clarification_requirement_refs: list[ref_type("Requirement")]


class ResourceCapacity(StrictRecord):
    resource_ref: ref_type("Resource")
    resource_kind: TextId
    region_id: ValueState[TextId]
    total: ValueState[Measured]
    effective_window: TimeWindow


class ContractorCapabilityView(SourcedProjection):
    ref: ref_type("ContractorCapability")
    organization_ref: ref_type("Organization")
    effective_window: TimeWindow
    work_types: ValueState[list[TextId]]
    method_refs: ValueState[list[ref_type("WorkMethod")]]
    qualification_coverage: Literal["complete", "partial", "unknown"]
    resource_coverage: Literal["complete", "partial", "unknown"]
    resources: list[ResourceCapacity]

    @model_validator(mode="after")
    def unique_resources(self):
        keys = [(item.resource_ref.kind, item.resource_ref.id) for item in self.resources]
        if len(keys) != len(set(keys)):
            raise ValueError("A resource identity cannot contribute capacity twice")
        for item in self.resources:
            if item.total.state == "known" and Decimal(item.total.value.value) < 0:
                raise ValueError("Resource capacity cannot be negative")
        return self


class QualificationView(SourcedProjection):
    ref: ref_type("Qualification")
    organization_ref: ref_type("Organization")
    qualification_code: TextId
    region_ids: list[TextId]
    work_types: list[TextId]
    effective_window: TimeWindow
    standing: ValueState[bool]


class InvitationView(SourcedProjection):
    ref: ref_type("Invitation")
    package_ref: ref_type("ProcurementPackage")
    issuer_ref: ref_type("Organization")
    recipient_actor_id: TextId
    effective_window: TimeWindow


class CommittedResource(StrictRecord):
    commitment_ref: ref_type("ResourceCommitment")
    resource_ref: ref_type("Resource")
    quantity: Measured
    window: TimeWindow

    @model_validator(mode="after")
    def positive(self):
        if Decimal(self.quantity.value) <= 0:
            raise ValueError("An existing resource commitment must be positive")
        return self


class CommitmentSnapshotView(SourcedProjection):
    ref: ref_type("CommitmentSnapshot")
    organization_ref: ref_type("Organization")
    as_of: TimePoint
    coverage: Literal["complete", "partial", "unknown"]
    allocations: list[CommittedResource]

    @model_validator(mode="after")
    def unique_allocations(self):
        keys = [(item.commitment_ref.kind, item.commitment_ref.id) for item in self.allocations]
        if len(keys) != len(set(keys)):
            raise ValueError("An existing commitment cannot consume capacity twice")
        return self


class OpportunityScreeningProfileView(SourcedProjection):
    outreach_limits: ProfessionalOutreachLimits | None = None
    monthly_region_policy_ref: ref_type('RegionEntryReviewPolicy') | None = None
    monthly_region_observation_ref: ref_type('RegionEntryReviewObservation') | None = None
    monthly_jv_policy_ref: ref_type('JVPartnerReviewPolicy') | None = None
    monthly_jv_observation_ref: ref_type('JVPartnerReviewObservation') | None = None
    ref: ref_type("OpportunityScreeningProfile")
    organization_ref: ref_type("Organization")
    effective_window: TimeWindow
    policy: Literal["participate_if_eligible", "decline_new_work"]
    require_known_funding_signal: bool
    decline_on_negative_funding_signal: bool
    resource_comparison: Literal["fixed_location_half_open_exact_v1"]


class WorkMethodSupportView(SourcedProjection):
    ref: ref_type("WorkMethod")
    region_ids: list[TextId]
    work_types: list[TextId]
    effective_window: TimeWindow


class ScreeningRequirementView(SourcedProjection):
    ref: ref_type("Requirement")
    package_ref: ref_type("ProcurementPackage")
    description: TextId


def contractor_screening_schemas():
    registry = common_projection_schemas()
    from src.actions.contracts.contractor_jv_review import JVPartnerReviewPolicy,JVPartnerReviewObservation
    registry.register_kind('JVPartnerReviewPolicy',JVPartnerReviewPolicy,str)
    registry.register_kind('JVPartnerReviewObservation',JVPartnerReviewObservation,str)
    from src.actions.contracts.contractor_region_review import RegionEntryReviewPolicy,RegionEntryReviewObservation,RegionalPartnerDisclosure
    for kind,schema in [('RegionEntryReviewPolicy',RegionEntryReviewPolicy),('RegionEntryReviewObservation',RegionEntryReviewObservation),('RegionalPartnerDisclosure',RegionalPartnerDisclosure)]:
        registry.register_kind(kind,schema,str)
    from src.actions.contracts.professional_outreach import ProfessionalOutreachObservation
    registry.register_kind('OutreachObservation',ProfessionalOutreachObservation,str)
    for kind, schema in (
        ("ProcurementPackage", ProcurementPackageView),
        ("ContractorCapability", ContractorCapabilityView),
        ("Qualification", QualificationView), ("Invitation", InvitationView),
        ("CommitmentSnapshot", CommitmentSnapshotView),
        ("OpportunityScreeningProfile", OpportunityScreeningProfileView),
        ("WorkMethod", WorkMethodSupportView), ("Requirement", ScreeningRequirementView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
