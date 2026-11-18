"""Sourced supplier screening projections; no order, inventory or capacity ledger."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    DecimalString, EvidenceRef, Measured, ScopeRef, StrictRecord, TextId,
    TimePoint, TimeWindow, ValueState, ref_type,
)
from src.actions.contracts.contractor_objects import ResourceCapacity, CommittedResource
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.professional_outreach import ProfessionalOutreachLimits, ProfessionalOutreachObservation
from src.actions.contracts.supplier_monthly_prices import SupplierPriceMonitorPolicy,SupplierPriceMonitorObservation
from src.actions.contracts.service_objects import (
    ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView,
)


class SupplierProjection(StrictRecord):
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class SupplyInquiryLine(StrictRecord):
    requirement_ref: ref_type("Requirement")
    scope: ScopeRef
    product_code: ValueState[TextId]
    quantity: ValueState[Measured]
    production_region_id: ValueState[TextId]
    delivery_region_id: ValueState[TextId]
    work_window: ValueState[TimeWindow]
    required_function_codes: ValueState[list[TextId]]
    allowed_fulfillment_modes: ValueState[list[Literal["manufacture", "purchase"]]]

    @model_validator(mode="after")
    def positive_quantity(self):
        if self.quantity.state == "known" and Decimal(self.quantity.value.value) <= 0:
            raise ValueError("Inquiry quantity must be positive")
        return self


class SupplyInquiryView(SupplierProjection):
    ref: ref_type("SupplyInquiry")
    scope: ScopeRef
    buyer_id: TextId
    recipient_id: TextId
    recipient_organization_id: TextId
    received_at: TimePoint
    response_window: TimeWindow
    status: Literal["active", "withdrawn"]
    allow_partial_scope: bool
    lines: Annotated[list[SupplyInquiryLine], Field(min_length=1)]
    clarification_requirement_refs: list[ref_type("Requirement")]

    @model_validator(mode="after")
    def independent_line_scopes(self):
        questions = [(ref.kind, ref.id) for ref in self.clarification_requirement_refs]
        if len(set(questions)) != len(questions):
            raise ValueError("Clarification requirement identity repeated across versions")
        identities = [(item.requirement_ref.kind, item.requirement_ref.id) for item in self.lines]
        if len(set(identities)) != len(identities):
            raise ValueError("Inquiry requirement identity repeated")
        parent_keys = {ref.key() for ref in self.scope.coverage_refs}
        if len(parent_keys) != len(self.scope.coverage_refs):
            raise ValueError("Inquiry parent scope coverage repeated")
        covered = []
        for line in self.lines:
            if line.scope.kind != self.scope.kind or line.scope.ref != self.scope.ref:
                raise ValueError("Inquiry line belongs to another parent scope")
            line_keys = {ref.key() for ref in line.scope.coverage_refs}
            if not line_keys <= parent_keys or len(line_keys) != len(line.scope.coverage_refs):
                raise ValueError("Inquiry line exceeds or duplicates its declared scope")
            if len(self.lines) > 1 and not line_keys:
                raise ValueError("Multiple inquiry lines require explicit disjoint coverage")
            covered.extend(line_keys)
        if len(set(covered)) != len(covered):
            raise ValueError("Inquiry line coverage overlaps")
        if self.scope.coverage_refs and set(covered) != {ref.key() for ref in self.scope.coverage_refs}:
            raise ValueError("Inquiry lines do not cover the exact requested scope")
        return self


class SupplierProductSupport(StrictRecord):
    product_code: TextId
    function_codes: ValueState[list[TextId]]
    production_region_ids: ValueState[list[TextId]]
    delivery_region_ids: ValueState[list[TextId]]
    method_ref: ref_type("WorkMethod")


class SupplierCapabilityView(SupplierProjection):
    ref: ref_type("SupplierCapability")
    organization_id: TextId
    registration_region_id: ValueState[TextId]
    operating_region_ids: ValueState[list[TextId]]
    effective_window: TimeWindow
    product_coverage: Literal["complete", "partial", "unknown"]
    products: list[SupplierProductSupport]
    function_authority_refs: list[ref_type("Authority")]

    @model_validator(mode="after")
    def unique_products(self):
        if len({item.product_code for item in self.products}) != len(self.products):
            raise ValueError("Product screening support repeated")
        return self


class SupplierCapacityView(SupplierProjection):
    ref: ref_type("SupplierCapacity")
    organization_id: TextId
    as_of: TimePoint
    resource_coverage: Literal["complete", "partial", "unknown"]
    commitment_coverage: Literal["complete", "partial", "unknown"]
    resources: list[ResourceCapacity]
    commitments: list[CommittedResource]

    @model_validator(mode="after")
    def unique_resource_and_commitment_identity(self):
        for values, field in ((self.resources, "resource_ref"), (self.commitments, "commitment_ref")):
            keys = [(getattr(item, field).kind, getattr(item, field).id) for item in values]
            if len(keys) != len(set(keys)):
                raise ValueError("Capacity or commitment identity repeated across versions")
        for item in self.resources:
            if item.total.state == "known" and Decimal(item.total.value.value) < 0:
                raise ValueError("Supplier capacity cannot be negative")
        return self


class SupplyPriority(StrictRecord):
    inquiry_ref: ref_type("SupplyInquiry")
    priority: ValueState[int]


class SupplyScreeningProfileView(SupplierProjection):
    outreach_limits: ProfessionalOutreachLimits | None = None
    monthly_price_policy_ref:ref_type('SupplierPriceMonitorPolicy')|None=None
    monthly_price_observation_ref:ref_type('SupplierPriceMonitorObservation')|None=None
    ref: ref_type("SupplyScreeningProfile")
    organization_id: TextId
    effective_window: TimeWindow
    policy: Literal["evaluate", "decline_new_work", "defer_new_work"]
    allow_limited_scope: bool
    inquiry_priorities: list[SupplyPriority]

    @model_validator(mode="after")
    def unique_priorities(self):
        ids = [(item.inquiry_ref.kind, item.inquiry_ref.id) for item in self.inquiry_priorities]
        if len(set(ids)) != len(ids):
            raise ValueError("Inquiry priority identity repeated across versions")
        return self


class SupplyWorkMethodView(SupplierProjection):
    ref: ref_type("WorkMethod")
    organization_id: TextId
    product_code: TextId
    fulfillment_mode: Literal["manufacture", "purchase"]
    production_region_id: TextId
    delivery_region_ids: list[TextId]
    function_codes: list[TextId]
    effective_window: TimeWindow
    quantity_unit: TextId
    resource_kind: TextId
    capacity_unit: TextId
    units_per_capacity_tick: DecimalString
    method: Literal["constant_capacity_over_half_open_window_v1"]

    @model_validator(mode="after")
    def positive_productivity(self):
        if Decimal(self.units_per_capacity_tick) <= 0:
            raise ValueError("Supply screening productivity must be positive")
        return self


class SupplierFunctionAuthorityView(SupplierProjection):
    ref: ref_type("Authority")
    organization_id: TextId
    actor_id: TextId
    scope: ScopeRef
    function_codes: list[TextId]
    effective_window: TimeWindow


class SupplyRequirementView(SupplierProjection):
    ref: ref_type("Requirement")
    inquiry_ref: ref_type("SupplyInquiry")
    scope: ScopeRef
    description: TextId


class SupplyMarketObservationView(SupplierProjection):
    ref: ref_type("MarketObservation")
    scope: ScopeRef
    region_id: ValueState[TextId]
    product_codes: ValueState[list[TextId]]
    forecast_quantity: ValueState[Measured]
    forecast_window: ValueState[TimeWindow]
    observed_at: TimePoint
    available_at: TimePoint


def supplier_screening_schemas():
    registry = common_projection_schemas()
    registry.register_kind('OutreachObservation', ProfessionalOutreachObservation, str)
    registry.register_kind('SupplierPriceMonitorPolicy',SupplierPriceMonitorPolicy,str)
    registry.register_kind('SupplierPriceMonitorObservation',SupplierPriceMonitorObservation,str)
    for kind, schema in (
        ("SupplyInquiry", SupplyInquiryView), ("SupplierCapability", SupplierCapabilityView),
        ("SupplierCapacity", SupplierCapacityView), ("SupplyScreeningProfile", SupplyScreeningProfileView),
        ("WorkMethod", SupplyWorkMethodView), ("Authority", SupplierFunctionAuthorityView),
        ("Requirement", SupplyRequirementView), ("MarketObservation", SupplyMarketObservationView),
        ("OwnerCase", ServiceScopeCaseView), ("Organization", ServiceScopeOrganizationView),
        ("Project", ServiceScopeProjectView), ("WorkScope", ServiceWorkScopeView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
