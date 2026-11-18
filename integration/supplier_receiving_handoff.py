"""Relate saved A09 responses to actual contract-node delivery evidence for A10."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_receiving_results import SavedSupplierReceiving
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_payment_objects import (
    SupplierOrderPaymentNodeView, SupplierPaymentDeliveryView, SupplierPaymentOrderView,
    supplier_payment_schemas,
)
from src.actions.contracts.supplier_receiving_objects import (
    SupplierArrivalEvidenceView, SupplierCustomerReceiptView, SupplierReceiptInspectionView,
    SupplierReceivingShipmentView,
)
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierReceivingDeliveryLink(StrictRecord):
    delivery_ref: ref_type('DeliveryEvidence')
    delivery_sha256: Digest
    source_ref: Reference
    source_sha256: Digest
    node_sha256: Digest
    native_record_sha256: Digest
    native_record_evidence_ref: ref_type('Evidence')


class SupplierReceivingHandoffBasisView(GovReviewAuthored):
    """Observed source relation; independent contract entitlement stays with its issuer."""
    ref: ref_type('SupplierReceivingHandoffBasis')
    run_id: TextId
    organization_id: TextId
    receiving_task_sha256: Digest
    receiving_record_sha256: Digest
    receiving_result_sha256: Digest
    receiving_audit_sha256: Digest
    receiving_source_reading_sha256: Digest
    delivery_links: Annotated[list[SupplierReceivingDeliveryLink], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A10']


def supplier_receiving_handoff_schemas():
    schemas = supplier_payment_schemas()
    for kind, schema in [('Shipment', SupplierReceivingShipmentView), ('ArrivalEvidence', SupplierArrivalEvidenceView),
            ('GoodsReceipt', SupplierCustomerReceiptView), ('InspectionResult', SupplierReceiptInspectionView),
            ('SupplierReceivingHandoffBasis', SupplierReceivingHandoffBasisView)]:
        schemas.register_kind(kind, schema, str)
    return schemas


def prepare_supplier_receiving_handoff(saved, *, context, reading, basis_ref, delivery_refs, order_refs, validate_current):
    """Keep shipment events, receiving facts, inspection and independent payment rights separate."""
    if (not isinstance(saved, SavedSupplierReceiving) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A10'
            or not callable(validate_current)):
        raise ValueError('Receiving handoff requires original saved A09 and actual authorized A10 reading')
    reading.check_method_context(context, 'SUPPLIER-A10')
    if (saved.current_context != context or saved.identity.action_id != 'SUPPLIER-A09'
            or saved.identity.role != 'Supplier' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Receiving handoff changes original Supplier, task, input/context or retained sources')
    if saved.result.kind != 'completed':
        return {'kind': 'needs_information', 'missing_fields': ['completed_original_receiving_response'],
            'requested_refs': [saved.action_input.shipment_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A09',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(k) != v for k, v in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Receiving handoff lacks original successful authorized audit')
    now = context.business_time

    def read(ref, schema, *, historic=False):
        row = reading.resolve(ref)
        if (not isinstance(row, schema) or row.ref != ref or row.available_at.clock_ref != now.clock_ref
                or row.available_at.offset > now.offset or not historic and not row.effective_window.contains(now)):
            raise ValueError('Delivery relation requires exact available concrete source versions')
        return row

    def original(ref, schema):
        rows = [row for row in saved.source_reading if Reference.model_validate(row['ref']) == ref]
        if len(rows) != 1:
            raise ValueError('Delivery relation lacks exact retained original receiving source')
        row = schema.model_validate(rows[0]['projection'])
        if row.ref != ref:
            raise ValueError('Retained receiving source changes its reference')
        return row

    def evidence_at(refs, at=None, *, historic=False, observed=False):
        point = now if at is None else at
        if point.clock_ref != now.clock_ref or point.offset > now.offset:
            raise ValueError('Delivery evidence changes its actual use clock or time')
        for ref in {ref.key(): ref for ref in refs}.values():
            row = reading.resolve(ref)
            if (not isinstance(row,EvidenceRecord) or observed and row.basis_kind != 'observed'
                    or row.effective_window is not None and (
                        row.effective_window.start.clock_ref != now.clock_ref
                        or row.effective_window.start.offset > now.offset
                        or (at is not None or not historic) and not row.effective_window.contains(point))):
                raise ValueError('Delivery evidence is unavailable or invalid at its actual use time')

    try:
        basis = read(Reference.model_validate(basis_ref), SupplierReceivingHandoffBasisView)
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'receiving_task_sha256': saved.identity.key, 'receiving_record_sha256': saved.record_sha256,
            'receiving_result_sha256': result_sha, 'receiving_audit_sha256': task_digest(saved.audit),
            'receiving_source_reading_sha256': saved.source_reading_sha256}
        if any(getattr(basis, k) != v for k, v in expected.items()):
            raise ValueError('Delivery relation substitutes original saved receiving evidence')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or grant.ref != basis.author_authority_ref
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(s, basis.scope) for s in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Receiving relation lacks independent Supplier author authority')
        for ref in [*grant.basis_refs,*assignment.basis_refs]:
            if ref.kind == 'Evidence':evidence_at([ref],basis.authored_at)
            else:reading.resolve(ref)
        shipment = original(saved.action_input.shipment_ref, SupplierReceivingShipmentView)
        if shipment.order_ref not in [Reference.model_validate(ref) for ref in order_refs]:
            raise ValueError('Receiving relation names an order absent from the selected payment input')
        order = read(shipment.order_ref, SupplierPaymentOrderView)
        if order.supplier_id != reading.organization_id:
            raise ValueError('Actual payment order substitutes original receiving Supplier')
        selected = [Reference.model_validate(ref) for ref in delivery_refs]
        unique_refs(selected); unique_refs([link.delivery_ref for link in basis.delivery_links])
        if not selected or set(selected) != {link.delivery_ref for link in basis.delivery_links}:
            raise ValueError('Delivery relation substitutes explicitly selected actual delivery versions')
        mappings = {
            'actual_dispatch': (SupplierReceivingShipmentView, [saved.action_input.shipment_ref]),
            'actual_arrival': (SupplierArrivalEvidenceView, saved.action_input.arrival_refs),
            'actual_receipt': (SupplierCustomerReceiptView, saved.action_input.receipt_refs),
            'actual_inspection': (SupplierReceiptInspectionView, saved.action_input.inspection_refs),
        }
        deliveries, sources, nodes = [], [], []
        native_hashes = {}
        for link in basis.delivery_links:
            delivery = read(link.delivery_ref, SupplierPaymentDeliveryView, historic=True)
            schema, refs = mappings[delivery.kind]
            if link.source_ref not in refs:
                raise ValueError('Delivery basis is absent from the original explicit receiving source selection')
            source = read(link.source_ref, schema, historic=True)
            prior = original(link.source_ref, schema)
            if (task_digest(delivery.model_dump(mode='json')) != link.delivery_sha256
                    or task_digest(source.model_dump(mode='json')) != link.source_sha256
                    or source.model_dump(mode='json') != prior.model_dump(mode='json')
                    or delivery.order_ref != shipment.order_ref or delivery.order_line_ref not in order.line_refs
                    or delivery.node_ref not in order.node_refs
                    or delivery.occurred_at.clock_ref != now.clock_ref or delivery.occurred_at.offset > now.offset
                    or delivery.kind != 'actual_dispatch' and source.shipment_ref != shipment.ref):
                raise ValueError('Actual delivery substitutes original receiving facts, order, node or time')
            node = read(delivery.node_ref, SupplierOrderPaymentNodeView)
            if (task_digest(node.model_dump(mode='json')) != link.node_sha256 or node.order_ref != order.ref
                    or node.order_line_ref != delivery.order_line_ref or delivery.ref not in node.delivery_evidence_refs
                    or node.payee_id != reading.organization_id or node.payer_id != order.payer_id or node.as_of != now):
                raise ValueError('Actual delivery relation changes independently sourced current contract node')
            if delivery.kind == 'actual_dispatch':
                event, at = source.core_event_id, source.dispatched_at
                known = source.query_status == 'present' and source.status in {'dispatched', 'in_transit', 'arrived', 'received'}
            elif delivery.kind == 'actual_arrival':
                event, at, known = source.core_event_id, source.arrived_at, True
                if source.physical_batch_key != shipment.physical_batch_key or source.destination_ref != shipment.plan.destination_ref:
                    raise ValueError('Delivery arrival substitutes original physical batch or destination')
            elif delivery.kind == 'actual_receipt':
                event, at, known = source.core_event_id, source.authored_at, source.status == 'recorded'
            else:
                event, at, known = None, source.authored_at, source.status == 'ok'
            if not known or at is None:
                return {'kind': 'needs_information', 'missing_fields': ['actual_recorded_delivery_or_independent_inspection'],
                    'requested_refs': [source.ref]}
            if delivery.occurred_at != at or event is not None and delivery.core_event_id != event:
                raise ValueError('Delivery evidence substitutes original event or actual observation time')
            if (at.clock_ref != now.clock_ref or at.offset > source.available_at.offset
                    or at.offset > delivery.available_at.offset):
                raise ValueError('Delivery source precedes its actual original occurrence')
            evidence_at(delivery.evidence_refs,at)
            if delivery.kind == 'actual_dispatch':
                # Shipment can include later state observations with no
                # independent timestamp; its cargo amount belongs to dispatch.
                evidence_at(source.evidence_refs,historic=True)
                evidence_at([source.plan.quantity.basis_ref],at)
            else:
                evidence_at(source.evidence_refs,at)
                if delivery.kind == 'actual_arrival':evidence_at([source.quantity.basis_ref],at)
                elif delivery.kind == 'actual_inspection':evidence_at([source.covered_quantity.basis_ref],at)
            if (node.authored_at.clock_ref != now.clock_ref or node.authored_at.offset > node.available_at.offset
                    or not node.effective_window.contains(node.authored_at)):
                raise ValueError('Contract payment node precedes or invalidates its original authorship')
            evidence_at(node.evidence_refs,node.authored_at)
            key = link.native_record_evidence_ref.key()
            if key in native_hashes and native_hashes[key] != link.native_record_sha256:
                raise ValueError('Native record evidence changes its immutable content digest')
            native_hashes[key] = link.native_record_sha256
            # Native content is the independently observed snapshot; the
            # underlying delivery occurrence has its own original time above.
            evidence_at([link.native_record_evidence_ref],now,observed=True)
            deliveries.append(delivery); sources.append(source); nodes.append(node)
        unique_refs(basis.relation_evidence_refs)
        if any(ref.key() in native_hashes for ref in basis.relation_evidence_refs):
            raise ValueError('Native delivery evidence cannot replace independent source relation')
        evidence_at(basis.evidence_refs,basis.authored_at)
        evidence_at(basis.relation_evidence_refs,basis.authored_at,observed=True)
        for link in basis.delivery_links:
            if reading.resolve(link.native_record_evidence_ref).content_hash != native_hashes[link.native_record_evidence_ref.key()]:
                raise ValueError('Actual delivery changes original native observed content')
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True), basis=basis.model_copy(deep=True),
                order=order.model_copy(deep=True), deliveries=deepcopy(deliveries), sources=deepcopy(sources), nodes=deepcopy(nodes)) is not True:
            raise ValueError('Actual native delivery, independent receiving/inspection and contract-node relation require host verification')
        return {'kind': 'prepared', 'delivery_evidence_refs': selected,
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'receiving_record_sha256': saved.record_sha256,
            'receiving_result_sha256': result_sha,
            'limitations': ['Source relation only; original A10 independent entitlement, valuation and cash checks remain required.']}
    finally:
        reading.recheck()
