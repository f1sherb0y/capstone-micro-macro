"""Copy actual finished-product inventory; never derive stock from GBA capacity."""
from decimal import Decimal
from typing import Literal

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_product_objects import ProductSpecificationView
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView
from src.actions.contracts.supplier_quote_objects import QuoteInventoryView, QuoteLocationView, QuoteStockLot
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierQuoteInventorySourceView(GovReviewAuthored):
    """An actual finished-product ledger snapshot, supplied and verified by host."""
    ref: ref_type('SupplierQuoteInventorySource')
    run_id: TextId
    organization_id: TextId
    as_of: TimePoint
    record_kind: Literal['product_batch_inventory']
    coverage: Literal['complete', 'partial', 'unknown']
    lots: list[QuoteStockLot]
    original_record_sha256: Digest
    original_record_evidence_ref: ref_type('Evidence')


class SupplierQuoteInventoryAdoptionView(GovReviewAuthored):
    """Supplier authority to project this exact physical ledger for this quote."""
    ref: ref_type('SupplierQuoteInventoryAdoption')
    run_id: TextId
    organization_id: TextId
    source_ref: ref_type('SupplierQuoteInventorySource')
    source_sha256: Digest
    inventory_ref: ref_type('InventorySnapshot')
    adoption_evidence_refs: list[ref_type('Evidence')]
    author_action_id: Literal['SUPPLIER-A03']


def add_supplier_quote_inventory_schemas(schemas):
    schemas.register_kind('SupplierQuoteInventorySource', SupplierQuoteInventorySourceView, str)
    schemas.register_kind('SupplierQuoteInventoryAdoption', SupplierQuoteInventoryAdoptionView, str)
    schemas.register_kind('ProductBatch', SupplierQualityBatchView, str)
    return schemas


