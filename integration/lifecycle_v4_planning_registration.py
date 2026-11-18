"""Bind independently declared native task formation to actual saved A05 evidence."""
import argparse
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from integration.lifecycle_v4_logistics_connection import _read
from integration.lifecycle_v4_planning_connection import assemble_v4_planning_connection
from integration.sessions import atomic_json
from integration.supplier_planning_handoff import SupplierPlanningHandoffBasisView, SupplierTaskFormationRecordView
from integration.supplier_planning_production_fixture_sources import (
    FormedPlanningTask, DeclaredPlanningProductionRegistration,
)
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.coordination.tasks import TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredPlanningRelationSeed(GovReviewAuthored):
    ref: ref_type('SupplierPlanningHandoffBasis')
    run_id: TextId
    organization_id: TextId
    formation_record_ref: ref_type('SupplierTaskFormationRecord')
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A06']


class PlanningConnectionSeed(StrictRecord):
    schema_version: Literal['lifecycle-v4-planning-connection-seed.v1']
    scenario_id: Literal['V4']
    origin: Literal['synthetic']
    status: Literal['awaiting_original_planning_result']
    planning_input_path: TextId
    planning_input_sha256: Digest
    production_input_path: TextId
    production_input_sha256: Digest
    registration_id: TextId
    relation: DeclaredPlanningRelationSeed
    formation_record: SupplierTaskFormationRecordView
    tasks: Annotated[list[FormedPlanningTask], Field(min_length=1)]
    recorded_at: TimePoint
    producer: Literal['core']
    native_record: dict
    assumptions: Annotated[list[TextId], Field(min_length=1)]


def bind_v4_planning_registration(*, seed_path, planning_result_path, output_directory):
    """Attach actual saved digests; create no tasks, release, stock or production."""
    seed_file, result_file = _read(seed_path), _read(planning_result_path)
    seed = PlanningConnectionSeed.model_validate(seed_file[2])
    planning_file, production_file = _read(seed.planning_input_path), _read(seed.production_input_path)
    inputs = (seed_file, result_file, planning_file, production_file)
    if planning_file[1] != seed.planning_input_sha256 or production_file[1] != seed.production_input_sha256:
        raise ValueError('Planning seed changes declared original inputs')
    output = result_file[2]
    identity = TaskIdentity(**output['execution_evidence']['identity'])
    if (identity.action_id != 'SUPPLIER-A05' or identity.role != 'Supplier' or identity.purpose != 'action'
            or identity.run_id != seed.relation.run_id or identity.organization_id != seed.relation.organization_id):
        raise ValueError('Planning seed requires actual original same-run A05 evidence')
    original_source = planning_file[2]['steps'][0]['configuration']['settings']['source_settings']
    record = read_original_supplier_result(journal_path=original_source['journal_path'], output=output, identity=identity)
    formation = seed.formation_record
    if (seed.relation.formation_record_ref != formation.ref or formation.run_id != identity.run_id
            or formation.organization_id != identity.organization_id):
        raise ValueError('Planning seed substitutes native formation identity')
    expected_native = {'schema_version': 'supplier-native-task-formation-observation.v1', 'run_id': identity.run_id,
        'work_authority_ref': formation.work_authority_ref.model_dump(mode='json'),
        'recorded_at': seed.recorded_at.model_dump(mode='json'), 'producer': seed.producer,
        'formation_lines': [row.model_dump(mode='json') for row in formation.lines],
        'tasks': [row.model_dump(mode='json') for row in seed.tasks]}
    if seed.native_record != expected_native or task_digest(expected_native) != formation.native_source_sha256:
        raise ValueError('Planning seed changes independent native task/method/material content')
    basis = SupplierPlanningHandoffBasisView.model_validate({**seed.relation.model_dump(mode='json'),
        'planning_task_sha256': identity.key, 'planning_record_sha256': record['record_sha256'],
        'planning_result_sha256': record['result_sha256'], 'planning_audit_sha256': task_digest(record['audit']),
        'planning_source_reading_sha256': record['source_reading_sha256'],
        'formation_record_sha256': task_digest(formation.model_dump(mode='json'))})
    registration = DeclaredPlanningProductionRegistration.model_validate({
        'schema_version': 'supplier-planning-production-registration.v1', 'registration_id': seed.registration_id,
        'basis': basis.model_dump(mode='json'), 'formation_record': formation.model_dump(mode='json'),
        'tasks': [row.model_dump(mode='json') for row in seed.tasks], 'recorded_at': seed.recorded_at.model_dump(mode='json'),
        'producer': seed.producer, 'native_record': seed.native_record, 'current_state': 'recorded'})
    directory = Path(output_directory).resolve()
    journals = [Path(case[2]['steps'][0]['configuration']['settings']['source_settings']['journal_path']).resolve()
        for case in (planning_file, production_file)]
    if any(directory == journal.parent or directory in journal.parent.parents or journal.parent in directory.parents
            for journal in journals):
        raise ValueError('Planning binding output must be separate from action journals')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed',
        'inputs': [{'path': str(path), 'sha256': digest} for path, digest, _ in inputs]}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Planning binding original inputs changed before assembly')
        registration_path = directory / 'registration.json'
        atomic_json(registration_path, registration.model_dump(mode='json'))
        assembly = assemble_v4_planning_connection(planning_result_path=result_file[0], planning_input_path=planning_file[0],
            production_input_path=production_file[0], registration_path=registration_path, output_directory=directory / 'assembly')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Planning binding original inputs changed during assembly')
        result = {**assembly, 'schema_version': 'lifecycle-v4-planning-registration-binding.v1',
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
    parser.add_argument('--planning-result', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    bind_v4_planning_registration(seed_path=args.seed, planning_result_path=args.planning_result, output_directory=args.output)


if __name__ == '__main__':
    main()
