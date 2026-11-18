"""Sourced production/purchase plans are requests, never physical stock."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, Money, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_quote_objects import QuoteProductLine, QuoteInventoryView, QuoteCapacityView
from src.actions.contracts.supplier_order_objects import FormationOfferView, FormationTermsView


class SupplierPlannedAllocation(StrictRecord):
    resource_ref: ref_type('ResourcePool')
    scope_ref: ScopeRef
    window_ref: ref_type('TimeWindow')
    quantity: Measured


class SupplierPlannedInput(StrictRecord):
    product_ref: ref_type('ProductSpecification')
    required: Measured
    available_allocation_refs: list[ref_type('InventoryAllocation')]
    acquisition_requirement_refs: list[ref_type('SupplyRequirement')]


class SupplierPlannedTask(StrictRecord):
    local_key: TextId
    mode: Literal['manufacture', 'purchase', 'rework']
    scope_ref: ScopeRef
    method_ref: ref_type('SupplyMethod')
    target: QuoteProductLine
    dependency_refs: list[ref_type('Dependency')]
    resources: list[SupplierPlannedAllocation]
    planned_inputs: list[SupplierPlannedInput]


class SupplierWorkAuthorityView(CostSource):
    ref: ref_type('SupplyWorkAuthorization')
    organization_id: TextId
    permitted: ValueState[bool]
    order_ref: ref_type('Order') | None
    speculative_authority_ref: ref_type('StockingAuthority') | None
    profile_ref: ref_type('SupplyPlanningProfile')
    permitted_modes: list[Literal['manufacture', 'purchase', 'rework']]
    requirement_refs: list[ref_type('SupplyRequirement')]
    design_refs: list[ref_type('ReleasedDeliverable')]
    method_refs: list[ref_type('SupplyMethod')]
    order_line_refs: list[ref_type('OrderLine')]


class SupplierPlanningOrderView(CostSource):
    ref: ref_type('Order')
    supplier_id: TextId
    buyer_id: TextId
    effective: ValueState[bool]
    line_refs: list[ref_type('OrderLine')]
    core_event_id: TextId


class SupplierStockingAuthorityView(CostSource):
    ref: ref_type('StockingAuthority')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    permitted: ValueState[bool]
    risk_bearer_id: TextId
    requirement_refs: list[ref_type('SupplyRequirement')]


class SupplierPlanningProfileView(CostSource):
    monthly_reliability_policy_ref: ref_type('SupplyReliabilityPolicy') | None = None
    monthly_reliability_observation_ref: ref_type('SupplyReliabilityObservation') | None = None
    monthly_inventory_policy_ref: ref_type('SupplierInventoryPolicy') | None = None
    monthly_inventory_observation_ref: ref_type('SupplierInventoryObservation') | None = None
    ref: ref_type('SupplyPlanningProfile')
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['plan_manufacture', 'plan_purchase', 'split_plan', 'revise_plan', 'request_quote', 'accept_upstream_offer', 'seek_delivery_change']
    plan_ref: ref_type('SupplyPlan') | None
    prior_plan_ref: ref_type('SupplyPlan') | None
    supplier_ids: list[TextId]
    required_lines: list[QuoteProductLine]
    offer_ref: ref_type('SupplyOffer') | None
    offer_line_keys: list[TextId]
    procurement_authority_ref: ref_type('SupplyProcurementAuthority') | None
    affected_line_refs: list[ref_type('OrderLine')]
    proposed_window_ref: ref_type('TimeWindow') | None
    note: TextId


class SupplierSupplyPlanView(GovReviewAuthored):
    ref: ref_type('SupplyPlan')
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    tasks: list[SupplierPlannedTask]
    task_requirement_refs: dict[TextId, list[ref_type('SupplyRequirement')]]
    replaces_plan_ref: ref_type('SupplyPlan') | None
    replacement_commitment_refs: list[ref_type('ResourceCommitment')]
    status: Literal['proposed', 'effective', 'superseded']


class SupplierPlanningRequirementView(CostSource):
    ref: ref_type('SupplyRequirement')
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    purpose: Literal['order_output', 'material']
    target: QuoteProductLine
    permitted: ValueState[bool]
    order_line_ref: ref_type('OrderLine') | None


class SupplierPlanningDesignView(CostSource):
    ref: ref_type('ReleasedDeliverable')
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    requirement_refs: list[ref_type('SupplyRequirement')]
    effective: ValueState[bool]


class SupplierMethodInput(StrictRecord):
    product_ref: ref_type('ProductSpecification')
    unit: TextId
    quantity_per_output: DecimalString
    basis_ref: ref_type('Evidence')


class SupplierPlanningMethodView(CostSource):
    ref: ref_type('SupplyMethod')
    mode: Literal['manufacture', 'purchase', 'rework']
    product_ref: ref_type('ProductSpecification')
    quantity_unit: TextId
    supported: ValueState[bool]
    design_refs: list[ref_type('ReleasedDeliverable')]
    material_inputs: list[SupplierMethodInput]
    resource_kind: TextId | None
    capacity_unit: TextId | None
    quantity_per_capacity_tick: ValueState[DecimalString]
    productivity_basis_ref: ref_type('Evidence')
    procurement_basis_ref: ref_type('Evidence') | None
    purchase_window_ref: ref_type('TimeWindow') | None


class SupplierPlanningResourceView(CostSource):
    ref: ref_type('ResourcePool')
    organization_id: TextId
    region_id: TextId
    resource_kind: TextId


class SupplierInventoryAllocationView(CostSource):
    ref: ref_type('InventoryAllocation')
    organization_id: TextId
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    inventory_ref: ref_type('InventorySnapshot')
    batch_ref: ref_type('ProductBatch')
    product_ref: ref_type('ProductSpecification')
    quantity: Measured
    status: Literal['reserved', 'consumed', 'released']
    core_event_id: TextId


class SupplierPlanningDependencyView(CostSource):
    ref: ref_type('Dependency')
    plan_ref: ref_type('SupplyPlan')
    dependent_task_key: TextId
    predecessor_task_keys: list[TextId]
    requirement_refs: list[ref_type('SupplyRequirement')]


class SupplierPlanningProductView(CostSource):
    ref: ref_type('ProductSpecification')
    quantity_unit: TextId


class SupplierPlanningProductRequirementView(CostSource):
    ref: ref_type('Requirement')
    product_refs: list[ref_type('ProductSpecification')]
    offer_ref: ref_type('SupplyOffer') | None
    satisfied: ValueState[bool]


class SupplierPlanningDeviationView(CostSource):
    ref: ref_type('SpecificationDeviation')
    product_ref: ref_type('ProductSpecification')
    requirement_refs: list[ref_type('Requirement')]
    permitted: ValueState[bool]


class SupplierPlanningOrderLineView(CostSource):
    ref: ref_type('OrderLine')
    order_ref: ref_type('Order')
    product: QuoteProductLine
    delivery_window_ref: ref_type('TimeWindow')
    remaining_quantity: Measured
    as_of: TimePoint


class SupplierProcurementAuthorityView(CostSource):
    ref: ref_type('SupplyProcurementAuthority')
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    permitted: ValueState[bool]
    allowed_payer_ids: list[TextId]
    limit: Money
    used: ValueState[Money]
    commitment_refs: list[ref_type('UpstreamSupplyCommitment')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class SupplierUpstreamCommitmentView(CostSource):
    ref: ref_type('UpstreamSupplyCommitment')
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    organization_id: TextId
    offer_ref: ref_type('SupplyOffer')
    offer_line_keys: list[TextId]
    terms_ref: ref_type('SupplyTerms')
    amount: Money
    status: Literal['submitted', 'pending', 'effective', 'released', 'failed', 'unknown']


class SupplierPlanningCommitmentView(CostSource):
    ref: ref_type('ResourceCommitment')
    plan_ref: ref_type('SupplyPlan')
    organization_id: TextId
    resource_ref: ref_type('ResourcePool')
    quantity: Measured
    window_ref: ref_type('TimeWindow')


def supplier_planning_schemas():
    from src.actions.contracts.supplier_monthly_inventory import SupplierInventoryPolicy, SupplierInventoryObservation
    from src.actions.contracts.supplier_monthly_reliability import SupplyReliabilityPolicy,SupplyReliabilityObservation
    return contractor_bid_schemas({
        'SupplierInventoryPolicy': SupplierInventoryPolicy, 'SupplierInventoryObservation': SupplierInventoryObservation,
        'SupplyReliabilityPolicy':SupplyReliabilityPolicy,'SupplyReliabilityObservation':SupplyReliabilityObservation,
        'SupplyWorkAuthorization': SupplierWorkAuthorityView, 'Order': SupplierPlanningOrderView,
        'StockingAuthority': SupplierStockingAuthorityView, 'SupplyPlanningProfile': SupplierPlanningProfileView,
        'SupplyPlan': SupplierSupplyPlanView, 'SupplyRequirement': SupplierPlanningRequirementView,
        'ReleasedDeliverable': SupplierPlanningDesignView, 'SupplyMethod': SupplierPlanningMethodView,
        'ResourcePool': SupplierPlanningResourceView, 'InventorySnapshot': QuoteInventoryView,
        'SupplierCapacity': QuoteCapacityView, 'InventoryAllocation': SupplierInventoryAllocationView,
        'Dependency': SupplierPlanningDependencyView, 'ProductSpecification': SupplierPlanningProductView,
        'Requirement': SupplierPlanningProductRequirementView, 'SpecificationDeviation': SupplierPlanningDeviationView,
        'OrderLine': SupplierPlanningOrderLineView, 'SupplyOffer': FormationOfferView,
        'SupplyTerms': FormationTermsView, 'SupplyProcurementAuthority': SupplierProcurementAuthorityView,
        'UpstreamSupplyCommitment': SupplierUpstreamCommitmentView,
        'ResourceCommitment': SupplierPlanningCommitmentView,
    })
