"""Bind saved A07 decisions to actual independently confirmed dispatch release."""
from copy import deepcopy
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_quality_results import SavedSupplierQuality
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Known, Measured, Reference, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_logistics_objects import SupplierDispatchableView, SupplierDispatchReleaseView, supplier_logistics_schemas
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierQualityReleaseRecordView(CostSource):
    """Existing host release record, including independent professional confirmations."""
    ref: ref_type('SupplierQualityReleaseRecord')
    run_id: TextId
    organization_id: TextId
    original_batch_ref: ref_type('ProductBatch')
    original_batch_sha256: Digest
    current_batch_ref: ref_type('ProductBatch')
    current_batch_sha256: Digest
    release_ref: ref_type('DispatchRelease')
    release_sha256: Digest
    quality_result_sha256: Digest
    status: Literal['released', 'pending', 'rejected', 'revoked']
    released_quantity: Measured
    professional_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    native_record_sha256: Digest
    native_record_evidence_ref: ref_type('Evidence')


class SupplierQualityHandoffBasisView(GovReviewAuthored):
    ref: ref_type('SupplierQualityHandoffBasis')
    run_id: TextId
    organization_id: TextId
    quality_task_sha256: Digest
    quality_record_sha256: Digest
    quality_result_sha256: Digest
    quality_audit_sha256: Digest
    quality_source_reading_sha256: Digest
    release_record_ref: ref_type('SupplierQualityReleaseRecord')
    release_record_sha256: Digest
    dispatchable_refs: Annotated[list[ref_type('DispatchableBatch')], Field(min_length=1)]
    dispatchable_sha256s: dict[TextId, Digest]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A08']


def supplier_quality_handoff_schemas():
    schemas = supplier_logistics_schemas()
    schemas.register_kind('SupplierQualityReleaseRecord', SupplierQualityReleaseRecordView, str)
    schemas.register_kind('SupplierQualityHandoffBasis', SupplierQualityHandoffBasisView, str)
    return schemas