def prepare_supplier_quote_inventory(*, context, reading, adoption_ref, validate_current):
    """Retain original actual/committed values, status and coverage without summing.

    Host must verify the actual ledger, physical ownership/location, all current
    commitments and its declared coverage. MaterialBatch and normalized macro
    capacity records do not supply finished stock. Publish at a fresh token.
    """
    if (not isinstance(reading, ActionReadView) or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != 'SUPPLIER-A03' or not callable(validate_current)):
        raise ValueError('Inventory production requires original A03 reading and actual ledger validation')
    reading.check_method_context(context, 'SUPPLIER-A03')
    now = context.business_time

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise ValueError('Inventory production requires exact original concrete source versions')
        return row

    def current(row):
        if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now)):
            raise ValueError('Original inventory record/adoption/batch is unavailable now')

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
            raise ValueError('Inventory source/adoption lacks its original author authority')
        return [*grant.basis_refs, *assignment.basis_refs]

    try:
        adoption = read(Reference.model_validate(adoption_ref), SupplierQuoteInventoryAdoptionView)
        source = read(adoption.source_ref, SupplierQuoteInventorySourceView)
        current(adoption); current(source)
        if (adoption.run_id != context.run_id or source.run_id != context.run_id
                or adoption.organization_id != reading.organization_id
                or adoption.author_organization_id != reading.organization_id
                or source.organization_id != reading.organization_id or source.as_of != now
                or adoption.scope != context.scope or not scope_covers(source.scope, adoption.scope)
                or task_digest(source.model_dump(mode='json')) != adoption.source_sha256):
            raise ValueError('Inventory adoption changes original ledger, run, Supplier, scope or snapshot time')
        authority_refs = [*author(adoption, supplier=True), *author(source)]
        unique_refs([lot.batch_ref for lot in source.lots])
        batches, products, locations, dependency_digests, extra_evidence = [], [], [], {}, []
        physical_batches = set()
        for lot in source.lots:
            batch = read(lot.batch_ref, SupplierQualityBatchView)
            product = read(lot.product_ref, ProductSpecificationView)
            location = read(lot.location_ref, QuoteLocationView)
            current(batch)
            if (batch.organization_id != reading.organization_id or batch.as_of != now or batch.product_ref != lot.product_ref
                    or Decimal(batch.actual_quantity.value) != Decimal(lot.actual.value) or batch.actual_quantity.unit != lot.actual.unit
                    or lot.status == 'usable' and batch.state != 'usable'
                    or product.supplier_organization_id != reading.organization_id
                    or product.quantity_unit != lot.actual.unit or not product.effective_window.contains(now)):
                raise ValueError('Finished stock changes native batch quantity/product/unit or usable status')
            if batch.physical_batch_key in physical_batches:
                raise ValueError('Finished inventory repeats an original physical batch under different refs')
            physical_batches.add(batch.physical_batch_key)
            batches.append(batch.model_copy(deep=True)); products.append(product.model_copy(deep=True))
            locations.append(location.model_copy(deep=True))
            for row in (batch, product, location):
                dependency_digests[row.ref.key()] = {'ref': row.ref.model_dump(mode='json'),
                    'sha256': task_digest(row.model_dump(mode='json'))}
                extra_evidence.extend(row.evidence_refs)
        unique_refs(adoption.adoption_evidence_refs)
        if not adoption.adoption_evidence_refs:
            raise ValueError('Inventory snapshot requires independent Supplier adoption evidence')
        source_evidence = [*source.evidence_refs, source.original_record_evidence_ref,
            *(ref for ref in walk_references(source.lots) if ref.kind == 'Evidence')]
        if set(adoption.adoption_evidence_refs).intersection(source_evidence):
            raise ValueError('Original inventory ledger evidence cannot replace independent adoption')
        evidence_refs = list({ref.key(): ref for ref in [*source_evidence, *extra_evidence,
            *adoption.evidence_refs, *adoption.adoption_evidence_refs, *authority_refs]}.values())
        for ref in evidence_refs:
            evidence = read(ref, EvidenceRecord)
            if (evidence.effective_window is not None and not evidence.effective_window.contains(now)
                    or ref in [source.original_record_evidence_ref, *adoption.adoption_evidence_refs]
                    and evidence.basis_kind != 'observed'
                    or ref == source.original_record_evidence_ref and evidence.content_hash != source.original_record_sha256):
                raise ValueError('Actual inventory ledger and independent adoption require current observed evidence')
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        if (adoption.inventory_ref not in context.visible_refs or not any(isinstance(grant, Authorization)
                and grant.organization_id == reading.organization_id and grant.actor_id == context.actor_id
                and grant.function_ref == context.function_ref and 'SUPPLIER-A03' in grant.action_ids
                and grant.validity.contains(now) and adoption.inventory_ref in grant.readable_refs
                and any(scope_covers(scope, context.scope) for scope in grant.scopes) for grant in grants)):
            raise ValueError('Produced inventory target lacks original explicit current read authority')
        if validate_current(context=context.model_copy(deep=True), adoption=adoption.model_copy(deep=True),
                source=source.model_copy(deep=True), batches=batches, products=products, locations=locations) is not True:
            raise ValueError('Actual finished stock ownership/location/commitments and coverage require host verification')
        projection = QuoteInventoryView(ref=adoption.inventory_ref, organization_id=reading.organization_id,
            as_of=source.as_of, coverage=source.coverage,
            lots=[lot.model_copy(deep=True) for lot in source.lots], evidence_refs=evidence_refs)
        return {'kind': 'prepared', 'inventory_projection': projection,
            'inventory_sha256': task_digest(projection.model_dump(mode='json')),
            'source_sha256': adoption.source_sha256, 'original_record_sha256': source.original_record_sha256,
            'adoption_sha256': task_digest(adoption.model_dump(mode='json')),
            'context_sha256': task_digest(context.model_dump(mode='json')),
            'dependency_digests': list(dependency_digests.values()),
            'source_mode': 'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
            'limitations': ['Snapshot only; publish at a fresh authorized read token.',
                'No stock from material/capacity records; original commitments/status/coverage retained.']}
    finally:
        reading.recheck()
