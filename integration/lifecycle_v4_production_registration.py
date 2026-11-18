"""Bind independent production snapshots to actual saved original A06 evidence."""
import argparse
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from integration.lifecycle_v4_logistics_connection import _read
from integration.lifecycle_v4_production_connection import assemble_v4_production_connection
from integration.sessions import atomic_json
from integration.supplier_execution_handoff import SupplierExecutionHandoffBasisView
from integration.supplier_production_quality_fixture_sources import (
    DeclaredProductionConsumption, DeclaredProductionQualityRegistration,
)
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.supplier_execution_objects import (
    SupplierProductionRequestView, SupplierProductionExecutionView, SupplierStockMovementView,
)
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView
from src.coordination.tasks import TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredProductionBatchLinkSeed(StrictRecord):
    movement_ref: ref_type('StockMovement')
    batch_ref: ref_type('ProductBatch')


class DeclaredProductionRelationSeed(GovReviewAuthored):
    ref: ref_type('SupplierExecutionHandoffBasis')
    run_id: TextId
    organization_id: TextId
    production_execution_ref: ref_type('ProductionExecution')
    native_receipt_evidence_ref: ref_type('Evidence')
    output_links: Annotated[list[DeclaredProductionBatchLinkSeed], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A07']


class ProductionConnectionSeed(StrictRecord):
    schema_version: Literal['lifecycle-v4-production-connection-seed.v1']
    scenario_id: Literal['V4']
    origin: Literal['synthetic']
    status: Literal['awaiting_original_production_result']
    production_input_path: TextId
    production_input_sha256: Digest
    quality_input_path: TextId
    quality_input_sha256: Digest
    registration_id: TextId
    relation: DeclaredProductionRelationSeed
    request: SupplierProductionRequestView
    execution: SupplierProductionExecutionView
    movements: Annotated[list[SupplierStockMovementView], Field(min_length=1)]
    batches: Annotated[list[SupplierQualityBatchView], Field(min_length=1)]
    consumption_attributions: list[DeclaredProductionConsumption]
    native_receipt: dict
    assumptions: Annotated[list[TextId], Field(min_length=1)]


def bind_v4_production_registration(*, seed_path, production_result_path, output_directory):
    """Read original A06 provenance, bind declared snapshots and assemble A07 input."""
    seed_file, result_file = _read(seed_path), _read(production_result_path)
    seed = ProductionConnectionSeed.model_validate(seed_file[2])
    production_file, quality_file = _read(seed.production_input_path), _read(seed.quality_input_path)
    inputs = (seed_file, result_file, production_file, quality_file)
    if production_file[1] != seed.production_input_sha256 or quality_file[1] != seed.quality_input_sha256:
        raise ValueError('Production seed changes its declared original inputs')
    output = result_file[2]
    identity = TaskIdentity(**output['execution_evidence']['identity'])
    if (identity.action_id != 'SUPPLIER-A06' or identity.role != 'Supplier'
            or identity.run_id != seed.relation.run_id or identity.organization_id != seed.relation.organization_id):
        raise ValueError('Production seed requires original same-run saved A06 evidence')
    original_source = production_file[2]['steps'][0]['configuration']['settings']['source_settings']
    record = read_original_supplier_result(journal_path=original_source['journal_path'], output=output, identity=identity)
    movements = {row.ref.key(): row for row in seed.movements}
    batches = {row.ref.key(): row for row in seed.batches}
    links = seed.relation.output_links
    if (len(movements) != len(seed.movements) or len(batches) != len(seed.batches)
            or len({row.batch_ref.key() for row in links}) != len(links)
            or {row.batch_ref.key() for row in links} != set(batches)
            or {row.movement_ref.key() for row in links} !=
                {row.ref.key() for row in seed.movements if row.kind == 'pending_inspection_created'}
            or {row.ref for row in seed.movements} != set(seed.execution.movement_refs)
            or len(set(seed.execution.movement_refs)) != len(seed.execution.movement_refs)
            or seed.relation.production_execution_ref != seed.execution.ref
            or seed.execution.request_ref != seed.request.ref
            or seed.execution.request_sha256 != task_digest(seed.request.model_dump(mode='json'))):
        raise ValueError('Production seed changes complete native movement/output/request linkage')
    bound_links = [{**link.model_dump(mode='json'),
        'movement_sha256': task_digest(movements[link.movement_ref.key()].model_dump(mode='json')),
        'batch_sha256': task_digest(batches[link.batch_ref.key()].model_dump(mode='json'))} for link in links]
    expected_native = {'schema_version': 'supplier-native-production-receipt-observation.v1', 'run_id': identity.run_id,
        'request': seed.request.model_dump(mode='json'), 'execution': seed.execution.model_dump(mode='json'),
        'movements': [row.model_dump(mode='json') for row in seed.movements],
        'batches': [row.model_dump(mode='json') for row in seed.batches],
        'consumption_attributions': [row.model_dump(mode='json') for row in seed.consumption_attributions]}
    if seed.native_receipt != expected_native:
        raise ValueError('Production seed changes independently declared native receipt content')
    basis = SupplierExecutionHandoffBasisView.model_validate({**seed.relation.model_dump(mode='json'),
        'execution_task_sha256': identity.key, 'execution_record_sha256': record['record_sha256'],
        'execution_result_sha256': record['result_sha256'], 'execution_audit_sha256': task_digest(record['audit']),
        'execution_source_reading_sha256': record['source_reading_sha256'],
        'production_execution_sha256': task_digest(seed.execution.model_dump(mode='json')),
        'native_receipt_sha256': task_digest(seed.native_receipt), 'output_links': bound_links})
    seed_data = seed.model_dump(mode='json')
    registration = DeclaredProductionQualityRegistration.model_validate({
        'schema_version': 'supplier-production-quality-registration.v1', 'registration_id': seed.registration_id,
        'basis': basis.model_dump(mode='json'), 'current_state': 'recorded',
        **{key: seed_data[key] for key in ('request', 'execution', 'movements', 'batches', 'consumption_attributions', 'native_receipt')}})
    directory = Path(output_directory).resolve()
    journals = [Path(case[2]['steps'][0]['configuration']['settings']['source_settings']['journal_path']).resolve()
        for case in (production_file, quality_file)]
    if any(directory == journal.parent or directory in journal.parent.parents or journal.parent in directory.parents
            for journal in journals):
        raise ValueError('Production binding output must be separate from original action journals')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed',
        'inputs': [{'path': str(path), 'sha256': digest} for path, digest, _ in inputs]}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Production binding original inputs changed before assembly')
        registration_path = directory / 'registration.json'
        atomic_json(registration_path, registration.model_dump(mode='json'))
        assembly = assemble_v4_production_connection(production_result_path=result_file[0], production_input_path=production_file[0],
            quality_input_path=quality_file[0], registration_path=registration_path, output_directory=directory / 'assembly')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Production binding original inputs changed during assembly')
        result = {**assembly, 'schema_version': 'lifecycle-v4-production-registration-binding.v1',
            'status': 'bound_unverified', 'seed_sha256': seed_file[1]}
        atomic_json(directory / 'binding.json', result)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return result
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', required=True, type=Path)
    parser.add_argument('--production-result', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    bind_v4_production_registration(seed_path=args.seed, production_result_path=args.production_result, output_directory=args.output)


if __name__ == '__main__':
    main()
