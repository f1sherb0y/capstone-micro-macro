"""Authorized A03 projections; rates and policies are explicit sourced facts."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.supplier_objects import SupplierProjection, SupplyInquiryView
from src.actions.contracts.service_objects import ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView


class QuoteInquiryView(SupplyInquiryView):
    payer_id: ValueState[TextId]
    currency: ValueState[TextId]
    required_service_codes: ValueState[list[TextId]]


class QuoteProductLine(StrictRecord):
    product_ref: ref_type("ProductSpecification")
    destination_scope_ref: ScopeRef
    quantity: Measured
    requirement_refs: list[ref_type("Requirement")]
    deviation_refs: list[ref_type("SpecificationDeviation")]


class QuoteProposalLine(StrictRecord):
    local_key: TextId
    product: QuoteProductLine


class QuoteProposalView(SupplierProjection):
    ref: ref_type("ProductProposal")
    inquiry_ref: ref_type("SupplyInquiry")
    supplier_organization_id: TextId
    status: Literal["pending_confirmation", "confirmed", "rejected", "withdrawn"]
    confirmation_requirement_ref: ref_type("Requirement") | None
    prerequisite_refs: list[ref_type("Requirement")]
    effective_window: TimeWindow
    available_at: TimePoint
    lines: Annotated[list[QuoteProposalLine], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_lines(self):
        if len({row.local_key for row in self.lines}) != len(self.lines):
            raise ValueError("Product proposal local key repeated")
        if self.status == "pending_confirmation" and self.confirmation_requirement_ref is None:
            raise ValueError("Unconfirmed proposal must expose an explicit confirmation prerequisite")
        if any(Decimal(row.product.quantity.value) <= 0 for row in self.lines):
            raise ValueError("Proposed quantity must be positive")
        return self


class QuoteRequirementView(SupplierProjection):
    ref: ref_type("Requirement")
    inquiry_ref: ref_type("SupplyInquiry")
    scope: ScopeRef
    condition_code: TextId
    product_proposal_ref: ref_type("ProductProposal") | None


class QuoteCostView(SupplierProjection):
    ref: ref_type("CostBasis")
    supplier_organization_id: TextId
    product_ref: ref_type("ProductSpecification")
    destination_scope_ref: ScopeRef
    quantity_unit: TextId
    service_code: TextId
    unit_cost: ValueState[Money]
    per_batch_cost: ValueState[Money]
    effective_window: TimeWindow
    available_at: TimePoint
    purpose: Literal["binding_quote", "indicative_only"]


class QuoteStockLot(StrictRecord):
    batch_ref: ref_type("ProductBatch")
    product_ref: ref_type("ProductSpecification")
    location_ref: ref_type("Location")
    status: Literal["usable", "quarantined"]
    actual: Measured
    committed: Measured


class QuoteInventoryView(SupplierProjection):
    ref: ref_type("InventorySnapshot")
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal["complete", "partial", "unknown"]
    lots: list[QuoteStockLot]

    @model_validator(mode="after")
    def actual_stock(self):
        keys = [(row.batch_ref.kind, row.batch_ref.id) for row in self.lots]
        if len(set(keys)) != len(keys):
            raise ValueError("Physical stock batch repeated across versions")
        for lot in self.lots:
            if (lot.actual.unit != lot.committed.unit or Decimal(lot.actual.value) < 0
                    or Decimal(lot.committed.value) < 0 or Decimal(lot.committed.value) > Decimal(lot.actual.value)):
                raise ValueError("Actual and committed inventory must use identical units and valid quantities")
        return self


class QuotePool(StrictRecord):
    resource_ref: ref_type("ResourcePool")
    region_id: TextId
    total: ValueState[Measured]
    effective_window: TimeWindow


class QuoteCommitment(StrictRecord):
    commitment_ref: ref_type("ResourceCommitment")
    resource_ref: ref_type("ResourcePool")
    quantity: Measured
    window: TimeWindow


class QuoteCapacityView(SupplierProjection):
    ref: ref_type("SupplierCapacity")
    organization_id: TextId
    as_of: TimePoint
    resource_coverage: Literal["complete", "partial", "unknown"]
    commitment_coverage: Literal["complete", "partial", "unknown"]
    resources: list[QuotePool]
    commitments: list[QuoteCommitment]

    @model_validator(mode="after")
    def unique_pools(self):
        for rows, field in ((self.resources, "resource_ref"), (self.commitments, "commitment_ref")):
            keys = [(getattr(row, field).kind, getattr(row, field).id) for row in rows]
            if len(set(keys)) != len(keys):
                raise ValueError("Physical capacity pool or commitment repeated across versions")
        return self


class QuoteLocationView(SupplierProjection):
    ref: ref_type("Location")
    region_id: TextId
    factory_id: TextId | None


class QuoteResourcePoolView(SupplierProjection):
    ref: ref_type("ResourcePool")
    organization_id: TextId
    region_id: TextId


class QuoteServiceView(SupplierProjection):
    ref: ref_type("DeliveryService")
    service_code: TextId
    provider_organization_id: TextId
    destination_ref: ref_type("Location")
    effective_window: TimeWindow


class QuoteResourceUse(StrictRecord):
    resource_ref: ref_type("ResourcePool")
    window_ref: ref_type("TimeWindow")
    # Constant rate per product unit for this declared schedule. It is an
    # explicit method/scenario assumption, not inferred factory productivity.
    rate_per_product_unit: Measured
    source: Literal["manufacture", "delivery"]


class QuoteDelivery(StrictRecord):
    local_key: TextId
    proposal_line_key: TextId
    quantity: Measured
    inventory_quantity: Measured
    source_location_ref: ref_type("Location")
    destination_ref: ref_type("Location")
    delivery_window_ref: ref_type("TimeWindow")
    included_service_refs: Annotated[list[ref_type("DeliveryService")], Field(min_length=1)]
    cost_basis_refs: Annotated[list[ref_type("CostBasis")], Field(min_length=1)]
    resource_uses: list[QuoteResourceUse]


class QuoteLogisticsView(SupplierProjection):
    ref: ref_type("LogisticsAssessment")
    supplier_organization_id: TextId
    product_proposal_ref: ref_type("ProductProposal")
    inquiry_ref: ref_type("SupplyInquiry")
    available_at: TimePoint
    effective_window: TimeWindow
    feasible: ValueState[bool]
    prerequisite_refs: list[ref_type("Requirement")]
    deliveries: Annotated[list[QuoteDelivery], Field(min_length=1)]


class QuotePaymentRule(StrictRecord):
    milestone_code: TextId
    fraction: DecimalString


class QuoteTermsView(SupplierProjection):
    ref: ref_type("SupplyTerms")
    inquiry_ref: ref_type("SupplyInquiry")
    supplier_organization_id: TextId
    buyer_id: TextId
    payer_id: TextId
    currency: TextId
    effective_window: TimeWindow
    payment_rules: Annotated[list[QuotePaymentRule], Field(min_length=1)]
    prerequisite_refs: list[ref_type("Requirement")]


class QuotePriority(StrictRecord):
    proposal_ref: ref_type("ProductProposal")
    priority: int


class QuoteProfileView(SupplierProjection):
    ref: ref_type("SupplyPricingProfile")
    organization_id: TextId
    effective_window: TimeWindow
    policy: Literal["evaluate", "decline_new_quotes"]
    algorithm_code: TextId
    price_basis: Literal["batch_total_included_services"]
    markup_rate: ValueState[DecimalString]
    minor_places: Annotated[int, Field(ge=0, le=8)]
    currency: ValueState[TextId]
    required_service_codes: ValueState[list[TextId]]
    terms_ref: ref_type("SupplyTerms")
    validity_ref: ref_type("TimeWindow")
    proposal_priorities: list[QuotePriority]


def supplier_quote_schemas():
    registry = common_projection_schemas()
    for kind, schema in (("SupplyInquiry", QuoteInquiryView), ("ProductProposal", QuoteProposalView),
        ("CostBasis", QuoteCostView), ("InventorySnapshot", QuoteInventoryView), ("SupplierCapacity", QuoteCapacityView),
        ("LogisticsAssessment", QuoteLogisticsView), ("SupplyPricingProfile", QuoteProfileView), ("SupplyTerms", QuoteTermsView),
        ("Location", QuoteLocationView), ("DeliveryService", QuoteServiceView),
        ("ResourcePool", QuoteResourcePoolView),
        ("Requirement", QuoteRequirementView), ("OwnerCase", ServiceScopeCaseView), ("Organization", ServiceScopeOrganizationView),
        ("Project", ServiceScopeProjectView), ("WorkScope", ServiceWorkScopeView)):
        registry.register_kind(kind, schema, str)
    from src.actions.contracts.supplier_product_objects import ProductSpecificationView, ProductDeviationView
    registry.register_kind("ProductSpecification", ProductSpecificationView, str)
    registry.register_kind("SpecificationDeviation", ProductDeviationView, str)
    return registry
