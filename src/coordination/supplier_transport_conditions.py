"""Recompute the original Supplier A08 transport wait without issuing cargo again."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_logistics_objects import (
    SupplierDispatchableView, SupplierLogisticsProfileView, SupplierShipmentSliceView, SupplierShipmentView,
    SupplierTransportMethodView, SupplierTransportPositionView, SupplierTransportRouteView, SupplierTransportTraversalView,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.supplier_transport_history import validate_arrival_traversals


@dataclass(frozen=True)
class SupplierTransportConditionReading:
    context: ActionContext
    reading: ActionReadView
    shipment_refs: tuple[Reference, ...]
    logistics_profile_ref: Reference


def check_supplier_query_selection(selected):
    """Require a separately authorized current reconciliation profile."""
    if (not isinstance(selected, SupplierTransportConditionReading)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.shipment_refs, tuple)
            or any(not isinstance(ref, Reference) for ref in selected.shipment_refs)
            or not isinstance(selected.logistics_profile_ref, Reference)):
        raise TaskConflict('Supplier wait requires typed current shipment and reconciliation-profile sources')
    context, reading = selected.context, selected.reading
    reading.check_method_context(context, 'SUPPLIER-A08')
    profile = reading.resolve(selected.logistics_profile_ref)
    if (context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
            or not isinstance(profile, SupplierLogisticsProfileView) or profile.ref != selected.logistics_profile_ref
            or profile.organization_id != reading.organization_id or profile.actor_id != context.actor_id
            or profile.function_ref != context.function_ref or profile.authority_ref not in context.authorization_refs
            or profile.choice != 'reconcile' or profile.scope != context.scope
            or profile.available_at.clock_ref != context.business_time.clock_ref
            or profile.available_at.offset > context.business_time.offset or not profile.effective_window.contains(context.business_time)):
        raise TaskConflict('Supplier continuation requires current own reconciliation authority, never a new dispatch choice')
    return profile


def supplier_original_transport_profile(read_current, validate_relation):
    """Bind continue_original_transport_operation to authentic current query history.

    The reader supplies old/current shipments and a new reconcile profile.
    Native validation authenticates original dispatch and complete stock/slice,
    position and traversal history. Event data alone never establishes arrival,
    ownership transfer, usable destination stock or a right to dispatch again.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supplier wait requires independent current reader and native transport-history validator')
    code = 'continue_original_transport_operation'

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'SUPPLIER-A08' or source['role'] != 'Supplier' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)
                or any(ref.kind != 'Shipment' for ref in old_refs)):
            raise TaskConflict('Supplier wait changes original task, recipient or shipment dependencies')
        selected = read_current(deepcopy(check))
        profile = check_supplier_query_selection(selected)
        context, reading, refs = selected.context.model_copy(deep=True), selected.reading, selected.shipment_refs
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or len(refs) != len(old_refs) or len(set(refs)) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}):
            raise TaskConflict('Supplier wait substitutes current read point or original physical shipments')
        now = context.business_time
        current_refs = {(ref.kind, ref.id): ref for ref in refs}
        originals, currents, related, observed = [], [], {}, {}
        commands, businesses, core_events, physical_slices = set(), set(), set(), set()

        def available(row, *, historic=False):
            return (row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                and row.effective_window.start.clock_ref == now.clock_ref
                and row.effective_window.start.offset <= now.offset
                and (historic or row.effective_window.contains(now)))

        def evidence(ref, *, at=None, historic=False):
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Supplier transport query requires independent actual observed evidence')
            point = now if at is None else at
            if point.clock_ref != now.clock_ref or point.offset > now.offset:
                return False
            if row.effective_window is not None and (
                    row.effective_window.start.clock_ref != now.clock_ref
                    or row.effective_window.start.offset > now.offset
                    or (at is not None or not historic) and not row.effective_window.contains(point)):
                return False
            observed[ref.key()] = row.model_dump(mode='json')
            return True

        def transport_clock(point):
            if point.clock_ref != now.clock_ref:
                _unsupported('supplier-logistics-clock-alignment')

        def transport_evidence(refs, *, at=None, historic=False):
            for ref in refs:
                if not evidence(ref,at=at,historic=historic):
                    _needs('original_transport_history_evidence_valid_at_use', [ref])

        def transport_read(ref, schema, *, historic=False, linked=False):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise TaskConflict('Supplier arrival query substitutes its exact typed transport source')
            transport_clock(row.available_at)
            transport_clock(row.effective_window.start)
            transport_clock(row.effective_window.end)
            if row.available_at.offset > now.offset or not historic and not row.effective_window.contains(now):
                _needs('received_original_transport_history_source', [ref])
            transport_evidence(row.evidence_refs,historic=historic)
            related[ref.key()] = row.model_dump(mode='json')
            return row

        try:
            for ref in profile.evidence_refs:
                if not evidence(ref):
                    return 'unavailable'
            for old_ref in old_refs:
                current_ref = current_refs[(old_ref.kind, old_ref.id)]
                original, current = reading.resolve(old_ref), reading.resolve(current_ref)
                if (not isinstance(original, SupplierShipmentView) or not isinstance(current, SupplierShipmentView)
                        or original.ref != old_ref or current.ref != current_ref
                        or current.run_id != source['run_id'] or current.organization_id != source['organization_id']
                        or current.order_ref != profile.order_ref
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'order_ref', 'organization_id', 'run_id', 'operation_id', 'command_id', 'business_key',
                            'physical_batch_key', 'slice_refs', 'plan', 'request_sha256', 'scope'))
                        or task_digest(current.plan.model_dump(mode='json')) != current.request_sha256
                        or current.command_id in commands or current.business_key in businesses):
                    raise TaskConflict('Supplier query changes original command, order, physical batch/slices or exact transport plan')
                commands.add(current.command_id); businesses.add(current.business_key)
                if original.core_event_id is not None and (
                        current.core_event_id != original.core_event_id or current.dispatched_at != original.dispatched_at):
                    raise TaskConflict('Supplier query rewrites an already known original dispatch event or time')
                if not available(current,historic=True):
                    return 'unavailable'
                if current.status == 'submitted_unknown' or current.query_status in {'unknown', 'not_queried'}:
                    return 'waiting'
                if current.status == 'failed':
                    return 'unavailable'
                # A shipment projection includes later status updates; it has
                # no actual timestamp for every update or original submission.
                for ref in [*current.evidence_refs, *current.plan.condition_evidence_refs]:
                    if not evidence(ref,historic=True):
                        return 'unavailable'
                dispatch_at = current.dispatched_at
                if current.status in {'dispatched','in_transit','arrived','received'} and dispatch_at is None:
                    raise TaskConflict('Recorded Supplier transport lacks original actual dispatch time')
                if not evidence(current.plan.quantity.basis_ref,at=dispatch_at,historic=True):
                    return 'unavailable'
                quantity = decimal_fraction(current.plan.quantity.value)
                if quantity <= 0 or not current.slice_refs or len(set(current.slice_refs)) != len(current.slice_refs):
                    raise TaskConflict('Supplier shipment omits original positive physical cargo slices')
                total = 0
                for ref in current.slice_refs:
                    cargo = reading.resolve(ref)
                    if not isinstance(cargo, SupplierShipmentSliceView) or cargo.ref != ref:
                        raise TaskConflict('Supplier shipment substitutes a cargo slice')
                    batch = reading.resolve(cargo.dispatchable_ref)
                    if (not isinstance(batch, SupplierDispatchableView) or batch.ref != cargo.dispatchable_ref
                            or batch.batch_ref != current.plan.batch_ref
                            or batch.physical_batch_key != current.physical_batch_key or cargo.quantity.unit != current.plan.quantity.unit):
                        raise TaskConflict('Supplier shipment changes original physical batch/quantity units')
                    if current.status != 'rejected':
                        if cargo.physical_slice_key in physical_slices:
                            raise TaskConflict('Supplier query dispatches a physical cargo slice twice')
                        physical_slices.add(cargo.physical_slice_key)
                    amount = decimal_fraction(cargo.quantity.value)
                    if not available(cargo,historic=True) or not available(batch,historic=True):
                        return 'unavailable'
                    for evidence_ref in [*cargo.evidence_refs,*batch.evidence_refs]:
                        if not evidence(evidence_ref,historic=True):
                            return 'unavailable'
                    if amount < 0 or not evidence(cargo.quantity.basis_ref,at=dispatch_at,historic=True):
                        return 'unavailable'
                    total += amount
                    related[cargo.ref.key()] = cargo.model_dump(mode='json')
                    related[batch.ref.key()] = batch.model_dump(mode='json')
                if total != quantity:
                    raise TaskConflict('Supplier shipment quantity differs from its original cargo slices')
                if current.status in {'dispatched', 'in_transit', 'arrived', 'received'}:
                    if (current.query_status != 'present' or current.core_event_id is None or current.core_event_id in core_events
                            or current.dispatched_at is None or current.dispatched_at.clock_ref != now.clock_ref
                            or current.dispatched_at.offset > current.available_at.offset or current.current_position_ref is None):
                        raise TaskConflict('Supplier movement lacks its distinct actual dispatch event and original timing')
                    core_events.add(current.core_event_id)
                    position = reading.resolve(current.current_position_ref)
                    if (not isinstance(position, SupplierTransportPositionView) or position.ref != current.current_position_ref
                            or position.shipment_ref != current.ref or position.producer != 'core'
                            or position.observed_at.clock_ref != now.clock_ref
                            or not current.dispatched_at.offset <= position.observed_at.offset <= now.offset
                            or position.remaining_quantity.unit != current.plan.quantity.unit
                            or not 0 <= decimal_fraction(position.remaining_quantity.value) <= quantity):
                        raise TaskConflict('Supplier current position changes original shipment or quantity/timing')
                    if (not available(position,historic=True) or position.observed_at.offset > position.available_at.offset
                            or not position.effective_window.contains(position.observed_at)
                            or not evidence(position.remaining_quantity.basis_ref,at=position.observed_at)):
                        return 'unavailable'
                    for evidence_ref in position.evidence_refs:
                        if not evidence(evidence_ref,at=position.observed_at):
                            return 'unavailable'
                    related[position.ref.key()] = position.model_dump(mode='json')
                    if current.status in {'arrived', 'received'} and (
                            position.location_ref != current.plan.destination_ref or not current.traversal_refs):
                        raise TaskConflict('Supplier arrival lacks original destination and actual traversal history')
                    if len(set(current.traversal_refs)) != len(current.traversal_refs):
                        raise TaskConflict('Supplier query repeats traversal evidence')
                    for ref in current.traversal_refs:
                        traversal = reading.resolve(ref)
                        if not isinstance(traversal, SupplierTransportTraversalView) or traversal.shipment_ref != current.ref or traversal.producer != 'core':
                            raise TaskConflict('Supplier traversal substitutes another shipment or a noncore movement')
                        route = reading.resolve(traversal.route_ref)
                        if not isinstance(route, SupplierTransportRouteView):
                            raise TaskConflict('Supplier traversal lacks its original route')
                        method = reading.resolve(route.method_ref)
                        if not isinstance(method, SupplierTransportMethodView) or method.clock_ref != now.clock_ref:
                            raise TaskConflict('Supplier traversal lacks its original clock/method')
                        related[ref.key()] = traversal.model_dump(mode='json')
                        related[route.ref.key()] = route.model_dump(mode='json')
                        related[method.ref.key()] = method.model_dump(mode='json')
                    if current.status in {'arrived', 'received'}:
                        try:
                            validate_arrival_traversals(current, position, read=transport_read,
                                clock=transport_clock,
                                true=lambda value: isinstance(value, Known) and value.value is True,
                                evidence=transport_evidence, needs=_needs, unsupported=_unsupported)
                        except ObservationGap:
                            return 'unavailable'
                elif (current.status != 'rejected' or current.core_event_id is not None or current.dispatched_at is not None
                        or current.current_position_ref is not None or current.traversal_refs):
                    raise TaskConflict('Unconfirmed Supplier movement invents physical dispatch/arrival')
                originals.append(original.model_dump(mode='json'))
                currents.append(current.model_dump(mode='json'))
            if validate_relation(source_identity=deepcopy(source), original_shipments=deepcopy(originals),
                    current_shipments=deepcopy(currents), related_sources=deepcopy(list(related.values())),
                    evidence=deepcopy(list(observed.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Supplier wait lacks authentic complete original dispatch, position and elapsed traversal history')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('SUPPLIER-A08', code, '3', frozenset({'dependency_change'}), evaluate)
