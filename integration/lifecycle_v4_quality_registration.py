"""Bind independent quality release declarations to an existing original A07 result."""
import argparse
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from integration.lifecycle_v4_logistics_connection import _read
from integration.lifecycle_v4_quality_connection import assemble_v4_quality_connection
from integration.sessions import atomic_json
from integration.supplier_quality_handoff import SupplierQualityHandoffBasisView, SupplierQualityReleaseRecordView
from integration.supplier_quality_logistics_fixture_sources import (
    DeclaredProfessionalReleaseConfirmation, DeclaredQualityDispatchRegistration,
)
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import Measured, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_logistics_objects import SupplierDispatchableView, SupplierDispatchReleaseView
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView
from src.coordination.tasks import TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredQualityRelationSeed(GovReviewAuthored):
    ref: ref_type('SupplierQualityHandoffBasis')
    run_id: TextId
    organization_id: TextId
    release_record_ref: ref_type('SupplierQualityReleaseRecord')
    dispatchable_refs: Annotated[list[ref_type('DispatchableBatch')], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A08']


class DeclaredQualityReleaseRecordSeed(CostSource):
    ref: ref_type('SupplierQualityReleaseRecord')
    run_id: TextId
    organization_id: TextId
    original_batch_ref: ref_type('ProductBatch')
    current_batch_ref: ref_type('ProductBatch')
    release_ref: ref_type('DispatchRelease')
    status: Literal['released']
    released_quantity: Measured
    professional_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    native_record_evidence_ref: ref_type('Evidence')


class QualityConnectionSeed(StrictRecord):
    schema_version: Literal['lifecycle-v4-quality-connection-seed.v1']
    scenario_id: Literal['V4']
    origin: Literal['synthetic']
    status: Literal['awaiting_original_quality_result']
    quality_input_path: TextId
    quality_input_sha256: Digest
    logistics_input_path: TextId
    logistics_input_sha256: Digest
    registration_id: TextId
    relation: DeclaredQualityRelationSeed
    release_record: DeclaredQualityReleaseRecordSeed
    batch: SupplierQualityBatchView
    release: SupplierDispatchReleaseView
    dispatchables: Annotated[list[SupplierDispatchableView], Field(min_length=1)]
    confirmation: DeclaredProfessionalReleaseConfirmation
    native_record: dict
    assumptions: Annotated[list[TextId], Field(min_length=1)]


def bind_v4_quality_registration(*, seed_path, quality_result_path, output_directory):
    seed_file, result_file = _read(seed_path), _read(quality_result_path)
    seed = QualityConnectionSeed.model_validate(seed_file[2])
    quality_file, logistics_file = _read(seed.quality_input_path), _read(seed.logistics_input_path)
    inputs = (seed_file, result_file, quality_file, logistics_file)
    if quality_file[1] != seed.quality_input_sha256 or logistics_file[1] != seed.logistics_input_sha256:
        raise ValueError('Quality seed changes its declared original inputs')
    output = result_file[2]
    identity = TaskIdentity(**output['execution_evidence']['identity'])
    if (identity.action_id != 'SUPPLIER-A07' or identity.role != 'Supplier'
            or identity.run_id != seed.relation.run_id or identity.organization_id != seed.relation.organization_id):
        raise ValueError('Quality seed requires an original same-run saved A07 result')
    quality_source = quality_file[2]['steps'][0]['configuration']['settings']['source_settings']
    record = read_original_supplier_result(journal_path=quality_source['journal_path'], output=output, identity=identity)
    original_rows = [row for row in record['source_reading']
        if Reference.model_validate(row['ref']) == seed.release_record.original_batch_ref]
    if len(original_rows) != 1:
        raise ValueError('Quality seed lacks the exact original retained batch projection')
    original = SupplierQualityBatchView.model_validate(original_rows[0]['projection'])
    if (len({row.ref.id for row in seed.dispatchables}) != len(seed.dispatchables)
            or {row.ref for row in seed.dispatchables} != set(seed.relation.dispatchable_refs)):
        raise ValueError('Quality seed must declare each selected dispatchable exactly once')
    expected_native = {'schema_version': 'supplier-native-quality-release-observation.v1', 'run_id': identity.run_id,
        'batch': seed.batch.model_dump(mode='json'), 'release': seed.release.model_dump(mode='json'),
        'confirmation': seed.confirmation.model_dump(mode='json')}
    if seed.native_record != expected_native:
        raise ValueError('Quality seed changes independently declared professional/native release content')
    source = SupplierQualityReleaseRecordView.model_validate({**seed.release_record.model_dump(mode='json'),
        'original_batch_sha256': task_digest(original.model_dump(mode='json')),
        'current_batch_sha256': task_digest(seed.batch.model_dump(mode='json')),
        'release_sha256': task_digest(seed.release.model_dump(mode='json')),
        'quality_result_sha256': record['result_sha256'], 'native_record_sha256': task_digest(seed.native_record)})
    basis = SupplierQualityHandoffBasisView.model_validate({**seed.relation.model_dump(mode='json'),
        'quality_task_sha256': identity.key, 'quality_record_sha256': record['record_sha256'],
        'quality_result_sha256': record['result_sha256'], 'quality_audit_sha256': task_digest(record['audit']),
        'quality_source_reading_sha256': record['source_reading_sha256'],
        'release_record_sha256': task_digest(source.model_dump(mode='json')),
        'dispatchable_sha256s': {row.ref.id: task_digest(row.model_dump(mode='json')) for row in seed.dispatchables}})
    seed_data = seed.model_dump(mode='json')
    registration = DeclaredQualityDispatchRegistration.model_validate({
        'schema_version': 'supplier-quality-dispatch-registration.v1', 'registration_id': seed.registration_id,
        'basis': basis.model_dump(mode='json'), 'release_record': source.model_dump(mode='json'),
        **{name: seed_data[name] for name in ('batch', 'release', 'dispatchables', 'confirmation', 'native_record')},
        'current_state': 'released'})
    directory = Path(output_directory).resolve()
    journals = [Path(case[2]['steps'][0]['configuration']['settings']['source_settings']['journal_path']).resolve()
        for case in (quality_file, logistics_file)]
    if any(directory == journal.parent or directory in journal.parent.parents or journal.parent in directory.parents
            for journal in journals):
        raise ValueError('Quality binding output must be separate from original action journals')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed',
        'inputs': [{'path': str(path), 'sha256': digest} for path, digest, _ in inputs]}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Quality binding original inputs changed before assembly')
        registration_path = directory / 'registration.json'
        atomic_json(registration_path, registration.model_dump(mode='json'))
        assembly = assemble_v4_quality_connection(quality_result_path=result_file[0], quality_input_path=quality_file[0],
            logistics_input_path=logistics_file[0], registration_path=registration_path, output_directory=directory / 'assembly')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Quality binding original inputs changed during assembly')
        result = {**assembly, 'schema_version': 'lifecycle-v4-quality-registration-binding.v1',
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
    parser.add_argument('--quality-result', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    bind_v4_quality_registration(seed_path=args.seed, quality_result_path=args.quality_result, output_directory=args.output)


if __name__ == '__main__':
    main()
