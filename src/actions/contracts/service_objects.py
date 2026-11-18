"""Shared professional-service projections; no formal service state is created here."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    DecimalString, EvidenceRef, Measured, Money, ScopeRef, StrictRecord, TextId,
    TimePoint, TimeWindow, ValueState, ref_type,
)
from src.actions.contracts.contractor_objects import ResourceCapacity, CommittedResource
from src.actions.contracts.domain import common_projection_schemas


ServiceUse = Literal["research", "cost_estimation", "regulatory_submission", "procurement", "construction", "operation"]


class SourcedServiceProjection(StrictRecord):
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class ServiceScopeOrganizationView(SourcedServiceProjection):
    ref: ref_type("Organization")


class ServiceClockView(SourcedServiceProjection):
    ref: ref_type("ClockProfile")
    tick_unit: TextId


class ServiceScopeCaseView(SourcedServiceProjection):
    ref: ref_type("OwnerCase")
    organization_id: TextId


class ServiceScopeProjectView(SourcedServiceProjection):
    ref: ref_type("Project")


class ServiceWorkScopeView(SourcedServiceProjection):
    ref: ref_type("WorkScope")
    parent_ref: ref_type("OwnerCase") | ref_type("Project") | ref_type("Organization")


class ServiceCommissionAuthorityView(SourcedServiceProjection):
    ref: ref_type("Authority")
    organization_id: TextId
    actor_id: TextId
    purposes: list[Literal["commission_service", "authorize_payment", "internal_service"]]
    scopes: list[ScopeRef]
    service_codes: list[TextId]
    validity: TimeWindow


class ServiceRequestView(SourcedServiceProjection):
    ref: ref_type("ServiceRequest")
    scope: ScopeRef
    provider_id: TextId
    provider_organization_id: TextId
    client_id: TextId
    client_organization_id: TextId
    payer_id: TextId
    payer_organization_id: TextId
    client_authority_ref: ref_type("Authority")
    payer_authority_ref: ref_type("Authority")
    offered_terms_ref: ref_type("ServiceTerms")
    # QS-A02 does not carry a separate pricing reference in its source input;
    # when present, the authorized request projection supplies that policy.
    fee_basis_ref: ref_type("FeeBasis") | None = None
    permitted_offer_scopes: list[ScopeRef]
    permitted_service_codes: list[TextId]
    open_question_refs: list[ref_type("EvidenceTarget")]
    received_at: TimePoint
    effective_window: TimeWindow
    status: Literal["active", "withdrawn"]


class ServiceTermsView(SourcedServiceProjection):
    ref: ref_type("ServiceTerms")
    request_ref: ref_type("ServiceRequest")
    prior_terms_ref: ref_type("ServiceTerms") | None
    scope: ScopeRef
    provider_id: TextId
    client_id: TextId
    payer_id: TextId
    relation: Literal["external", "internal"]
    region_id: ValueState[TextId]
    service_code: ValueState[TextId]
    object_type: ValueState[TextId]
    requested_uses: ValueState[list[ServiceUse]]
    responsibility_codes: ValueState[list[TextId]]
    required_qualification_codes: ValueState[list[TextId]]
    required_method_refs: ValueState[list[ref_type("Method")]]
    fee: ValueState[Money]
    payment_risk: ValueState[Measured]
    work_profile_ref: ref_type("WorkProfile") | None
    effort_estimate: ValueState[Measured]
    desired_window: ValueState[TimeWindow]
    deliverable_requirement_refs: list[ref_type("DeliverableRequirement")]
    issued_at: TimePoint
    effective_window: TimeWindow
    status: Literal["offered", "proposal", "withdrawn"]
    selection_priority: ValueState[int]

    @model_validator(mode="after")
    def positive_estimates(self):
        if self.effort_estimate.state == "known" and Decimal(self.effort_estimate.value.value) <= 0:
            raise ValueError("Service effort must be positive")
        if self.fee.state == "known" and Decimal(self.fee.value.value) < 0:
            raise ValueError("Service fee cannot be negative")
        if self.payment_risk.state == "known" and Decimal(self.payment_risk.value.value) < 0:
            raise ValueError("Payment risk cannot be negative")
        return self


class ServiceIntakeCapabilityView(SourcedServiceProjection):
    ref: ref_type("Capability")
    organization_id: TextId
    effective_window: TimeWindow
    region_ids: ValueState[list[TextId]]
    service_codes: ValueState[list[TextId]]
    object_types: ValueState[list[TextId]]
    allowed_uses: ValueState[list[ServiceUse]]
    responsibility_codes: ValueState[list[TextId]]
    method_refs: ValueState[list[ref_type("Method")]]
    qualification_refs: list[ref_type("Qualification")]
    qualification_coverage: Literal["complete", "partial", "unknown"]


class ServiceQualificationView(SourcedServiceProjection):
    ref: ref_type("Qualification")
    organization_id: TextId
    code: TextId
    region_ids: list[TextId]
    service_codes: list[TextId]
    effective_window: TimeWindow
    standing: ValueState[bool]


class ServiceResourceCalendarView(SourcedServiceProjection):
    ref: ref_type("ResourceCalendar")
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal["complete", "partial", "unknown"]
    resources: list[ResourceCapacity]
    commitments: list[CommittedResource]

    @model_validator(mode="after")
    def unique_physical_resources(self):
        for rows, field in ((self.resources, "resource_ref"), (self.commitments, "commitment_ref")):
            keys = [(getattr(row, field).kind, getattr(row, field).id) for row in rows]
            if len(set(keys)) != len(keys):
                raise ValueError("Resource or commitment counted more than once")
        if any(row.total.state == "known" and Decimal(row.total.value.value) < 0 for row in self.resources):
            raise ValueError("Resource capacity cannot be negative")
        return self


class ServiceFeeBasisView(SourcedServiceProjection):
    ref: ref_type("FeeBasis")
    organization_id: TextId
    scope: ScopeRef
    effective_window: TimeWindow
    minimum_fee: ValueState[Money]
    maximum_payment_risk: ValueState[Measured]
    new_work_policy: ValueState[Literal["evaluate", "decline", "defer"]]
    counteroffer_terms_refs: list[ref_type("ServiceTerms")]
    counteroffer_calculation_refs: list[ref_type("FeeCalculation")]

    @model_validator(mode="after")
    def consistent_pricing(self):
        if self.minimum_fee.state == "known" and Decimal(self.minimum_fee.value.value) < 0:
            raise ValueError("Minimum service fee cannot be negative")
        if self.maximum_payment_risk.state == "known" and Decimal(self.maximum_payment_risk.value.value) < 0:
            raise ValueError("Maximum payment risk cannot be negative")
        for refs in (self.counteroffer_terms_refs, self.counteroffer_calculation_refs):
            if len({ref.key() for ref in refs}) != len(refs):
                raise ValueError("Pricing alternative reference repeated")
        return self


class ServiceWorkProfileView(SourcedServiceProjection):
    ref: ref_type("WorkProfile")
    region_ids: list[TextId]
    service_codes: list[TextId]
    object_types: list[TextId]
    effective_window: TimeWindow
    clock_ref: ref_type("ClockProfile")
    resource_kind: TextId
    effort_unit: TextId
    capacity_unit: TextId
    # Productivity in effort units per capacity unit per business-clock tick.
    effort_per_capacity_tick: DecimalString
    method: TextId

    @model_validator(mode="after")
    def positive_conversion(self):
        if Decimal(self.effort_per_capacity_tick) <= 0:
            raise ValueError("Work profile effort conversion must be positive")
        return self


class ServiceMethodView(SourcedServiceProjection):
    ref: ref_type("Method")
    purpose: Literal["service_support", "fee_calculation"]
    region_ids: list[TextId]
    service_codes: list[TextId]
    object_types: list[TextId]
    effective_window: TimeWindow


class ServiceFeeCalculationView(SourcedServiceProjection):
    ref: ref_type("FeeCalculation")
    organization_id: TextId
    scope: ScopeRef
    terms_ref: ref_type("ServiceTerms")
    fee_basis_ref: ref_type("FeeBasis")
    method_ref: ref_type("Method")
    executed_at: TimePoint
    execution_status: Literal["succeeded", "failed"]
    amount: Money


class ServiceDeliverableRequirementView(SourcedServiceProjection):
    ref: ref_type("DeliverableRequirement")
    request_ref: ref_type("ServiceRequest")
    scope: ScopeRef
    requested_use: ServiceUse
    description: TextId


class ServiceClarificationTargetView(SourcedServiceProjection):
    ref: ref_type("EvidenceTarget")
    request_ref: ref_type("ServiceRequest")
    scope: ScopeRef
    question: TextId
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    blocking_uses: list[ServiceUse]
    response_requirement_ref: ref_type("ResponseRequirement")


class ServiceResponseRequirementView(SourcedServiceProjection):
    ref: ref_type("ResponseRequirement")
    request_ref: ref_type("ServiceRequest")
    scope: ScopeRef
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]


class ServiceInternalFeeRuleView(SourcedServiceProjection):
    ref: ref_type("Rule")
    code: Literal["internal_service_no_self_invoice"]
    organization_id: TextId
    scope: ScopeRef
    effective_window: TimeWindow


def service_intake_schemas(overrides=None):
    registry = common_projection_schemas()
    schemas = dict((
        ("ClockProfile", ServiceClockView),
        ("Organization", ServiceScopeOrganizationView), ("OwnerCase", ServiceScopeCaseView),
        ("Project", ServiceScopeProjectView), ("WorkScope", ServiceWorkScopeView),
        ("Authority", ServiceCommissionAuthorityView), ("ServiceRequest", ServiceRequestView),
        ("ServiceTerms", ServiceTermsView), ("Capability", ServiceIntakeCapabilityView),
        ("Qualification", ServiceQualificationView), ("ResourceCalendar", ServiceResourceCalendarView),
        ("FeeBasis", ServiceFeeBasisView), ("WorkProfile", ServiceWorkProfileView),
        ("Method", ServiceMethodView), ("FeeCalculation", ServiceFeeCalculationView),
        ("DeliverableRequirement", ServiceDeliverableRequirementView),
        ("EvidenceTarget", ServiceClarificationTargetView), ("ResponseRequirement", ServiceResponseRequirementView),
        ("Rule", ServiceInternalFeeRuleView),
    ))
    if overrides:
        schemas.update(overrides)
    for kind, schema in schemas.items():
        registry.register_kind(kind, schema, str)
    return registry
