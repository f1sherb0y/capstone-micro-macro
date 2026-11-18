"""Relate saved A06 requests and actual production receipts to A07 batches."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_execution_results import SavedSupplierExecution
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_execution_objects import (
    SupplierProductionExecutionView, SupplierProductionRequestView, SupplierStockMovementView,
    SupplierExecutionTaskView, validate_supplier_reconciliation_task,
)
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView, supplier_quality_schemas
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierProductionBatchLink(StrictRecord):
    movement_ref: ref_type('StockMovement')
    movement_sha256: Digest
    batch_ref: ref_type('ProductBatch')
    batch_sha256: Digest


class SupplierExecutionHandoffBasisView(GovReviewAuthored):
    """Explicit actual receipt-to-batch relation; no production or quality approval."""
    ref: ref_type('SupplierExecutionHandoffBasis')
    run_id: TextId
    organization_id: TextId
    execution_task_sha256: Digest
    execution_record_sha256: Digest
    execution_result_sha256: Digest
    execution_audit_sha256: Digest
    execution_source_reading_sha256: Digest
    production_execution_ref: ref_type('ProductionExecution')
    production_execution_sha256: Digest
    native_receipt_sha256: Digest
    native_receipt_evidence_ref: ref_type('Evidence')
    output_links: Annotated[list[SupplierProductionBatchLink], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A07']


def supplier_execution_handoff_schemas():
    schemas = supplier_quality_schemas()
    for kind, schema in [('ProductionExecution', SupplierProductionExecutionView),
            ('ProductionRequest', SupplierProductionRequestView), ('StockMovement', SupplierStockMovementView),
            ('SupplierExecutionHandoffBasis', SupplierExecutionHandoffBasisView)]:
        schemas.register_kind(kind, schema, str)
    return schemas


def prepare_supplier_execution_handoff(saved, *, context, reading, basis_ref, batch_ref, validate_current):
    """Verify recorded production and every pending-inspection output without promoting usability."""
    if (not isinstance(saved, SavedSupplierExecution) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A07'
            or not callable(validate_current)):
        raise ValueError('Execution handoff requires saved original A06 and actual authorized A07 reading')
    reading.check_method_context(context, 'SUPPLIER-A07')
    if (saved.current_context != context or saved.identity.action_id != 'SUPPLIER-A06'
            or saved.identity.role != 'Supplier' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Execution handoff changes original Supplier, task, input/context or retained sources')
    if saved.result.kind != 'completed' or saved.result.payload.choice not in {'execute', 'rebalance', 'reconcile_execution'}:
        return {'kind': 'needs_information', 'missing_fields': ['original_production_request_or_reconciliation'],
            'requested_refs': [saved.action_input.task_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A06',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(k) != v for k, v in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Execution handoff lacks original successful authorized audit')
    now = context.business_time

    def read(ref, schema, *, current=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise ValueError('Production lineage requires exact concrete source versions')
        if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or current and not row.effective_window.contains(now)):
            raise ValueError('Production source is unavailable at the current read time')
        return row

    def evidence_at(refs, at):
        if at is not None and (at.clock_ref != now.clock_ref or at.offset > now.offset):
            raise ValueError('Production evidence changes original use clock or time')
        for ref in {ref.key(): ref for ref in refs}.values():
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                raise ValueError('Production relation requires original typed authorized evidence')
            if row.effective_window is not None and (
                    row.effective_window.start.clock_ref != now.clock_ref
                    or row.effective_window.start.offset > now.offset
                    or at is not None and not row.effective_window.contains(at)):
                raise ValueError('Production evidence is unavailable or invalid at its actual use time')

    def original_task(ref):
        matches = [row['projection'] for row in saved.source_reading
            if Reference.model_validate(row['ref']).key() == ref.key()]
        if len(matches) != 1:
            raise ValueError('Production reconciliation lacks its exact retained original task version')
        row = SupplierExecutionTaskView.model_validate(matches[0])
        if row.ref != ref:
            raise ValueError('Production reconciliation substitutes a retained task reference')
        return row

    try:
        basis = read(Reference.model_validate(basis_ref), SupplierExecutionHandoffBasisView, current=True)
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'execution_task_sha256': saved.identity.key, 'execution_record_sha256': saved.record_sha256,
            'execution_result_sha256': result_sha, 'execution_audit_sha256': task_digest(saved.audit),
            'execution_source_reading_sha256': saved.source_reading_sha256}
        if any(getattr(basis, k) != v for k, v in expected.items()):
            raise ValueError('Execution relation substitutes original saved evidence')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(s, basis.scope) for s in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Execution relation lacks original independent Supplier authority')
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                evidence_at([ref], basis.authored_at)
            else:
                reading.resolve(ref)
        execution = read(basis.production_execution_ref, SupplierProductionExecutionView)
        if (task_digest(execution.model_dump(mode='json')) != basis.production_execution_sha256
                or execution.run_id != context.run_id or execution.organization_id != reading.organization_id
                or execution.scope != saved.context.scope):
            raise ValueError('Actual production receipt changes original run, Supplier or task')
        if (execution.status != 'recorded' or execution.query_status != 'present'
                or execution.core_event_id is None or execution.recorded_at is None):
            return {'kind': 'needs_information', 'missing_fields': ['original_recorded_present_production_receipt'],
                'requested_refs': [execution.ref]}
        if (execution.recorded_at.clock_ref != now.clock_ref
                or execution.recorded_at.offset > execution.available_at.offset
                or execution.recorded_at.offset > now.offset):
            raise ValueError('Production receipt changes original clock or is future')
        request = read(execution.request_ref, SupplierProductionRequestView)
        if (task_digest(request.model_dump(mode='json')) != execution.request_sha256
                or request.run_id != execution.run_id or request.organization_id != execution.organization_id
                or request.task_ref != execution.task_ref or request.operation_id != execution.operation_id
                or request.business_key != execution.business_key or request.scope != execution.scope):
            raise ValueError('Actual execution substitutes original submitted request')
        payload = saved.result.payload
        if payload.choice == 'reconcile_execution':
            if execution.ref not in payload.execution_refs:
                raise ValueError('Receipt is absent from the original explicit reconciliation selection')
            validate_supplier_reconciliation_task(original_task(execution.task_ref),
                original_task(saved.action_input.task_ref), execution,
                run_id=context.run_id, organization_id=reading.organization_id)
        else:
            setup = saved.action_input.execution_setup
            if (execution.task_ref != saved.action_input.task_ref
                    or execution.recorded_at.offset < saved.context.business_time.offset
                    or setup.kind != 'production' or request.operation_id != saved.context.operation_id
                    or request.release_ref != setup.release_ref or request.method_ref != setup.method_ref
                    or [i.model_dump(mode='json') for i in request.inputs] != [i.model_dump(mode='json') for i in payload.inputs]
                    or [r.model_dump(mode='json') for r in request.resources] != [r.model_dump(mode='json') for r in payload.resources]):
                raise ValueError('Submitted production request changes original local inputs, resources, release or operation')
        unique_refs(execution.movement_refs)
        unique_refs(list({link.movement_ref.key(): link.movement_ref for link in basis.output_links}.values()))
        unique_refs([link.batch_ref for link in basis.output_links])
        movements = [read(ref, SupplierStockMovementView) for ref in execution.movement_refs]
        if (any(row.organization_id != reading.organization_id or row.execution_ref != execution.ref
                or row.core_event_id != execution.core_event_id or row.scope != execution.scope
                or row.available_at.offset < execution.recorded_at.offset for row in movements)
                or len({row.physical_movement_key for row in movements}) != len(movements)):
            raise ValueError('Stock movement changes or duplicates original execution/event/physical identity')
        outputs = {row.ref.key(): row for row in movements if row.kind == 'pending_inspection_created'}
        if {link.movement_ref.key() for link in basis.output_links} != set(outputs):
            raise ValueError('Batch relation must cover all and only original pending-inspection outputs')
        batches, quantities = [], {}
        for link in basis.output_links:
            movement = outputs[link.movement_ref.key()]
            batch = read(link.batch_ref, SupplierQualityBatchView, current=True)
            if (task_digest(movement.model_dump(mode='json')) != link.movement_sha256
                    or task_digest(batch.model_dump(mode='json')) != link.batch_sha256
                    or batch.organization_id != reading.organization_id or batch.as_of != now
                    or batch.actual_quantity.unit != movement.quantity.unit
                    or not Decimal('0') <= Decimal(batch.actual_quantity.value) <= Decimal(movement.quantity.value)):
                raise ValueError('Batch relation changes current native batch or original output quantity/unit')
            batches.append(batch.model_copy(deep=True))
            key = movement.ref.key()
            quantities[key] = quantities.get(key, Fraction()) + Fraction(Decimal(batch.actual_quantity.value))
            if quantities[key] > Fraction(Decimal(movement.quantity.value)):
                raise ValueError('Linked physical batches exceed the original output movement quantity')
        if (len({batch.physical_batch_key for batch in batches}) != len(batches)
                or Reference.model_validate(batch_ref) not in [batch.ref for batch in batches]):
            raise ValueError('Selected quality batch is absent or duplicates an original physical output')
        unique_refs(basis.relation_evidence_refs)
        if basis.native_receipt_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Native receipt evidence cannot replace independent batch relation')
        evidence_at([*basis.evidence_refs, *basis.relation_evidence_refs], basis.authored_at)
        for ref in basis.relation_evidence_refs:
            if reading.resolve(ref).basis_kind != 'observed':
                raise ValueError('Batch relation requires independently observed original evidence')
        evidence_at([basis.native_receipt_evidence_ref, *execution.evidence_refs,
            *[ref for row in movements for ref in [*row.evidence_refs, row.quantity.basis_ref]]], execution.recorded_at)
        # ProductionRequest has no actual submission timestamp. Keep its
        # historical evidence without inferring submission from availability.
        evidence_at(request.evidence_refs, None)
        evidence_at([ref for row in batches for ref in [*row.evidence_refs, row.actual_quantity.basis_ref]], now)
        native = reading.resolve(basis.native_receipt_evidence_ref)
        if native.basis_kind != 'observed' or native.content_hash != basis.native_receipt_sha256:
            raise ValueError('Native production receipt changes original observed content')
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True), basis=basis.model_copy(deep=True),
                execution=execution.model_copy(deep=True), request=request.model_copy(deep=True),
                movements=deepcopy(movements), batches=batches) is not True:
            raise ValueError('Actual receipt/material-to-product lineage and current batch changes require host verification')
        return {'kind': 'prepared', 'batch_ref': Reference.model_validate(batch_ref),
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'execution_record_sha256': saved.record_sha256,
            'execution_result_sha256': result_sha, 'production_execution_sha256': basis.production_execution_sha256,
            'native_receipt_sha256': basis.native_receipt_sha256,
            'limitations': ['Source relation only; no output batch, inspection approval or usable stock is created.']}
    finally:
        reading.recheck()
