"""Bind saved A08 decisions to actual current A09 shipments without cargo effects."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_logistics_results import SavedSupplierLogistics
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Known, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_logistics_objects import (
    SupplierDispatchableView, SupplierLogisticsProfileView, SupplierShipmentView,
    SupplierTransportMethodView, SupplierTransportPositionView,
    SupplierTransportRouteView, SupplierTransportTraversalView,
)
from src.actions.contracts.supplier_receiving_objects import SupplierReceivingShipmentView, supplier_receiving_schemas
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.supplier_transport_history import validate_arrival_traversals
from src.coordination.tasks import task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierShipmentSourceLink(StrictRecord):
    plan_index: Annotated[int, Field(ge=0)] | None
    shipment_ref: ref_type('Shipment')
    shipment_sha256: Digest
    native_record_sha256: Digest
    native_record_evidence_ref: ref_type('Evidence')


class SupplierLogisticsHandoffBasisView(GovReviewAuthored):
    """Independently authored relation to observed shipments, never an arrival receipt."""
    ref: ref_type('SupplierLogisticsHandoffBasis')
    run_id: TextId
    organization_id: TextId
    logistics_task_sha256: Digest
    logistics_record_sha256: Digest
    logistics_result_sha256: Digest
    logistics_audit_sha256: Digest
    logistics_source_reading_sha256: Digest
    shipment_links: Annotated[list[SupplierShipmentSourceLink], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A09']


def supplier_logistics_handoff_schemas():
    schemas = supplier_receiving_schemas()
    schemas.register_kind('SupplierLogisticsHandoffBasis', SupplierLogisticsHandoffBasisView, str)
    for kind, schema in (
            ('TransportPosition', SupplierTransportPositionView),
            ('TransportTraversal', SupplierTransportTraversalView),
            ('TransportRoute', SupplierTransportRouteView),
            ('TransportMethod', SupplierTransportMethodView)):
        schemas.register_kind(kind, schema, str)
    return schemas


def prepare_supplier_logistics_handoff(saved, *, context, reading, basis_ref, shipment_ref, validate_current):
    """Preserve original dispatch plans and explicit existing-shipment selections."""
    if (not isinstance(saved, SavedSupplierLogistics) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A09'
            or not callable(validate_current)):
        raise ValueError('Logistics handoff requires saved original A08 and actual authorized A09 reading')
    reading.check_method_context(context, 'SUPPLIER-A09')
    if (saved.current_context != context or saved.identity.action_id != 'SUPPLIER-A08'
            or saved.identity.role != 'Supplier' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Logistics handoff changes original Supplier, task, input/context or sources')
    if saved.result.kind != 'completed':
        return {'kind': 'needs_information', 'missing_fields': ['completed_original_logistics_decision'],
            'requested_refs': [saved.action_input.order_ref]}
    payload = saved.result.payload
    if payload.choice == 'reschedule' and payload.target.kind != 'shipments':
        return {'kind': 'needs_information', 'missing_fields': ['actual_dispatch_for_rescheduled_order_lines'],
            'requested_refs': [saved.action_input.order_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A08',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(k) != v for k, v in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Logistics handoff lacks original successful authorized audit')
    now = context.business_time

    def read(ref, schema, *, historic=False):
        row = reading.resolve(ref)
        if (not isinstance(row, schema) or row.ref != ref or row.available_at.clock_ref != now.clock_ref
                or row.available_at.offset > now.offset
                or row.effective_window.start.clock_ref != now.clock_ref
                or not historic and not row.effective_window.contains(now)):
            raise ValueError('Shipment relation requires exact current concrete source versions')
        return row

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('supplier-logistics-clock-alignment')

    def evidence_at(refs, at=None, *, historic=False, observed=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            raise ValueError('Shipment evidence use occurs in the future')
        for ref in {ref.key(): ref for ref in refs}.values():
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or observed and row.basis_kind != 'observed'
                    or row.effective_window is not None and (
                        row.effective_window.start.clock_ref != now.clock_ref
                        or row.effective_window.start.offset > now.offset
                        or (at is not None or not historic) and not row.effective_window.contains(point))):
                raise ValueError('Shipment evidence is unavailable or invalid at its actual use time')

    def transport_read(ref, schema, *, historic=False, linked=False):
        row = read(ref, schema, historic=historic)
        evidence_at(row.evidence_refs,historic=historic)
        return row

    def original(ref, schema):
        rows = [row for row in saved.source_reading if Reference.model_validate(row['ref']) == ref]
        if len(rows) != 1:
            raise ValueError('Shipment relation lacks exact original retained source')
        row = schema.model_validate(rows[0]['projection'])
        if row.ref != ref:
            raise ValueError('Original shipment source changes its reference')
        return row

    try:
        basis = read(Reference.model_validate(basis_ref), SupplierLogisticsHandoffBasisView)
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'logistics_task_sha256': saved.identity.key, 'logistics_record_sha256': saved.record_sha256,
            'logistics_result_sha256': result_sha, 'logistics_audit_sha256': task_digest(saved.audit),
            'logistics_source_reading_sha256': saved.source_reading_sha256}
        if any(getattr(basis, k) != v for k, v in expected.items()):
            raise ValueError('Shipment relation substitutes original saved evidence')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or grant.ref != basis.author_authority_ref
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(s, basis.scope) for s in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Shipment relation lacks independent Supplier author authority')
        for ref in [*grant.basis_refs,*assignment.basis_refs]:
            if ref.kind == 'Evidence':evidence_at([ref],basis.authored_at)
            else:reading.resolve(ref)
        links = basis.shipment_links
        unique_refs([link.shipment_ref for link in links])
        selected = Reference.model_validate(shipment_ref)
        if selected not in [link.shipment_ref for link in links]:
            raise ValueError('Receiving shipment is absent from the explicit original relation')
        profile = original(saved.action_input.logistics_profile_ref, SupplierLogisticsProfileView)
        if payload.choice in {'dispatch', 'split'}:
            if ([p.model_dump(mode='json') for p in payload.plans] != [p.model_dump(mode='json') for p in profile.plans]
                    or len(links) != len(payload.plans) or {link.plan_index for link in links} != set(range(len(payload.plans)))):
                raise ValueError('Actual shipment relation must cover every original plan exactly once')
        else:
            if payload.choice == 'reconcile':
                refs = payload.shipment_refs
            elif payload.choice == 'reroute':
                refs = [payload.shipment_ref]
            elif payload.choice == 'reschedule':
                refs = payload.target.shipment_refs
            else:
                raise ValueError('Unsupported original logistics decision')
            unique_refs(refs)
            if set(refs) != {link.shipment_ref for link in links} or any(link.plan_index is not None for link in links):
                raise ValueError('Existing transport decision substitutes its original shipment selection')
        shipments = []
        native_refs = []
        for link in links:
            row = read(link.shipment_ref, SupplierReceivingShipmentView)
            if (task_digest(row.model_dump(mode='json')) != link.shipment_sha256
                    or row.order_ref != saved.action_input.order_ref or row.organization_id != reading.organization_id
                    or row.run_id != context.run_id or row.as_of != now or row.scope != context.scope
                    or task_digest(row.plan.model_dump(mode='json')) != row.request_sha256):
                raise ValueError('Actual shipment changes original order, plan digest or current version')
            if payload.choice in {'dispatch', 'split'}:
                if (row.operation_id != saved.context.operation_id
                        or row.plan.model_dump(mode='json') != payload.plans[link.plan_index].model_dump(mode='json')
                        or row.slice_refs != profile.plan_slice_refs[link.plan_index]):
                    raise ValueError('Native dispatch substitutes original operation, plan or physical slices')
                batches = [original(ref, SupplierDispatchableView) for ref in saved.action_input.dispatchable_refs]
                matching = [batch for batch in batches if batch.batch_ref == row.plan.batch_ref]
                if len(matching) != 1 or matching[0].physical_batch_key != row.physical_batch_key:
                    raise ValueError('Native shipment substitutes original physical batch identity')
            else:
                prior = original(row.ref, SupplierShipmentView)
                if any(getattr(row, k) != getattr(prior, k) for k in ('order_ref', 'operation_id', 'command_id',
                        'business_key', 'physical_batch_key', 'slice_refs', 'plan', 'request_sha256')):
                    raise ValueError('Existing transport update replaces original dispatch identity or plan')
                if prior.core_event_id is not None and (row.core_event_id != prior.core_event_id or row.dispatched_at != prior.dispatched_at):
                    raise ValueError('Existing transport update replaces original native dispatch event')
            if (row.query_status != 'present' or row.status not in {'dispatched', 'in_transit', 'arrived', 'received'}
                    or row.core_event_id is None or row.dispatched_at is None or row.history_coverage != 'complete'):
                return {'kind': 'needs_information', 'missing_fields': ['actual_present_dispatch_and_complete_shipment_history'],
                    'requested_refs': [row.ref]}
            if (row.dispatched_at.clock_ref != now.clock_ref or row.dispatched_at.offset > row.available_at.offset
                    or payload.choice in {'dispatch', 'split'} and row.dispatched_at.offset < saved.context.business_time.offset):
                raise ValueError('Actual dispatch changes original business clock or time')
            if row.status in {'arrived', 'received'}:
                if row.current_position_ref is None:
                    _needs('original_visible_core_transport_position', [row.ref])
                position = transport_read(row.current_position_ref, SupplierTransportPositionView,historic=True)
                clock(position.observed_at)
                if (position.shipment_ref != row.ref or position.location_ref != row.plan.destination_ref
                        or position.observed_at.offset < row.dispatched_at.offset
                        or position.observed_at.offset > position.available_at.offset
                        or not position.effective_window.contains(position.observed_at)
                        or position.remaining_quantity.unit != row.plan.quantity.unit
                        or not 0 <= decimal_fraction(position.remaining_quantity.value) <= decimal_fraction(row.plan.quantity.value)):
                    raise ValueError('Receiving transport position changes original shipment, destination, time or quantity')
                evidence_at([*position.evidence_refs,position.remaining_quantity.basis_ref],position.observed_at)
                validate_arrival_traversals(row, position, read=transport_read, clock=clock,
                    true=lambda value: isinstance(value, Known) and value.value is True,
                    evidence=evidence_at, needs=_needs, unsupported=_unsupported)
            evidence_at([row.plan.quantity.basis_ref],row.dispatched_at)
            # Current shipment/native observations may include later status
            # updates. Their time is not the original dispatch occurrence.
            evidence_at(row.plan.condition_evidence_refs,historic=True)
            shipments.append(row)
            native_refs.append(link.native_record_evidence_ref)
        if len({row.command_id for row in shipments}) != len(shipments) or len({row.business_key for row in shipments}) != len(shipments) or len({row.core_event_id for row in shipments}) != len(shipments):
            raise ValueError('Shipment relation aliases original native commands, business keys or events')
        unique_refs(native_refs); unique_refs(basis.relation_evidence_refs)
        if set(native_refs).intersection(basis.relation_evidence_refs):
            raise ValueError('Native shipment evidence cannot replace independent source relation')
        native_hashes = {link.native_record_evidence_ref.key(): link.native_record_sha256 for link in links}
        evidence_at(basis.evidence_refs,basis.authored_at)
        evidence_at(basis.relation_evidence_refs,basis.authored_at,observed=True)
        evidence_at(native_refs,now,observed=True)
        evidence_at([ref for row in shipments for ref in row.evidence_refs],now)
        for ref in native_refs:
            if reading.resolve(ref).content_hash != native_hashes[ref.key()]:
                raise ValueError('Shipment relation changes exact native observed content')
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True),
                basis=basis.model_copy(deep=True), shipments=deepcopy(shipments)) is not True:
            raise ValueError('Actual native dispatch, physical lineage, transport changes and history require host verification')
        return {'kind': 'prepared', 'shipment_ref': selected,
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'logistics_record_sha256': saved.record_sha256,
            'logistics_result_sha256': result_sha,
            'limitations': ['Source relation only; original A09 arrival, independent receipt and inspection checks remain required.']}
    except ObservationGap as exc:
        return exc.result
    finally:
        reading.recheck()
