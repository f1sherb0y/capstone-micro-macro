"""Shared checks for observed arrival history; never create transport events."""
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.supplier_logistics_objects import (
    SupplierTransportMethodView, SupplierTransportRouteView,
    SupplierTransportTraversalView,
)


def validate_arrival_traversals(shipment, position, *, read, clock, true,
        evidence, needs, unsupported):
    """Require continuous travel, original method validity and real event times.

    read keeps retained sources historical; evidence accepts an explicit at
    point so callers do not impose current validity on original travel.
    """
    if not shipment.traversal_refs:
        needs('original_actual_transport_traversals_before_recorded_arrival', [shipment.ref])
    unique_refs(shipment.traversal_refs)
    location = shipment.plan.source_ref
    tick = shipment.dispatched_at.offset
    travel_events = set()
    unloading = 0
    for traversal_ref in shipment.traversal_refs:
        traversal = read(traversal_ref, SupplierTransportTraversalView, historic=True, linked=True)
        route = read(traversal.route_ref, SupplierTransportRouteView, historic=True, linked=True)
        method = read(route.method_ref, SupplierTransportMethodView, historic=True, linked=True)
        segments = [s for s in route.segments if s.segment_ref == traversal.segment_ref]
        clock(traversal.started_at)
        clock(traversal.completed_at)
        clock(traversal.available_at)
        if (traversal.completed_at.offset > traversal.available_at.offset
                or not traversal.effective_window.contains(traversal.completed_at)):
            raise ValueError('Original traversal source precedes or is invalid at actual completion')
        for source in (route,method):
            clock(source.available_at)
            clock(source.effective_window.start)
            if (source.available_at.offset > traversal.started_at.offset
                    or not source.effective_window.contains(traversal.started_at)):
                raise ValueError('Original traversal uses a route or method unavailable or invalid at departure')
            evidence(source.evidence_refs,at=traversal.started_at)
        if not true(route.supported) or not true(method.supported) or method.clock_ref != shipment.dispatched_at.clock_ref:
            unsupported('original_arrival_elapsed_transport_method_support')
        minimum_start = tick + (method.loading_ticks if location == shipment.plan.source_ref else 0)
        if (traversal.shipment_ref != shipment.ref or len(segments) != 1 or traversal.source_ref != location
                or segments[0].source_ref != traversal.source_ref or segments[0].destination_ref != traversal.destination_ref
                or traversal.started_at.offset < minimum_start or traversal.completed_at.offset > position.observed_at.offset
                or traversal.completed_at.offset - traversal.started_at.offset < segments[0].minimum_ticks
                or traversal.core_event_id in travel_events):
            raise ValueError('Actual route/reroute traversal substitutes original physical position or elapsed travel time')
        evidence(traversal.evidence_refs,at=traversal.completed_at)
        evidence([*method.basis_refs, segments[0].travel_basis_ref],at=traversal.started_at)
        travel_events.add(traversal.core_event_id)
        location = traversal.destination_ref
        tick = traversal.completed_at.offset
        unloading = method.unloading_ticks
    if location != shipment.plan.destination_ref or position.observed_at.offset < tick + unloading:
        raise ValueError('Original recorded arrival skips actual traversal or unloading time')
