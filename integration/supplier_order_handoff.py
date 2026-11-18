"""Relate a saved full A04 acceptance to an existing effective order for A05."""
from copy import deepcopy
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_order_results import SavedSupplierOrder
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Known, Reference, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_order_objects import OrderDeliveryLine, OrderProposalView, order_agreement_digest
from src.actions.contracts.supplier_planning_objects import (
    SupplierPlanningOrderLineView, SupplierPlanningOrderView, SupplierWorkAuthorityView, supplier_planning_schemas,
)
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierFormedOrderLine(StrictRecord):
    order_line_ref: ref_type('OrderLine')
    order_line_sha256: Digest
    delivery: OrderDeliveryLine


class SupplierOrderFormationRecordView(CostSource):
    """Host view of original formal order details and current native line versions."""
    ref: ref_type('SupplierOrderFormationRecord')
    run_id: TextId
    organization_id: TextId
    as_of: TimePoint
    order_ref: ref_type('Order')
    order_projection_sha256: Digest
    core_event_id: TextId
    proposal_ref: ref_type('OrderProposal')
    offer_ref: ref_type('SupplyOffer')
    agreement_sha256: Digest
    buyer_id: TextId
    payer_id: TextId
    terms_ref: ref_type('SupplyTerms')
    condition_refs: list[ref_type('Requirement')]
    lines: Annotated[list[SupplierFormedOrderLine], Field(min_length=1)]
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class SupplierOrderLineLink(StrictRecord):
    accepted_line_index: Annotated[int, Field(ge=0)]
    order_line_ref: ref_type('OrderLine')


