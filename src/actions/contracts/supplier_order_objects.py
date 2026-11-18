"""Closed A04 host projections; accepted drafts are never formal orders."""
from decimal import Decimal
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.supplier_objects import SupplierProjection
from src.actions.contracts.supplier_quote_objects import (
    QuoteProductLine, QuoteInventoryView, QuoteCapacityView, QuoteLocationView,
    QuoteServiceView, QuoteResourcePoolView, QuoteResourceUse, QuotePaymentRule,
)
from src.actions.contracts.supplier_product_objects import ProductSpecificationView, ProductDeviationView
from src.actions.contracts.service_objects import ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView


class OrderDeliveryLine(StrictRecord):
    product: QuoteProductLine
    delivery_window_ref: ref_type("TimeWindow")
    destination_ref: ref_type("Location")
    included_service_refs: Annotated[list[ref_type("DeliveryService")], Field(min_length=1)]
    price: Money

    @model_validator(mode="after")
    def positive_delivery(self):
        if Decimal(self.product.quantity.value) <= 0 or Decimal(self.price.value) <= 0:
            raise ValueError("Order line quantity and binding batch price must be positive")
        for refs in (self.included_service_refs, self.product.requirement_refs, self.product.deviation_refs):
            if len({ref.key() for ref in refs}) != len(refs):
                raise ValueError("Order line scope, deviation or service reference repeated")
        if not self.product.requirement_refs:
            raise ValueError("Order line must identify its requirements")
        return self


class SupplyOfferLine(StrictRecord):
    local_key: TextId
    delivery: OrderDeliveryLine


