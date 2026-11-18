"""SUPPLIER-A08 schedules physical transport and queries original stock dispatch."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.supplier_logistics_objects import (
    SupplierLogisticsOrderView, SupplierLogisticsOrderLineView, SupplierTransportTermsView,
    SupplierDispatchableView, SupplierDispatchReleaseView, SupplierDispatchLedgerView,
    SupplierShipmentSliceView, SupplierLogisticsProfileView, SupplierReceivingWindowView,
    SupplierTransportRouteView, SupplierTransportMethodView, SupplierTransportRequirementView,
    SupplierTransportAllocationView, SupplierTransportReservationView, SupplierTransportCapacityView,
    SupplierShipmentView, SupplierTransportPositionView,
    SupplierQualityBatchView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.actions.roles.supplier_transport_history import validate_arrival_traversals
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def arrange_transport(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('supplier-logistics-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:_needs('received_original_transport_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):
                _unsupported('supplier-logistics-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if row.effective_window.start.offset > now.offset:_needs('received_original_transport_evidence',[ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_transport_evidence_valid_at_use',[ref])

    def read(ref,schema,historic=False,linked=False,*,evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row,schema):_unsupported('supplier-logistics-projection:' + ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Transport source widens original authorized scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:_needs('received_original_transport_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):_needs('current_original_transport_source',[ref])
        point = None if evidence_at_field is None else getattr(row,evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > now.offset:_needs('received_original_transport_evidence_time',[ref])
            if point.offset > row.available_at.offset:raise ValueError('Transport source precedes its actual observation or authorship')
        evidence(getattr(row,'evidence_refs',[]),at=point,historic=historic)
        return row

    def true(value):return isinstance(value,Known) and value.value is True

    def q(value,unit=None,positive=False,*,at=None,historic=False):
        evidence([value.basis_ref],at=at,historic=historic);result = decimal_fraction(value.value)
        if unit is not None and value.unit != unit or result < 0 or positive and result == 0:
            raise ValueError('Transport quantity changes original unit or physical positive amount')
        return result

    def window(value):
        clock(value.start);clock(value.end)
        if value.bounds != 'closed_open':_unsupported('transport-half-open-window-domain')
        return value

    def authorize(ref,actor,function,organization,action,at,target):
        grant = read(ref,Authorization,historic=True,linked=True)
        assignment = read(function,RoleAssignment,historic=True,linked=True)
        roles = {'SUPPLIER':'Supplier','CONTRACTOR':'Contractor','OWN':'Owner','GOV':'Government'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Transport source substitutes actual independent actor/function/scope authority')
        clock(at);clock(grant.validity.start)
        if at.offset > now.offset:_needs('received_original_transport_author_time',[ref])
        if not grant.validity.contains(at):_needs('original_transport_authority_at_execution',[ref])
        for ref in [*grant.basis_refs,*assignment.basis_refs]:
            if ref.kind == 'Evidence':evidence([ref],at=at)
            else:reading.resolve(ref)

    def complete(choice,**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,**fields,'note':profile.note +
            ' Request/query only. Core records dispatch, transit and arrival once using elapsed clock time. Risk transfers at '+terms.risk_transfer_event+
            '; title transfers at '+terms.title_transfer_event+'. No destination stock, receipt or use approval is created by dispatch.'}}

    def wait(code,refs):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':refs,'earliest_time':None,'condition_code':code}}

    def position(shipment):
        if shipment.current_position_ref is None or shipment.current_position_ref.key() not in keys(action_input.position_refs):
            _needs('original_visible_core_transport_position',[shipment.ref])
        row = read(shipment.current_position_ref,SupplierTransportPositionView,historic=True,linked=True,evidence_at_field='observed_at')
        clock(row.observed_at)
        if (row.shipment_ref != shipment.ref or row.observed_at.offset > now.offset
                or not row.effective_window.contains(row.observed_at)
                or q(row.remaining_quantity,shipment.plan.quantity.unit,at=row.observed_at) > q(shipment.plan.quantity,historic=True)):
            raise ValueError('Transport position substitutes original shipment/time or remaining physical quantity')
        return row

    def receiving_window(window_ref,destination):
        matches = [read(r,SupplierReceivingWindowView,linked=True,evidence_at_field='authored_at') for r in action_input.receiving_window_refs]
        matches = [r for r in matches if r.window_ref == window_ref and r.destination_ref == destination]
        if len(matches) != 1 or matches[0].order_ref != order.ref or matches[0].receiver_id != order.buyer_id or not true(matches[0].available):
            _needs('actual_independent_receiver_available_window_for_dispatch')
        receiver = matches[0];clock(receiver.authored_at)
        if receiver.authored_at.offset > receiver.available_at.offset or not receiver.effective_window.contains(receiver.authored_at):
            raise ValueError('Receiving availability predates original receiver statement or original effective authority')
        authorize(receiver.author_authority_ref,receiver.author_actor_id,receiver.author_function_ref,
            receiver.author_organization_id,receiver.author_action_id,receiver.authored_at,receiver.scope)
        if receiver.author_organization_id != order.buyer_id:raise ValueError('Supplier cannot substitute buyer receiving authority')
        return window(read(window_ref,TimeWindow))

    def route_schedule(route_ref,source,destination,alloc_refs,quantity,earliest,receiving=None):
        if route_ref.key() not in keys(action_input.route_candidates):
            raise ValueError('Transport request selects an unreceived route')
        route = read(route_ref,SupplierTransportRouteView,linked=True)
        method = read(route.method_ref,SupplierTransportMethodView,linked=True)
        if not true(route.supported) or not true(method.supported) or method.clock_ref != now.clock_ref or not route.segments:
            _unsupported('original_transport_route_and_elapsed_time_method_support')
        unit = quantity.unit;q(quantity,method.quantity_unit,positive=True);evidence(method.basis_refs)
        keys([s.segment_ref for s in route.segments]);keys(alloc_refs)
        requirements = keys(route.requirement_refs) | keys(terms.transport_requirement_refs)
        if not requirements <= keys(action_input.requirement_refs):_needs('complete_original_route_and_order_transport_conditions')
        condition_refs = {}
        for ref in [*route.requirement_refs,*terms.transport_requirement_refs]:
            req = read(ref,SupplierTransportRequirementView,linked=True)
            if req.order_ref != order.ref or route.ref.key() not in keys(req.route_refs) or not true(req.satisfied):
                _needs('actual_current_original_transport_condition',[ref])
            evidence(req.condition_evidence_refs)
            condition_refs.update({r.key():r for r in req.condition_evidence_refs})
        allocations = [read(ref,SupplierTransportAllocationView,linked=True) for ref in alloc_refs]
        by_segment = {}
        for allocation in allocations:
            if allocation.segment_ref.key() in by_segment:raise ValueError('Route repeats a physical shared segment allocation')
            by_segment[allocation.segment_ref.key()] = allocation
        if set(by_segment) != keys([s.segment_ref for s in route.segments]):
            _needs('exact_original_transport_allocation_for_each_route_segment')
        location = source;tick = earliest + method.loading_ticks
        for segment in route.segments:
            if segment.source_ref != location:raise ValueError('Transport route jumps from actual original position')
            evidence([segment.travel_basis_ref]);allocation = by_segment[segment.segment_ref.key()]
            occupied = window(allocation.window)
            if (allocation.organization_id != org or allocation.order_ref != order.ref or allocation.status != 'reserved'
                    or allocation.capacity_ref.key() not in keys(action_input.capacity_refs)
                    or q(allocation.quantity,unit,positive=True) < q(quantity)):
                _needs('original_reserved_transport_allocation_for_physical_cargo',[allocation.ref])
            if occupied.start.offset < tick or occupied.end.offset - occupied.start.offset < segment.minimum_ticks:
                _needs('elapsed_transport_loading_and_segment_time_before_arrival')
            tick = occupied.end.offset;location = segment.destination_ref
        if location != destination:raise ValueError('Transport route does not reach original order destination')
        tick += method.unloading_ticks
        if receiving is not None and not receiving.contains(now.model_copy(update={'offset':tick})):
            _needs('actual_receiving_window_after_elapsed_transport_and_unloading')
        return allocations,condition_refs

    def capacity_check(allocations,cargo):
        pools = {};physical = {};events = set()
        for allocation in allocations.values():
            if allocation.capacity_ref.key() not in pools:
                pool = read(allocation.capacity_ref,SupplierTransportCapacityView,linked=True);clock(pool.as_of)
                if pool.as_of != now or pool.coverage != 'complete' or not true(pool.actually_available):
                    _needs('complete_current_actual_transport_capacity',[pool.ref])
                if pool.physical_pool_key in physical and physical[pool.physical_pool_key] != pool.ref.key():
                    raise ValueError('Transport capacity aliases the same shared physical pool')
                physical[pool.physical_pool_key] = pool.ref.key();pools[pool.ref.key()] = pool
            pool = pools[allocation.capacity_ref.key()]
            if pool.segment_ref != allocation.segment_ref:raise ValueError('Transport allocation changes original shared segment')
            if cargo[allocation.ref.key()] > q(allocation.quantity,pool.actual_capacity.unit):
                _needs('shared_transport_allocation_capacity_for_all_unique_cargo_slices')
        for pool in pools.values():
            reservations = [];keys(pool.reservation_refs)
            for ref in pool.reservation_refs:
                row = read(ref,SupplierTransportReservationView,linked=True);window(row.window)
                if row.capacity_ref != pool.ref or row.segment_ref != pool.segment_ref or row.core_event_id in events:
                    raise ValueError('Transport reservations repeat original core event or physical shared segment')
                events.add(row.core_event_id);q(row.quantity,pool.actual_capacity.unit);reservations.append(row)
            for allocation in [a for a in allocations.values() if a.capacity_ref == pool.ref]:
                bound = [r for r in reservations if r.ref == allocation.reservation_ref]
                if (len(bound) != 1 or bound[0].allocation_ref != allocation.ref or bound[0].quantity != allocation.quantity
                        or bound[0].window != allocation.window or bound[0].status != 'reserved'):
                    raise ValueError('Transport allocation lacks original exclusive core reservation')
            boundaries = sorted({t for r in reservations if r.status == 'reserved' for t in [r.window.start.offset,r.window.end.offset]})
            for tick in boundaries[:-1]:
                total = sum((decimal_fraction(r.quantity.value) for r in reservations if r.status == 'reserved'
                    and r.window.start.offset <= tick < r.window.end.offset),Fraction(0))
                if total > q(pool.actual_capacity):_needs('actual_shared_transport_pool_concurrent_capacity')

    try:
        profile = read(action_input.logistics_profile_ref,SupplierLogisticsProfileView)
        order = read(action_input.order_ref,SupplierLogisticsOrderView,historic=profile.choice == 'reconcile',linked=True)
        terms = read(order.terms_ref,SupplierTransportTermsView,historic=profile.choice == 'reconcile',linked=True)
        if (order.supplier_id != org or not scope_covers(order.scope,scope) or profile.order_ref != order.ref
                or profile.organization_id != org or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                or profile.scope != scope or profile.authority_ref not in context.authorization_refs
                or terms.order_ref != order.ref or terms.supplier_id != org or terms.buyer_id != order.buyer_id):
            raise ValueError('Logistics changes original effective order, parties, terms or invocation authority')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,org,'SUPPLIER-A08',now,scope)
        for field in ('dispatchable_refs','receiving_window_refs','route_candidates','capacity_refs','requirement_refs','shipment_refs','position_refs'):
            keys(getattr(action_input,field))
        clock(order.as_of)
        if order.as_of != now or order.coverage != 'complete' or keys(order.shipment_refs) != keys(action_input.shipment_refs):
            _needs('complete_current_original_order_shipment_history')
        history = {};commands = set();business = set();events = set();past_slices = set()
        for ref in action_input.shipment_refs:
            row = read(ref,SupplierShipmentView,historic=True,linked=True)
            if (row.order_ref != order.ref or row.organization_id != org or row.run_id != context.run_id
                    or row.command_id in commands or row.business_key in business or content_digest(row.plan) != row.request_sha256):
                raise ValueError('Shipment history repeats or substitutes original command/business/request content')
            commands.add(row.command_id);business.add(row.business_key);keys(row.slice_refs)
            for slice_ref in row.slice_refs:
                original = read(slice_ref,SupplierShipmentSliceView,historic=True,linked=True)
                original_batch = read(original.dispatchable_ref,SupplierDispatchableView,historic=True,linked=True)
                if original_batch.batch_ref != row.plan.batch_ref or original_batch.physical_batch_key != row.physical_batch_key:
                    raise ValueError('Shipment history changes original batch lineage of physical slices')
                if row.status not in {'rejected','failed'}:
                    if original.physical_slice_key in past_slices:raise ValueError('Shipments dispatch the same original physical cargo slice twice')
                    past_slices.add(original.physical_slice_key)
            if not row.slice_refs or sum((q(read(r,SupplierShipmentSliceView,historic=True,linked=True).quantity,row.plan.quantity.unit,historic=True)
                    for r in row.slice_refs),Fraction(0)) != q(row.plan.quantity,positive=True,historic=True):
                raise ValueError('Original shipment content differs from physical slice quantity')
            if row.status in {'dispatched','in_transit','arrived','received'}:
                if row.query_status != 'present' or row.core_event_id is None or row.dispatched_at is None or row.core_event_id in events:
                    raise ValueError('Physical shipment requires original distinct core dispatch event')
                clock(row.dispatched_at);events.add(row.core_event_id)
                if row.dispatched_at.offset > row.available_at.offset:raise ValueError('Shipment source precedes its actual dispatch')
                q(row.plan.quantity,positive=True,at=row.dispatched_at)
                for slice_ref in row.slice_refs:
                    cargo = read(slice_ref,SupplierShipmentSliceView,historic=True,linked=True)
                    q(cargo.quantity,row.plan.quantity.unit,at=row.dispatched_at)
                current = position(row)
                if current.observed_at.offset < row.dispatched_at.offset:
                    raise ValueError('Transport position predates original dispatch')
                if row.status in {'arrived','received'} and current.location_ref != row.plan.destination_ref:
                    raise ValueError('Recorded arrival replaces original physical destination')
                if row.status in {'arrived','received'}:
                    validate_arrival_traversals(row,current,read=read,clock=clock,true=true,
                        evidence=evidence,needs=_needs,unsupported=_unsupported)
            elif row.core_event_id is not None or row.dispatched_at is not None:
                raise ValueError('Unrecorded shipment invents physical dispatch')
            history[ref.key()] = row
        if profile.choice == 'reconcile':
            if not history:_needs('original_existing_shipments_for_query')
            return complete('reconcile',shipment_refs=action_input.shipment_refs)
        unresolved = [r.ref for r in history.values() if r.status == 'submitted_unknown' or r.query_status in {'unknown','not_queried'}]
        if unresolved:return complete('reconcile',shipment_refs=unresolved)
        existing = [r.ref for r in history.values() if r.operation_id == context.operation_id]
        if existing:return wait('continue_original_transport_operation',existing)
        if not true(order.effective):_needs('original_effective_order_for_new_transport_request')

        if profile.choice == 'reschedule':
            if profile.proposed_window_ref is None:_needs('original_proposed_delivery_window')
            proposed = window(read(profile.proposed_window_ref,TimeWindow))
            if proposed.start.offset < now.offset:raise ValueError('Proposed transport reschedule precedes actual request')
            if profile.target_kind == 'order_lines':
                if not profile.target_line_refs or profile.target_shipment_refs or not keys(profile.target_line_refs) <= keys(order.line_refs):
                    raise ValueError('Unshipped reschedule requires original order-line target')
                for ref in profile.target_line_refs:
                    line = read(ref,SupplierLogisticsOrderLineView)
                    if line.order_ref != order.ref:raise ValueError('Reschedule replaces original order line')
                target = {'kind':'order_lines','line_refs':profile.target_line_refs}
            elif profile.target_kind == 'shipments':
                if not profile.target_shipment_refs or profile.target_line_refs or not keys(profile.target_shipment_refs) <= set(history):
                    raise ValueError('Shipment reschedule requires original existing shipment targets')
                for ref in profile.target_shipment_refs:position(history[ref.key()])
                target = {'kind':'shipments','shipment_refs':profile.target_shipment_refs}
            else:_needs('explicit_original_reschedule_target')
            return complete('reschedule',target=target,proposed_window_ref=profile.proposed_window_ref)

        if profile.choice == 'reroute':
            if (profile.shipment_ref is None or profile.shipment_ref.key() not in history or profile.replacement_route_ref is None
                    or profile.current_position_ref is None or profile.current_position_ref.key() not in keys(action_input.position_refs)):
                _needs('original_shipment_current_position_and_replacement_route')
            shipment = history[profile.shipment_ref.key()];current = position(shipment)
            if (shipment.current_position_ref != profile.current_position_ref or shipment.status not in {'dispatched','in_transit'}
                    or current.position_kind not in {'source','in_transit','held','damaged'} or current.observed_at != now):
                _needs('current_actual_in_transit_position_for_original_reroute')
            receiving = receiving_window(shipment.plan.receiving_window_ref,shipment.plan.destination_ref)
            allocations,_ = route_schedule(profile.replacement_route_ref,current.location_ref,shipment.plan.destination_ref,
                profile.replacement_allocation_refs,current.remaining_quantity,now.offset,receiving)
            capacity_check({a.ref.key():a for a in allocations},{a.ref.key():q(current.remaining_quantity) for a in allocations})
            return complete('reroute',shipment_ref=shipment.ref,replacement_route_ref=profile.replacement_route_ref,current_position_ref=current.ref)

        if profile.choice not in {'dispatch','split'} or not profile.plans or len(profile.plans) != len(profile.plan_slice_refs):
            _needs('original_concrete_shipment_plans_and_physical_slices')
        if profile.choice == 'split' and len(profile.plans) < 2:raise ValueError('Split dispatch requires multiple explicit physical plans')
        dispatchables = {ref.key():read(ref,SupplierDispatchableView) for ref in action_input.dispatchable_refs}
        if not dispatchables:_needs('original_actual_dispatchable_physical_stock')
        lines = {};batch_used = {};line_used = {};slices = set();allocations = {};cargo = {};batch_keys = set()
        for row in dispatchables.values():
            clock(row.as_of)
            if row.order_ref != order.ref or row.line_ref.key() not in keys(order.line_refs) or row.as_of != now or row.physical_batch_key in batch_keys:
                raise ValueError('Dispatchable batch aliases physical stock or changes original order/snapshot')
            batch_keys.add(row.physical_batch_key)
            line = read(row.line_ref,SupplierLogisticsOrderLineView);lines[row.line_ref.key()] = line
            release = read(row.release_ref,SupplierDispatchReleaseView)
            actual_batch = read(row.batch_ref,SupplierQualityBatchView,linked=True)
            ledger = read(row.ledger_ref,SupplierDispatchLedgerView,linked=True);clock(ledger.as_of)
            if (line.order_ref != order.ref or row.product_ref != line.product_ref or release.batch_ref != row.batch_ref
                    or actual_batch.organization_id != org or actual_batch.physical_batch_key != row.physical_batch_key
                    or actual_batch.product_ref != row.product_ref or actual_batch.as_of != now
                    or release.physical_batch_key != row.physical_batch_key or release.order_ref != order.ref or not true(release.permitted)
                    or ledger.physical_batch_key != row.physical_batch_key or ledger.coverage != 'complete' or ledger.as_of != now
                    or not keys(ledger.shipment_refs) <= set(history)):
                _needs('original_core_dispatch_release_and_complete_physical_stock_ledger')
            relevant = [r for r in history.values() if r.physical_batch_key == row.physical_batch_key]
            if keys(ledger.shipment_refs) != keys([r.ref for r in relevant]):raise ValueError('Dispatch ledger drops original stock dispatch history')
            sent = sum((q(r.plan.quantity,row.actual_remaining.unit,at=r.dispatched_at) for r in relevant if r.status in {'dispatched','in_transit','arrived','received'}),Fraction(0))
            pending = sum((q(r.plan.quantity,row.actual_remaining.unit,historic=True) for r in relevant if r.status == 'submitted_unknown'),Fraction(0))
            unit = row.actual_remaining.unit
            if (q(ledger.original_dispatchable,unit) - sent - q(ledger.other_outflow,unit) != q(ledger.actual_remaining,unit)
                    or q(ledger.actual_remaining,unit) != q(row.actual_remaining,unit) or q(actual_batch.actual_quantity,unit) != q(row.actual_remaining,unit)
                    or pending != q(ledger.pending_quantity,unit) or q(row.dispatchable_quantity,unit) > min(q(row.actual_remaining,unit),q(release.quantity,unit))):
                raise ValueError('Dispatch ledger restores original shipped physical stock or exceeds actual released quantity')
        for plan,refs in zip(profile.plans,profile.plan_slice_refs):
            keys(refs);quantity = q(plan.quantity,positive=True);slice_quantity = Fraction(0)
            if not refs:raise ValueError('Shipment plan omits original physical cargo slice partition')
            for ref in refs:
                original = read(ref,SupplierShipmentSliceView)
                if original.dispatchable_ref.key() not in dispatchables or original.physical_slice_key in slices | past_slices:
                    raise ValueError('Shipment plan repeats already dispatched physical slice or invents dispatchable stock')
                row = dispatchables[original.dispatchable_ref.key()];line = lines[row.line_ref.key()]
                if (plan.batch_ref != row.batch_ref or plan.source_ref != row.source_ref or plan.destination_ref != line.destination_ref
                        or plan.quantity.unit != row.actual_remaining.unit or plan.quantity.unit != line.remaining_to_dispatch.unit):
                    raise ValueError('Shipment plan replaces original batch/source/order destination')
                amount = q(original.quantity,plan.quantity.unit,positive=True);slice_quantity += amount;slices.add(original.physical_slice_key)
                batch_used[row.ref.key()] = batch_used.get(row.ref.key(),Fraction(0)) + amount
                line_used[line.ref.key()] = line_used.get(line.ref.key(),Fraction(0)) + amount
                if batch_used[row.ref.key()] > q(row.dispatchable_quantity) or line_used[line.ref.key()] > q(line.remaining_to_dispatch):
                    raise ValueError('Split shipments duplicate batch quantity or exceed original unshipped order remainder')
            if slice_quantity != quantity:raise ValueError('Shipment quantity differs from original physical slice partition')
            receiving = receiving_window(plan.receiving_window_ref,plan.destination_ref)
            selected,conditions = route_schedule(plan.route_ref,plan.source_ref,plan.destination_ref,plan.transport_allocation_refs,
                plan.quantity,now.offset,receiving)
            evidence(plan.condition_evidence_refs)
            if not set(conditions) <= keys(plan.condition_evidence_refs):raise ValueError('Dispatch plan drops original route/permit/customs evidence')
            for allocation in selected:
                allocations[allocation.ref.key()] = allocation
                cargo[allocation.ref.key()] = cargo.get(allocation.ref.key(),Fraction(0)) + quantity
        capacity_check(allocations,cargo)
        return complete(profile.choice,plans=[p.model_dump(mode='python') for p in profile.plans])
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