class SupplierOrderHandoffBasisView(GovReviewAuthored):
    """Independent source relation, with no order formation or work permission."""
    ref: ref_type('SupplierOrderHandoffBasis')
    run_id: TextId
    organization_id: TextId
    order_task_sha256: Digest
    order_record_sha256: Digest
    order_input_sha256: Digest
    order_context_sha256: Digest
    order_result_sha256: Digest
    order_audit_sha256: Digest
    order_source_reading_sha256: Digest
    proposal_agreement_sha256: Digest
    formation_record_ref: ref_type('SupplierOrderFormationRecord')
    formation_record_sha256: Digest
    line_links: Annotated[list[SupplierOrderLineLink], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A05']


def supplier_order_handoff_schemas():
    schemas = supplier_planning_schemas()
    schemas.register_kind('SupplierOrderFormationRecord', SupplierOrderFormationRecordView, str)
    schemas.register_kind('SupplierOrderHandoffBasis', SupplierOrderHandoffBasisView, str)
    return schemas


def prepare_supplier_order_handoff(saved, *, context, reading, basis_ref,
        work_authority_ref, validate_current):
    """Match full accepted lines to actual native order, retaining current remaining amounts."""
    if (not isinstance(saved, SavedSupplierOrder) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A05'
            or not callable(validate_current)):
        raise ValueError('Order handoff requires saved original A04 evidence and actual authorized A05 reading')
    reading.check_method_context(context, 'SUPPLIER-A05')
    if (saved.current_context != context or saved.identity.action_id != 'SUPPLIER-A04'
            or saved.identity.role != 'Supplier' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Order handoff changes original Supplier, task, input/context or retained sources')
    if saved.result.kind != 'completed' or saved.result.payload.choice != 'accept':
        return {'kind': 'needs_information', 'missing_fields': ['completed_independently_confirmed_full_order_acceptance'],
            'requested_refs': [saved.action_input.order_proposal_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A04',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(key) != value for key, value in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Order handoff lacks its original successful authorized audit')
    now = context.business_time

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Order handoff requires its exact original concrete source version')
        return row

    def current(row):
        if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now)):
            raise ValueError('Order relation/native record is unavailable at the current original time')

    def evidence_at(refs, at):
        if at.clock_ref != now.clock_ref or at.offset > now.offset:
            raise ValueError('Order evidence changes the original business clock or use time')
        for ref in {ref.key(): ref for ref in refs}.values():
            row = read(ref, EvidenceRecord)
            if row.effective_window is not None and not row.effective_window.contains(at):
                raise ValueError('Order evidence is invalid at its original use time')

    try:
        basis = read(Reference.model_validate(basis_ref), SupplierOrderHandoffBasisView)
        current(basis)
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'order_task_sha256': saved.identity.key, 'order_record_sha256': saved.record_sha256,
            'order_input_sha256': saved.identity.input_sha256, 'order_context_sha256': saved.identity.context_sha256,
            'order_result_sha256': result_sha, 'order_audit_sha256': task_digest(saved.audit),
            'order_source_reading_sha256': saved.source_reading_sha256,
            'proposal_agreement_sha256': saved.proposal_agreement_sha256}
        if any(getattr(basis, key) != value for key, value in expected.items()):
            raise ValueError('Order relation substitutes original acceptance evidence')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Order source relation lacks original independent Supplier authority')
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                evidence_at([ref], basis.authored_at)
            else:
                reading.resolve(ref)
        originals = [row for row in saved.source_reading
            if Reference.model_validate(row['ref']).key() == saved.action_input.order_proposal_ref.key()]
        if len(originals) != 1:
            raise ValueError('Order handoff lacks the exact retained original proposal')
        proposal = OrderProposalView.model_validate(originals[0]['projection'])
        if order_agreement_digest(proposal) != saved.proposal_agreement_sha256:
            raise ValueError('Original accepted agreement changed')
        source = read(basis.formation_record_ref, SupplierOrderFormationRecordView)
        order = read(source.order_ref, SupplierPlanningOrderView)
        mandate = read(Reference.model_validate(work_authority_ref), SupplierWorkAuthorityView)
        current(source); current(order); current(mandate)
        if (task_digest(source.model_dump(mode='json')) != basis.formation_record_sha256
                or source.run_id != context.run_id or source.organization_id != reading.organization_id
                or source.as_of != now or source.scope != proposal.scope or order.scope != proposal.scope
                or source.order_projection_sha256 != task_digest(order.model_dump(mode='json'))
                or source.core_event_id != order.core_event_id or order.supplier_id != reading.organization_id
                or source.proposal_ref != proposal.ref or source.offer_ref != saved.result.payload.offer_ref
                or source.offer_ref != saved.action_input.offer_ref or source.agreement_sha256 != saved.proposal_agreement_sha256
                or source.buyer_id != proposal.buyer_id or order.buyer_id != proposal.buyer_id
                or source.payer_id != proposal.payer_id or source.terms_ref != saved.result.payload.terms_ref
                or source.terms_ref != proposal.terms_ref or source.condition_refs != proposal.condition_refs
                or mandate.organization_id != reading.organization_id or mandate.order_ref != order.ref
                or mandate.speculative_authority_ref is not None or not scope_covers(order.scope, mandate.scope)):
            raise ValueError('Actual formed order substitutes original agreement, parties, scope or work source')
        if not isinstance(order.effective, Known) or order.effective.value is not True:
            return {'kind': 'needs_information', 'missing_fields': ['original_effective_core_confirmed_supply_order'],
                'requested_refs': [order.ref]}
        unique_refs(order.line_refs)
        unique_refs([row.order_line_ref for row in source.lines])
        unique_refs([row.order_line_ref for row in basis.line_links])
        formed = {row.order_line_ref.key(): row for row in source.lines}
        accepted = saved.result.payload.accepted_lines
        if (len(basis.line_links) != len(accepted) or len(formed) != len(accepted)
                or {row.accepted_line_index for row in basis.line_links} != set(range(len(accepted)))
                or {row.order_line_ref.key() for row in basis.line_links} != set(formed)
                or {ref.key() for ref in order.line_refs} != set(formed)
                or not mandate.order_line_refs or not {ref.key() for ref in mandate.order_line_refs} <= set(formed)):
            raise ValueError('Order relation omits, duplicates or adds an original accepted/native line')
        native_lines = []
        for link in basis.line_links:
            row = formed[link.order_line_ref.key()]
            original = OrderDeliveryLine.model_validate(accepted[link.accepted_line_index].model_dump(mode='python'))
            line = read(link.order_line_ref, SupplierPlanningOrderLineView)
            current(line)
            if (row.delivery != original or task_digest(line.model_dump(mode='json')) != row.order_line_sha256
                    or line.order_ref != order.ref or line.as_of != now or line.product != original.product
                    or line.delivery_window_ref != original.delivery_window_ref
                    or line.remaining_quantity.unit != original.product.quantity.unit
                    or not Decimal('0') <= Decimal(line.remaining_quantity.value) <= Decimal(original.product.quantity.value)):
                raise ValueError('Formed line changes original quantity/price/services or current native remaining quantity')
            native_lines.append(line.model_copy(deep=True))
        unique_refs(basis.relation_evidence_refs)
        if set(basis.relation_evidence_refs).intersection([source.native_evidence_ref, *source.evidence_refs]):
            raise ValueError('Native formation evidence cannot replace independent order relation evidence')
        evidence_at([*basis.evidence_refs, *basis.relation_evidence_refs], basis.authored_at)
        for ref in basis.relation_evidence_refs:
            if read(ref, EvidenceRecord).basis_kind != 'observed':
                raise ValueError('Order relation requires independently observed original evidence')
        evidence_at([source.native_evidence_ref, *source.evidence_refs, *order.evidence_refs, *mandate.evidence_refs,
            *[ref for line in native_lines for ref in line.evidence_refs],
            *[line.remaining_quantity.basis_ref for line in native_lines]], now)
        native = read(source.native_evidence_ref, EvidenceRecord)
        if native.basis_kind != 'observed' or native.content_hash != source.native_source_sha256:
            raise ValueError('Actual native order requires its exact current observed evidence')
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True), basis=basis.model_copy(deep=True),
                source=source.model_copy(deep=True), order=order.model_copy(deep=True),
                lines=native_lines, work_authority=mandate.model_copy(deep=True)) is not True:
            raise ValueError('Actual original formation/party confirmations and current remaining state require host verification')
        return {'kind': 'prepared', 'order_ref': order.ref,
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'order_record_sha256': saved.record_sha256,
            'order_result_sha256': result_sha, 'formation_record_sha256': basis.formation_record_sha256,
            'native_order_source_sha256': source.native_source_sha256, 'order_projection_sha256': source.order_projection_sha256,
            'limitations': ['Source relation only; original A05 independently checks its actual work mandate and requirements.',
                'No order formation, stock/reservation, work authority or reset of remaining quantities.']}
    finally:
        reading.recheck()
