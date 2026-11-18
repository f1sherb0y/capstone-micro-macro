"""Original physical dispatch slices and transport schedules; no stock movement."""
from typing import Literal
from pydantic import Field

from src.actions.contracts.common import Measured, Reference, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView


class SupplierTransportSourceView(CostSource):
    ref: Reference


class SupplierShipmentPlan(StrictRecord):
    batch_ref: ref_type('ProductBatch')
    quantity: Measured
    source_ref: ref_type('Location')
    destination_ref: ref_type('Location')
    route_ref: ref_type('TransportRoute')
    receiving_window_ref: ref_type('TimeWindow')
    transport_allocation_refs: list[ref_type('ResourceAllocation')]
    condition_evidence_refs: list[ref_type('Evidence')]


class SupplierLogisticsOrderView(CostSource):
    ref: ref_type('Order')
    supplier_id: TextId
    buyer_id: TextId
    effective: ValueState[bool]
    line_refs: list[ref_type('OrderLine')]
    terms_ref: ref_type('TransportTerms')
    shipment_refs: list[ref_type('Shipment')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class SupplierLogisticsOrderLineView(CostSource):
    ref: ref_type('OrderLine')
    order_ref: ref_type('Order')
    product_ref: ref_type('ProductSpecification')
    destination_ref: ref_type('Location')
    remaining_to_dispatch: Measured


class SupplierTransportTermsView(CostSource):
    ref: ref_type('TransportTerms')
    order_ref: ref_type('Order')
    supplier_id: TextId
    buyer_id: TextId
    risk_transfer_event: Literal['dispatch', 'carrier_receipt', 'arrival', 'customer_receipt', 'acceptance']
    title_transfer_event: Literal['dispatch', 'arrival', 'customer_receipt', 'payment', 'acceptance']
    transport_requirement_refs: list[ref_type('TransportRequirement')]


class SupplierDispatchableView(CostSource):
    ref: ref_type('DispatchableBatch')
    order_ref: ref_type('Order')
    line_ref: ref_type('OrderLine')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    product_ref: ref_type('ProductSpecification')
    source_ref: ref_type('Location')
    actual_remaining: Measured
    dispatchable_quantity: Measured
    release_ref: ref_type('DispatchRelease')
    ledger_ref: ref_type('DispatchLedger')
    as_of: TimePoint


class SupplierDispatchReleaseView(CostSource):
    ref: ref_type('DispatchRelease')
    batch_ref: ref_type('ProductBatch')
    physical_batch_key: TextId
    order_ref: ref_type('Order')
    quantity: Measured
    permitted: ValueState[bool]
    core_event_id: TextId


class SupplierDispatchLedgerView(CostSource):
    ref: ref_type('DispatchLedger')
    physical_batch_key: TextId
    original_dispatchable: Measured
    actual_remaining: Measured
    other_outflow: Measured
    pending_quantity: Measured
    shipment_refs: list[ref_type('Shipment')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    producer: Literal['core']


class SupplierShipmentSliceView(CostSource):
    ref: ref_type('ShipmentSlice')
    dispatchable_ref: ref_type('DispatchableBatch')
    physical_slice_key: TextId
    quantity: Measured


class SupplierLogisticsProfileView(CostSource):
    ref: ref_type('LogisticsProfile')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    order_ref: ref_type('Order')
    choice: Literal['dispatch', 'split', 'reroute', 'reschedule', 'reconcile']
    plans: list[SupplierShipmentPlan]
    plan_slice_refs: list[list[ref_type('ShipmentSlice')]]
    shipment_ref: ref_type('Shipment') | None
    replacement_route_ref: ref_type('TransportRoute') | None
    current_position_ref: ref_type('TransportPosition') | None
    replacement_allocation_refs: list[ref_type('ResourceAllocation')]
    target_kind: Literal['order_lines', 'shipments'] | None
    target_line_refs: list[ref_type('OrderLine')]
    target_shipment_refs: list[ref_type('Shipment')]
    proposed_window_ref: ref_type('TimeWindow') | None
    note: TextId


class SupplierReceivingWindowView(GovReviewAuthored):
    ref: ref_type('ReceivingWindow')
    order_ref: ref_type('Order')
    receiver_id: TextId
    destination_ref: ref_type('Location')
    window_ref: ref_type('TimeWindow')
    available: ValueState[bool]


class SupplierRouteSegment(StrictRecord):
    segment_ref: ref_type('TransportSegment')
    source_ref: ref_type('Location')
    destination_ref: ref_type('Location')
    minimum_ticks: int = Field(ge=1)
    travel_basis_ref: ref_type('Evidence')


class SupplierTransportRouteView(CostSource):
    ref: ref_type('TransportRoute')
    supported: ValueState[bool]
    segments: list[SupplierRouteSegment]
    requirement_refs: list[ref_type('TransportRequirement')]
    method_ref: ref_type('TransportMethod')


class SupplierTransportMethodView(CostSource):
    ref: ref_type('TransportMethod')
    supported: ValueState[bool]
    clock_ref: ref_type('ClockProfile')
    quantity_unit: TextId
    loading_ticks: int = Field(ge=0)
    unloading_ticks: int = Field(ge=0)
    basis_refs: list[ref_type('Evidence')]


class SupplierTransportRequirementView(CostSource):
    ref: ref_type('TransportRequirement')
    order_ref: ref_type('Order')
    route_refs: list[ref_type('TransportRoute')]
    satisfied: ValueState[bool]
    condition_evidence_refs: list[ref_type('Evidence')]


class SupplierTransportAllocationView(CostSource):
    ref: ref_type('ResourceAllocation')
    organization_id: TextId
    order_ref: ref_type('Order')
    capacity_ref: ref_type('TransportCapacity')
    segment_ref: ref_type('TransportSegment')
    quantity: Measured
    window: TimeWindow
    status: Literal['reserved', 'released', 'consumed', 'unknown']
    reservation_ref: ref_type('TransportReservation')


class SupplierTransportReservationView(CostSource):
    ref: ref_type('TransportReservation')
    allocation_ref: ref_type('ResourceAllocation')
    capacity_ref: ref_type('TransportCapacity')
    segment_ref: ref_type('TransportSegment')
    quantity: Measured
    window: TimeWindow
    core_event_id: TextId
    status: Literal['reserved', 'released', 'consumed']


class SupplierTransportCapacityView(CostSource):
    ref: ref_type('TransportCapacity')
    physical_pool_key: TextId
    segment_ref: ref_type('TransportSegment')
    actual_capacity: Measured
    actually_available: ValueState[bool]
    reservation_refs: list[ref_type('TransportReservation')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class SupplierShipmentView(CostSource):
    ref: ref_type('Shipment')
    order_ref: ref_type('Order')
    organization_id: TextId
    run_id: TextId
    operation_id: TextId
    command_id: TextId
    business_key: TextId
    physical_batch_key: TextId
    slice_refs: list[ref_type('ShipmentSlice')]
    plan: SupplierShipmentPlan
    request_sha256: Digest
    status: Literal['submitted_unknown', 'dispatched', 'in_transit', 'arrived', 'received', 'rejected', 'failed']
    query_status: Literal['present', 'absent', 'unknown', 'not_queried']
    core_event_id: TextId | None
    dispatched_at: TimePoint | None
    current_position_ref: ref_type('TransportPosition') | None
    traversal_refs: list[ref_type('TransportTraversal')]


class SupplierTransportTraversalView(CostSource):
    ref: ref_type('TransportTraversal')
    shipment_ref: ref_type('Shipment')
    route_ref: ref_type('TransportRoute')
    segment_ref: ref_type('TransportSegment')
    source_ref: ref_type('Location')
    destination_ref: ref_type('Location')
    started_at: TimePoint
    completed_at: TimePoint
    core_event_id: TextId
    producer: Literal['core']


class SupplierTransportPositionView(CostSource):
    ref: ref_type('TransportPosition')
    shipment_ref: ref_type('Shipment')
    location_ref: ref_type('Location')
    position_kind: Literal['source', 'in_transit', 'destination', 'received', 'damaged', 'held']
    remaining_quantity: Measured
    observed_at: TimePoint
    core_event_id: TextId
    producer: Literal['core']


def supplier_logistics_schemas():
    return contractor_bid_schemas({
        'Order': SupplierLogisticsOrderView, 'OrderLine': SupplierLogisticsOrderLineView,
        'TransportTerms': SupplierTransportTermsView, 'DispatchableBatch': SupplierDispatchableView,
        'DispatchRelease': SupplierDispatchReleaseView, 'DispatchLedger': SupplierDispatchLedgerView,
        'ShipmentSlice': SupplierShipmentSliceView, 'LogisticsProfile': SupplierLogisticsProfileView,
        'ReceivingWindow': SupplierReceivingWindowView, 'TransportRoute': SupplierTransportRouteView,
        'TransportMethod': SupplierTransportMethodView, 'TransportRequirement': SupplierTransportRequirementView,
        'ResourceAllocation': SupplierTransportAllocationView, 'TransportReservation': SupplierTransportReservationView,
        'TransportCapacity': SupplierTransportCapacityView, 'Shipment': SupplierShipmentView,
        'TransportPosition': SupplierTransportPositionView,
        'TransportTraversal': SupplierTransportTraversalView,
        'Location': SupplierTransportSourceView, 'TransportSegment': SupplierTransportSourceView,
        'ProductBatch': SupplierQualityBatchView,
    })
