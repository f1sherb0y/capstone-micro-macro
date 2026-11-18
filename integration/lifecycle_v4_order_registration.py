"""Bind independent effective-order declarations to actual saved original A04."""
import argparse
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from integration.lifecycle_v4_logistics_connection import _read
from integration.lifecycle_v4_order_connection import assemble_v4_order_connection
from integration.sessions import atomic_json
from integration.supplier_order_handoff import (
    SupplierOrderHandoffBasisView, SupplierOrderFormationRecordView, SupplierOrderLineLink,
)
from integration.supplier_order_planning_fixture_sources import DeclaredOrderPartyConfirmation, DeclaredOrderPlanningRegistration
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.supplier_planning_objects import SupplierPlanningOrderView, SupplierPlanningOrderLineView, SupplierWorkAuthorityView
from src.coordination.tasks import TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredOrderRelationSeed(GovReviewAuthored):
    ref: ref_type('SupplierOrderHandoffBasis')
    run_id: TextId
    organization_id: TextId
    formation_record_ref: ref_type('SupplierOrderFormationRecord')
    line_links: Annotated[list[SupplierOrderLineLink], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A05']


class OrderConnectionSeed(StrictRecord):
    schema_version: Literal['lifecycle-v4-order-connection-seed.v1']
    scenario_id: Literal['V4']
    origin: Literal['synthetic']
    status: Literal['awaiting_original_order_result']
    order_input_path: TextId
    order_input_sha256: Digest
    planning_input_path: TextId
    planning_input_sha256: Digest
    registration_id: TextId
    relation: DeclaredOrderRelationSeed
    formation_record: SupplierOrderFormationRecordView
    order: SupplierPlanningOrderView
    lines: Annotated[list[SupplierPlanningOrderLineView], Field(min_length=1)]
    work_authority: SupplierWorkAuthorityView
    confirmations: Annotated[list[DeclaredOrderPartyConfirmation], Field(min_length=1)]
    recorded_at: TimePoint
    producer: Literal['core']
    native_record: dict
    assumptions: Annotated[list[TextId], Field(min_length=1)]


def bind_v4_order_registration(*, seed_path, order_result_path, output_directory):
    """Attach actual saved hashes and assemble A05 without creating any native facts."""
    seed_file, result_file = _read(seed_path), _read(order_result_path)
    seed = OrderConnectionSeed.model_validate(seed_file[2])
    order_file, planning_file = _read(seed.order_input_path), _read(seed.planning_input_path)
    inputs = (seed_file, result_file, order_file, planning_file)
    if order_file[1] != seed.order_input_sha256 or planning_file[1] != seed.planning_input_sha256:
        raise ValueError('Order seed changes declared original inputs')
    output = result_file[2]
    identity = TaskIdentity(**output['execution_evidence']['identity'])
    if (identity.action_id != 'SUPPLIER-A04' or identity.role != 'Supplier' or identity.purpose != 'action'
            or identity.run_id != seed.relation.run_id or identity.organization_id != seed.relation.organization_id):
        raise ValueError('Order seed requires actual original same-run saved A04 evidence')
    original_source = order_file[2]['steps'][0]['configuration']['settings']['source_settings']
    record = read_original_supplier_result(journal_path=original_source['journal_path'], output=output, identity=identity)
    formation = seed.formation_record
    if (seed.relation.formation_record_ref != formation.ref or formation.run_id != identity.run_id
            or formation.organization_id != identity.organization_id or formation.order_ref != seed.order.ref
            or record['result']['payload']['choice'] != 'accept'
            or formation.agreement_sha256 != record['proposal_agreement_sha256']):
        raise ValueError('Order seed changes native formation identity or original accepted agreement')
    expected_native = {'schema_version': 'supplier-native-order-formation-observation.v1', 'run_id': identity.run_id,
        'recorded_at': seed.recorded_at.model_dump(mode='json'), 'producer': seed.producer,
        'core_event_id': formation.core_event_id, 'proposal_ref': formation.proposal_ref.model_dump(mode='json'),
        'agreement_sha256': formation.agreement_sha256, 'order': seed.order.model_dump(mode='json'),
        'lines': [row.model_dump(mode='json') for row in seed.lines],
        'work_authority': seed.work_authority.model_dump(mode='json'),
        'confirmations': [row.model_dump(mode='json') for row in seed.confirmations]}
    if seed.native_record != expected_native or task_digest(expected_native) != formation.native_source_sha256:
        raise ValueError('Order seed changes independent native order/confirmation/work-authority content')
    basis = SupplierOrderHandoffBasisView.model_validate({**seed.relation.model_dump(mode='json'),
        'order_task_sha256': identity.key, 'order_record_sha256': record['record_sha256'],
        'order_input_sha256': identity.input_sha256, 'order_context_sha256': identity.context_sha256,
        'order_result_sha256': record['result_sha256'], 'order_audit_sha256': task_digest(record['audit']),
        'order_source_reading_sha256': record['source_reading_sha256'],
        'proposal_agreement_sha256': record['proposal_agreement_sha256'],
        'formation_record_sha256': task_digest(formation.model_dump(mode='json'))})
    seed_data = seed.model_dump(mode='json')
    registration = DeclaredOrderPlanningRegistration.model_validate({
        'schema_version': 'supplier-order-planning-registration.v1', 'registration_id': seed.registration_id,
        'basis': basis.model_dump(mode='json'), 'current_state': 'recorded',
        **{key: seed_data[key] for key in ('formation_record', 'order', 'lines', 'work_authority',
            'confirmations', 'recorded_at', 'producer', 'native_record')}})
    directory = Path(output_directory).resolve()
    journals = [Path(case[2]['steps'][0]['configuration']['settings']['source_settings']['journal_path']).resolve()
        for case in (order_file, planning_file)]
    if any(directory == journal.parent or directory in journal.parent.parents or journal.parent in directory.parents
            for journal in journals):
        raise ValueError('Order binding output must be separate from action journals')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed',
        'inputs': [{'path': str(path), 'sha256': digest} for path, digest, _ in inputs]}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Order binding original inputs changed before assembly')
        registration_path = directory / 'registration.json'
        atomic_json(registration_path, registration.model_dump(mode='json'))
        assembly = assemble_v4_order_connection(order_result_path=result_file[0], order_input_path=order_file[0],
            planning_input_path=planning_file[0], registration_path=registration_path, output_directory=directory / 'assembly')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Order binding original inputs changed during assembly')
        result = {**assembly, 'schema_version': 'lifecycle-v4-order-registration-binding.v1',
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
    parser.add_argument('--order-result', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    bind_v4_order_registration(seed_path=args.seed, order_result_path=args.order_result, output_directory=args.output)


if __name__ == '__main__':
    main()
