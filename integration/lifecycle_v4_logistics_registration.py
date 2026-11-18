"""Bind declared transport relations to saved A08 evidence without executing actions."""
import argparse
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from integration.lifecycle_v4_logistics_connection import _read, assemble_v4_logistics_connection
from integration.sessions import atomic_json
from integration.supplier_logistics_handoff import SupplierLogisticsHandoffBasisView
from integration.supplier_logistics_receiving_fixture_sources import (
    DeclaredLogisticsReceivingRegistration, DeclaredNativeShipmentObservation,
)
from src.actions.contracts.common import StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.coordination.tasks import TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredShipmentSourceLinkSeed(StrictRecord):
    plan_index: Annotated[int, Field(ge=0)] | None
    shipment_ref: ref_type('Shipment')
    native_record_evidence_ref: ref_type('Evidence')


class DeclaredLogisticsRelationSeed(GovReviewAuthored):
    ref: ref_type('SupplierLogisticsHandoffBasis')
    run_id: TextId
    organization_id: TextId
    shipment_links: Annotated[list[DeclaredShipmentSourceLinkSeed], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A09']


class LogisticsConnectionSeed(StrictRecord):
    schema_version: Literal['lifecycle-v4-logistics-connection-seed.v1']
    scenario_id: Literal['V4']
    origin: Literal['synthetic']
    status: Literal['awaiting_original_logistics_result']
    logistics_input_path: TextId
    logistics_input_sha256: Digest
    receiving_input_path: TextId
    receiving_input_sha256: Digest
    registration_id: TextId
    relation: DeclaredLogisticsRelationSeed
    observations: Annotated[list[DeclaredNativeShipmentObservation], Field(min_length=1)]
    assumptions: Annotated[list[TextId], Field(min_length=1)]


def bind_v4_logistics_registration(*, seed_path, logistics_result_path, output_directory):
    """Fill saved provenance digests, then let the assembler verify the original journal."""
    seed_file, result_file = _read(seed_path), _read(logistics_result_path)
    seed = LogisticsConnectionSeed.model_validate(seed_file[2])
    logistics_file, receiving_file = _read(seed.logistics_input_path), _read(seed.receiving_input_path)
    inputs = (seed_file, result_file, logistics_file, receiving_file)
    if logistics_file[1] != seed.logistics_input_sha256 or receiving_file[1] != seed.receiving_input_sha256:
        raise ValueError('Logistics seed changes its declared original inputs')
    output = result_file[2]
    evidence = output['execution_evidence']
    identity = TaskIdentity(**evidence['identity'])
    if (identity.action_id != 'SUPPLIER-A08' or identity.role != 'Supplier'
            or identity.run_id != seed.relation.run_id or identity.organization_id != seed.relation.organization_id
            or output['result']['kind'] != 'completed' or evidence['result_table'] != 'supplier_logistics_results'):
        raise ValueError('Logistics seed requires an original same-run saved A08 result')
    observations = {row.shipment.ref.key(): row for row in seed.observations}
    links = seed.relation.shipment_links
    if (len(observations) != len(seed.observations) or len({row.shipment_ref.key() for row in links}) != len(links)
            or set(observations) != {row.shipment_ref.key() for row in links}):
        raise ValueError('Logistics seed must declare each original shipment exactly once')
    bound_links = []
    for link in links:
        observation = observations[link.shipment_ref.key()]
        expected_native = {'schema_version': 'supplier-native-shipment-observation.v1',
            'run_id': identity.run_id, 'shipment': observation.shipment.model_dump(mode='json')}
        if observation.native_record != expected_native:
            raise ValueError('Logistics seed changes independently declared native shipment content')
        bound_links.append({**link.model_dump(mode='json'),
            'shipment_sha256': task_digest(observation.shipment.model_dump(mode='json')),
            'native_record_sha256': task_digest(observation.native_record)})
    basis = SupplierLogisticsHandoffBasisView.model_validate({**seed.relation.model_dump(mode='json'),
        'shipment_links': bound_links, 'logistics_task_sha256': identity.key,
        'logistics_record_sha256': evidence['record_sha256'],
        'logistics_result_sha256': task_digest(output['result']),
        'logistics_audit_sha256': task_digest(evidence['saved_audit']),
        'logistics_source_reading_sha256': evidence['source_reading_sha256']})
    registration = DeclaredLogisticsReceivingRegistration.model_validate({
        'schema_version': 'supplier-logistics-receiving-registration.v1',
        'registration_id': seed.registration_id, 'basis': basis.model_dump(mode='json'),
        'observations': [row.model_dump(mode='json') for row in seed.observations], 'current_state': 'observed'})
    directory = Path(output_directory).resolve()
    journals = [Path(case[2]['steps'][0]['configuration']['settings']['source_settings']['journal_path']).resolve()
        for case in (logistics_file, receiving_file)]
    if any(directory == journal.parent or directory in journal.parent.parents or journal.parent in directory.parents
            for journal in journals):
        raise ValueError('Logistics binding output must be separate from original action journals')
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
        raise ValueError('Original logistics binding inputs changed before assembly')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed',
        'inputs': [{'path': str(path), 'sha256': digest} for path, digest, _ in inputs]}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        registration_path = directory / 'registration.json'
        atomic_json(registration_path, registration.model_dump(mode='json'))
        assembly = assemble_v4_logistics_connection(logistics_result_path=result_file[0],
            logistics_input_path=logistics_file[0], receiving_input_path=receiving_file[0],
            registration_path=registration_path, output_directory=directory / 'assembly')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Original logistics binding inputs changed during assembly')
        result = {**assembly, 'schema_version': 'lifecycle-v4-logistics-registration-binding.v1',
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
    parser.add_argument('--logistics-result', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    bind_v4_logistics_registration(seed_path=args.seed, logistics_result_path=args.logistics_result,
        output_directory=args.output)


if __name__ == '__main__':
    main()