class FormationOfferView(SupplierProjection):
    ref: ref_type("SupplyOffer")
    supplier_organization_id: TextId
    buyer_id: TextId
    payer_id: TextId
    scope: ScopeRef
    status: Literal["active", "withdrawn", "superseded"]
    available_at: TimePoint
    validity_ref: ref_type("TimeWindow")
    terms_ref: ref_type("SupplyTerms")
    condition_refs: list[ref_type("Requirement")]
    lines: Annotated[list[SupplyOfferLine], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_lines(self):
        if len({row.local_key for row in self.lines}) != len(self.lines):
            raise ValueError("Quoted batch identity repeated")
        return self


class OrderProposalLine(StrictRecord):
    local_key: TextId
    offer_line_key: TextId
    delivery: OrderDeliveryLine


class OrderProposalView(SupplierProjection):
    ref: ref_type("OrderProposal")
    offer_ref: ref_type("SupplyOffer")
    supplier_organization_id: TextId
    recipient_actor_id: TextId
    buyer_id: TextId
    payer_id: TextId
    scope: ScopeRef
    status: Literal["active", "withdrawn", "superseded"]
    received_at: TimePoint
    response_window: TimeWindow
    terms_ref: ref_type("SupplyTerms")
    condition_refs: list[ref_type("Requirement")]
    lines: Annotated[list[OrderProposalLine], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_lines(self):
        for field in ("local_key", "offer_line_key"):
            if len({getattr(row, field) for row in self.lines}) != len(self.lines):
                raise ValueError("Order proposal repeats a physical quoted batch")
        return self


def order_agreement(proposal):
    """Exact public proposed agreement; no private stock, funds or policy."""
    data = proposal.model_dump(mode="json") if isinstance(proposal, OrderProposalView) else proposal
    fields = ("ref", "offer_ref", "supplier_organization_id", "buyer_id", "payer_id", "scope", "terms_ref", "condition_refs", "lines")
    return {field: data[field] for field in fields}


def order_agreement_digest(proposal):
    return hashlib.sha256(json.dumps(order_agreement(proposal), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class FormationAcceptanceView(SupplierProjection):
    ref: ref_type("PartyAcceptance")
    run_id: TextId
    proposal_ref: ref_type("OrderProposal")
    offer_ref: ref_type("SupplyOffer")
    terms_ref: ref_type("SupplyTerms")
    scope: ScopeRef
    party_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type("FunctionAssignment")
    authorization_ref: ref_type("Authorization")
    action_id: TextId
    agreement_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    choice: Literal["accept", "reject", "revise"]
    status: Literal["active", "withdrawn"]
    created_at: TimePoint
    validity: TimeWindow


class FormationTermsView(SupplierProjection):
    ref: ref_type("SupplyTerms")
    offer_ref: ref_type("SupplyOffer")
    order_proposal_ref: ref_type("OrderProposal") | None
    supplier_organization_id: TextId
    buyer_id: TextId
    payer_id: TextId
    currency: TextId
    effective_window: TimeWindow
    payment_rules: Annotated[list[QuotePaymentRule], Field(min_length=1)]


class FormationRequirementView(SupplierProjection):
    ref: ref_type("Requirement")
    offer_ref: ref_type("SupplyOffer")
    order_proposal_ref: ref_type("OrderProposal") | None
    scope: ScopeRef
    condition_code: TextId
    satisfied: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow


class FormationFundingView(SupplierProjection):
    ref: ref_type("FundingPosition")
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal["complete", "partial", "unknown"]
    actual_cash: ValueState[Money]
    committed_cash: ValueState[Money]


class FormationStockUse(StrictRecord):
    batch_ref: ref_type("ProductBatch")
    quantity: Measured


class FormationPlanLine(StrictRecord):
    order_line_key: TextId
    delivery: OrderDeliveryLine
    source_location_ref: ref_type("Location")
    stock_uses: list[FormationStockUse]
    resource_uses: list[QuoteResourceUse]
    working_capital: ValueState[Money]


class FormationPlanView(SupplierProjection):
    ref: ref_type("SupplyCommitmentPlan")
    organization_id: TextId
    offer_ref: ref_type("SupplyOffer")
    order_proposal_ref: ref_type("OrderProposal")
    purpose: Literal["full_order", "partial_counterproposal"]
    available_at: TimePoint
    effective_window: TimeWindow
    lines: Annotated[list[FormationPlanLine], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_lines(self):
        if len({row.order_line_key for row in self.lines}) != len(self.lines):
            raise ValueError("Commitment plan line repeated")
        return self


class FormationCommercialRule(StrictRecord):
    order_line_key: TextId
    offer_line_key: TextId
    scope: ScopeRef
    allowed_product_refs: Annotated[list[ref_type("ProductSpecification")], Field(min_length=1)]
    maximum_quantity: Measured
    minimum_unit_price: Money
    minimum_batch_price: Money
    allowed_window_ref: ref_type("TimeWindow")
    allowed_destination_refs: Annotated[list[ref_type("Location")], Field(min_length=1)]
    required_service_refs: Annotated[list[ref_type("DeliveryService")], Field(min_length=1)]
    prerequisite_refs: list[ref_type("Requirement")]
    allowed_fulfillment_modes: Annotated[list[Literal["stock", "manufacture"]], Field(min_length=1)]


class FormationPartialPriority(StrictRecord):
    plan_ref: ref_type("SupplyCommitmentPlan")
    priority: int


class FormationProfileView(SupplierProjection):
    ref: ref_type("SupplyFormationProfile")
    organization_id: TextId
    offer_ref: ref_type("SupplyOffer")
    order_proposal_ref: ref_type("OrderProposal")
    effective_window: TimeWindow
    algorithm_code: TextId
    policy: Literal["evaluate", "prefer_partial", "revise", "reject_new_orders"]
    on_conflict: Literal["reject", "revise", "partial"]
    currency: ValueState[TextId]
    required_counterparty_ids: ValueState[list[TextId]]
    counterpart_action_ids: list[TextId]
    allowed_terms_refs: list[ref_type("SupplyTerms")]
    full_plan_ref: ref_type("SupplyCommitmentPlan") | None
    partial_plans: list[FormationPartialPriority]
    revision_requirement_refs: list[ref_type("Requirement")]
    commercial_rules: list[FormationCommercialRule]
    permitted_quote_changes: list[Literal["product", "quantity", "price", "delivery_window", "destination", "services", "terms", "conditions", "payer"]]
    reviewed_agreement_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None

    @model_validator(mode="after")
    def unique_policy(self):
        if len(set(self.permitted_quote_changes)) != len(self.permitted_quote_changes):
            raise ValueError("Permitted quote change repeated")
        if len({row.order_line_key for row in self.commercial_rules}) != len(self.commercial_rules):
            raise ValueError("Commercial rule line repeated")
        if len({(row.plan_ref.kind, row.plan_ref.id) for row in self.partial_plans}) != len(self.partial_plans):
            raise ValueError("Partial plan identity repeated across versions")
        return self


def supplier_order_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ("SupplyOffer", FormationOfferView), ("OrderProposal", OrderProposalView), ("PartyAcceptance", FormationAcceptanceView),
        ("SupplyTerms", FormationTermsView), ("Requirement", FormationRequirementView), ("FundingPosition", FormationFundingView),
        ("SupplyFormationProfile", FormationProfileView), ("SupplyCommitmentPlan", FormationPlanView),
        ("InventorySnapshot", QuoteInventoryView), ("SupplierCapacity", QuoteCapacityView),
        ("ProductSpecification", ProductSpecificationView), ("SpecificationDeviation", ProductDeviationView),
        ("Location", QuoteLocationView), ("DeliveryService", QuoteServiceView), ("ResourcePool", QuoteResourcePoolView),
        ("OwnerCase", ServiceScopeCaseView), ("Organization", ServiceScopeOrganizationView),
        ("Project", ServiceScopeProjectView), ("WorkScope", ServiceWorkScopeView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
