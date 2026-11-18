"""Adopt explicit original Supplier cost rates without deriving prices from totals."""
from typing import Literal

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, ValueState, Money, ref_type, walk_references
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_product_objects import ProductSpecificationView
from src.actions.contracts.supplier_quote_objects import QuoteCostView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierCostSourceView(GovReviewAuthored):
    """Host projection of an existing professional cost record, not a generated estimate."""
    ref: ref_type('SupplierCostSource')
    run_id: TextId
    supplier_organization_id: TextId
    product_ref: ref_type('ProductSpecification')
    quantity_unit: TextId
    service_code: TextId
    unit_cost: ValueState[Money]
    per_batch_cost: ValueState[Money]
    purpose: Literal['binding_quote', 'indicative_only']
    original_record_sha256: Digest
    original_record_evidence_ref: ref_type('Evidence')


class SupplierCostAdoptionView(GovReviewAuthored):
    """Explicit Supplier authority to use this exact original rate for this destination."""
    ref: ref_type('SupplierCostAdoption')
    run_id: TextId
    organization_id: TextId
    source_ref: ref_type('SupplierCostSource')
    source_sha256: Digest
    product_sha256: Digest
    cost_ref: ref_type('CostBasis')
    adoption_evidence_refs: list[ref_type('Evidence')]
    author_action_id: Literal['SUPPLIER-A03']


def add_supplier_cost_schemas(schemas):
    schemas.register_kind('SupplierCostSource', SupplierCostSourceView, str)
    schemas.register_kind('SupplierCostAdoption', SupplierCostAdoptionView, str)
    return schemas


def prepare_supplier_quote_cost(*, context, reading, adoption_ref, validate_current):
    """Copy original unit/batch values, including unknown and indicative states.

    Host verification must bind the actual professional record and its product,
    service, destination and applicability. No method, FX, total division or
    productivity calculation occurs. Publish the returned snapshot at a fresh
    authorized read token before A03 execution; do not mutate the current view.
    """
    if (not isinstance(reading, ActionReadView) or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != 'SUPPLIER-A03' or not callable(validate_current)):
        raise ValueError('Cost production requires actual A03 reading and explicit source validation')
    reading.check_method_context(context, 'SUPPLIER-A03')
    now = context.business_time

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise ValueError('Cost production requires its exact original concrete source version')
        return row

    def current(row):
        if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now)):
            raise ValueError('Cost source or adoption is unavailable at the original current time')

    def author(row, *, supplier=False):
        grant = read(row.author_authority_ref, Authorization)
        assignment = reading.resolve(row.author_function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.function_ref != row.author_function_ref
                or supplier and assignment.role != 'Supplier'
                or grant.organization_id != row.author_organization_id or grant.actor_id != row.author_actor_id
                or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids
                or not any(scope_covers(scope, row.scope) for scope in grant.scopes)
                or row.authored_at.clock_ref != now.clock_ref or row.authored_at.offset > row.available_at.offset
                or not row.effective_window.contains(row.authored_at) or not grant.validity.contains(row.authored_at)):
            raise ValueError('Cost source/adoption lacks its independent original author authority')
        return [*grant.basis_refs, *assignment.basis_refs]

    try:
        adoption = read(Reference.model_validate(adoption_ref), SupplierCostAdoptionView)
        source = read(adoption.source_ref, SupplierCostSourceView)
        current(adoption); current(source)
        if (adoption.run_id != context.run_id or source.run_id != context.run_id
                or adoption.organization_id != reading.organization_id
                or adoption.author_organization_id != reading.organization_id
                or source.supplier_organization_id != reading.organization_id
                or adoption.scope != context.scope or not scope_covers(source.scope, adoption.scope)
                or task_digest(source.model_dump(mode='json')) != adoption.source_sha256):
            raise ValueError('Cost adoption substitutes original Supplier, scope, run or source record')
        product = read(source.product_ref, ProductSpecificationView)
        if (product.supplier_organization_id != reading.organization_id or product.quantity_unit != source.quantity_unit
                or task_digest(product.model_dump(mode='json')) != adoption.product_sha256
                or not product.effective_window.contains(now)):
            raise ValueError('Cost source substitutes original product/version or quantity unit')
        authority_refs = [*author(adoption, supplier=True), *author(source)]
        unique_refs(adoption.adoption_evidence_refs)
        if not adoption.adoption_evidence_refs:
            raise ValueError('Cost source requires independent Supplier adoption evidence')
        source_refs = [*source.evidence_refs, source.original_record_evidence_ref,
            *(ref for value in (source.unit_cost, source.per_batch_cost) for ref in walk_references(value) if ref.kind == 'Evidence')]
        if set(adoption.adoption_evidence_refs).intersection(source_refs):
            raise ValueError('Professional cost source evidence cannot substitute independent Supplier adoption')
        evidence_refs = list({ref.key(): ref for ref in [*adoption.evidence_refs,
            *adoption.adoption_evidence_refs, *source_refs, *product.evidence_refs, *authority_refs]}.values())
        for ref in evidence_refs:
            evidence = read(ref, EvidenceRecord)
            if (evidence.effective_window is not None and not evidence.effective_window.contains(now)
                    or ref in [source.original_record_evidence_ref, *adoption.adoption_evidence_refs]
                    and evidence.basis_kind != 'observed'
                    or ref == source.original_record_evidence_ref and evidence.content_hash != source.original_record_sha256):
                raise ValueError('Cost record and independent adoption require current observed evidence')
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        if (adoption.cost_ref not in context.visible_refs or not any(isinstance(grant, Authorization)
                and grant.organization_id == reading.organization_id and grant.actor_id == context.actor_id
                and grant.function_ref == context.function_ref and 'SUPPLIER-A03' in grant.action_ids
                and grant.validity.contains(now) and adoption.cost_ref in grant.readable_refs
                and any(scope_covers(scope, context.scope) for scope in grant.scopes) for grant in grants)):
            raise ValueError('Produced cost target lacks original explicit current read authority')
        if validate_current(context=context.model_copy(deep=True), adoption=adoption.model_copy(deep=True),
                source=source.model_copy(deep=True), product=product.model_copy(deep=True)) is not True:
            raise ValueError('Actual original professional record and Supplier adoption require host verification')
        projection = QuoteCostView(ref=adoption.cost_ref, supplier_organization_id=reading.organization_id,
            product_ref=source.product_ref, destination_scope_ref=adoption.scope,
            quantity_unit=source.quantity_unit, service_code=source.service_code,
            unit_cost=source.unit_cost.model_copy(deep=True), per_batch_cost=source.per_batch_cost.model_copy(deep=True),
            purpose=source.purpose, available_at=now,
            effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'}, evidence_refs=evidence_refs)
        return {'kind': 'prepared', 'cost_projection': projection,
            'cost_sha256': task_digest(projection.model_dump(mode='json')),
            'source_sha256': adoption.source_sha256, 'original_record_sha256': source.original_record_sha256,
            'adoption_sha256': task_digest(adoption.model_dump(mode='json')),
            'context_sha256': task_digest(context.model_dump(mode='json')),
            'source_mode': 'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
            'limitations': ['Snapshot only; publish at a fresh authorized read token.',
                'Original values/purpose retained; no price, FX, productivity or binding status inferred.']}
    finally:
        reading.recheck()