def prepare_supplier_quality_handoff(saved, *, context, reading, basis_ref, dispatchable_refs, validate_current):
    """Keep historical quality decisions separate from actual current dispatch rights.

    validate_current must authenticate each professional confirmation/closure
    and its evidence at the actual original event time, as well as current
    native release/history. The release projection alone has no such times.
    """
    if (not isinstance(saved, SavedSupplierQuality) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A08'
            or not callable(validate_current)):
        raise ValueError('Quality handoff requires original saved A07 and actual authorized A08 reading')
    reading.check_method_context(context, 'SUPPLIER-A08')
    if (saved.current_context != context or saved.identity.action_id != 'SUPPLIER-A07'
            or saved.identity.role != 'Supplier' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Quality handoff changes original Supplier, task, input/context or sources')
    if saved.result.kind != 'completed':
        return {'kind': 'needs_information', 'missing_fields': ['completed_original_quality_decision'],
            'requested_refs': [saved.action_input.batch_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A07',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(k) != v for k, v in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Quality handoff lacks its original successful authorized audit')
    now = context.business_time

    def read(ref, schema):
        row = reading.resolve(ref)
        if (not isinstance(row, schema) or row.ref != ref or row.available_at.clock_ref != now.clock_ref
                or row.available_at.offset > now.offset or not row.effective_window.contains(now)):
            raise ValueError('Quality release requires exact current concrete source versions')
        return row

    def evidence_at(refs, at, *, observed=False):
        if at is not None and (at.clock_ref != now.clock_ref or at.offset > now.offset):
            raise ValueError('Quality release evidence changes its actual use clock or time')
        for ref in {ref.key(): ref for ref in refs}.values():
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or observed and row.basis_kind != 'observed'
                    or row.effective_window is not None and (
                        row.effective_window.start.clock_ref != now.clock_ref
                        or row.effective_window.start.offset > now.offset
                        or at is not None and not row.effective_window.contains(at))):
                raise ValueError('Quality release evidence is unavailable or invalid at its actual use time')

    try:
        basis = read(Reference.model_validate(basis_ref), SupplierQualityHandoffBasisView)
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'quality_task_sha256': saved.identity.key, 'quality_record_sha256': saved.record_sha256,
            'quality_result_sha256': result_sha, 'quality_audit_sha256': task_digest(saved.audit),
            'quality_source_reading_sha256': saved.source_reading_sha256}
        if any(getattr(basis, k) != v for k, v in expected.items()):
            raise ValueError('Quality relation substitutes original saved evidence')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or grant.ref != basis.author_authority_ref
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(s, basis.scope) for s in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Quality relation lacks original independent Supplier author authority')
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                evidence_at([ref], basis.authored_at)
            else:
                reading.resolve(ref)
        originals = [row for row in saved.source_reading if Reference.model_validate(row['ref']) == saved.action_input.batch_ref]
        if len(originals) != 1:
            raise ValueError('Quality handoff lacks original retained batch')
        original = SupplierQualityBatchView.model_validate(originals[0]['projection'])
        source = read(basis.release_record_ref, SupplierQualityReleaseRecordView)
        batch = read(source.current_batch_ref, SupplierQualityBatchView)
        release = read(source.release_ref, SupplierDispatchReleaseView)
        if (task_digest(source.model_dump(mode='json')) != basis.release_record_sha256
                or source.run_id != context.run_id or source.organization_id != reading.organization_id
                or source.original_batch_ref != original.ref or source.original_batch_sha256 != task_digest(original.model_dump(mode='json'))
                or source.quality_result_sha256 != result_sha or batch.organization_id != reading.organization_id
                or batch.as_of != now or batch.physical_batch_key != original.physical_batch_key
                or batch.product_ref != original.product_ref or batch.owner_id != original.owner_id
                or task_digest(batch.model_dump(mode='json')) != source.current_batch_sha256
                or task_digest(release.model_dump(mode='json')) != source.release_sha256
                or release.batch_ref != batch.ref or release.physical_batch_key != batch.physical_batch_key
                or not scope_covers(source.scope, context.scope)):
            raise ValueError('Native quality release substitutes original batch lineage, ownership or current source')
        if source.status != 'released' or not isinstance(release.permitted, Known) or release.permitted.value is not True:
            return {'kind': 'needs_information', 'missing_fields': ['actual_independently_confirmed_dispatch_release'],
                'requested_refs': [source.ref, release.ref]}
        amounts = [source.released_quantity, release.quantity, batch.actual_quantity]
        if (len({q.unit for q in amounts}) != 1 or Decimal(source.released_quantity.value) != Decimal(release.quantity.value)
                or not Decimal('0') < Decimal(release.quantity.value) <= Decimal(batch.actual_quantity.value)):
            raise ValueError('Native release changes or exceeds current actual batch quantity')
        selected = [Reference.model_validate(ref) for ref in dispatchable_refs]
        unique_refs(selected); unique_refs(basis.dispatchable_refs)
        if (set(selected) != set(basis.dispatchable_refs)
                or set(basis.dispatchable_sha256s) != {ref.id for ref in selected}):
            raise ValueError('Quality relation substitutes explicitly selected dispatchable versions')
        dispatchables = [read(ref, SupplierDispatchableView) for ref in selected]
        for row in dispatchables:
            if (task_digest(row.model_dump(mode='json')) != basis.dispatchable_sha256s[row.ref.id]
                    or row.batch_ref != batch.ref or row.physical_batch_key != batch.physical_batch_key
                    or row.product_ref != batch.product_ref or row.release_ref != release.ref
                    or row.order_ref != release.order_ref or row.as_of != now):
                raise ValueError('Dispatchable source changes actual released batch, order or current version')
        unique_refs(source.professional_evidence_refs); unique_refs(basis.relation_evidence_refs)
        if set(basis.relation_evidence_refs).intersection([source.native_record_evidence_ref, *source.professional_evidence_refs]):
            raise ValueError('Native/professional release evidence cannot replace independent source relation')
        evidence_at(basis.evidence_refs, basis.authored_at)
        evidence_at(basis.relation_evidence_refs, basis.authored_at, observed=True)
        evidence_at([source.native_record_evidence_ref], now, observed=True)
        if reading.resolve(source.native_record_evidence_ref).content_hash != source.native_record_sha256:
            raise ValueError('Actual quality release changes original native observed content')
        # This public release projection has no professional event timestamps.
        # The independent host must authenticate each original confirmation and
        # defect closure at its real time; availability is not an event time.
        evidence_at(source.professional_evidence_refs, None, observed=True)
        evidence_at([*source.evidence_refs, *batch.evidence_refs, *release.evidence_refs,
            *[q.basis_ref for q in amounts], *[ref for row in dispatchables for ref in [
                *row.evidence_refs, row.actual_remaining.basis_ref, row.dispatchable_quantity.basis_ref]]], now)
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True), basis=basis.model_copy(deep=True),
                source=source.model_copy(deep=True), batch=batch.model_copy(deep=True),
                release=release.model_copy(deep=True), dispatchables=deepcopy(dispatchables)) is not True:
            raise ValueError('Actual professional confirmation, disposition history and release require host verification')
        return {'kind': 'prepared', 'dispatchable_refs': selected,
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'quality_record_sha256': saved.record_sha256,
            'quality_result_sha256': result_sha, 'release_record_sha256': basis.release_record_sha256,
            'native_release_sha256': source.native_record_sha256,
            'limitations': ['Source relation only; A08 retains original physical ledger, stock and dispatch permission checks.']}
    finally:
        reading.recheck()
