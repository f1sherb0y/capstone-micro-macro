"""Bind an independent synthetic stock declaration to an existing A09 journal result."""
import argparse
from contextlib import closing
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3

from pydantic import Field
from typing import Annotated, Literal

from integration.lifecycle_v4_material_connection import _read, assemble_v4_material_connection
from integration.role_contract_host import RoleContractInvocation
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_receiving_contractor_fixture_sources import DeclaredReceivedMaterialRegistration
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.contractor_execution_objects import ContractorReceivedMaterialView, contractor_execution_schemas
from src.coordination.tasks import TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredMaterialMappingSeed(StrictRecord):
    ref: ref_type('ReceivedMaterialBasis')
    registration_id: TextId
    receipt_ref: ref_type('GoodsReceipt')
    component_ref: ref_type('ReceiptComponent')
    physical_slice_key: TextId
    use_release_refs: Annotated[list[ref_type('GoodsUseRelease')], Field(min_length=1)]
    use_code: TextId
    inventory_ref: ref_type('InventoryPosition')
    batch_ref: ref_type('MaterialBatch')
    native_evidence_ref: ref_type('Evidence')
    received_at: TimePoint
    scope: ScopeRef
    sharing_authorized: bool
    native_record: dict


class MaterialConnectionSeed(StrictRecord):
    schema_version: Literal['lifecycle-v4-material-connection-seed.v1']
    scenario_id: Literal['V4']
    origin: Literal['synthetic']
    status: Literal['awaiting_original_supplier_result']
    supplier_input_path: TextId
    supplier_input_sha256: Digest
    contractor: dict
    mapping: DeclaredMaterialMappingSeed
    assumptions: Annotated[list[TextId], Field(min_length=1)]


def bind_v4_material_registration(*, seed_path, supplier_result_path, output_directory):
    """Read the existing journal, then assemble declarations/configuration; no action execution."""
    seed_file, result_file = _read(seed_path), _read(supplier_result_path)
    seed = MaterialConnectionSeed.model_validate(seed_file[2])
    supplier_file = _read(seed.supplier_input_path)
    if supplier_file[1] != seed.supplier_input_sha256:
        raise ValueError('Material seed changes its original Supplier input')
    supplier_step = supplier_file[2]['steps'][0]
    supplier_source = supplier_step['configuration']['settings']['source_settings']
    journal = Path(supplier_source['journal_path']).resolve()
    if not journal.is_file():
        raise ValueError('Material registration requires an existing original Supplier journal')
    output = result_file[2]
    evidence = output['execution_evidence']
    identity = TaskIdentity(**evidence['identity'])
    request = RoleContractInvocation.model_validate(seed.contractor['request'])
    supplier_request = RoleContractInvocation.model_validate(supplier_step['request'])
    if (identity.run_id != request.context.run_id or identity.action_id != 'SUPPLIER-A09'
            or identity.role != 'Supplier' or evidence['result_table'] != 'supplier_receiving_results'
            or output.get('source_mode') != 'fixture' or output['result']['kind'] != 'completed'
            or identity.context_sha256 != task_digest(supplier_request.context.model_dump(mode='json'))
            or identity.input_sha256 != task_digest(supplier_request.action_input)):
        raise ValueError('Material registration requires the original same-run Supplier A09 result')
    # A read-only connection cannot create the missing journal or replay work.
    with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT record FROM supplier_receiving_results WHERE task_key=?', (identity.key,)).fetchone()
    if row is None:
        raise ValueError('Material registration cannot find its original Supplier result record')
    _, record = parse_input_json(row[0].encode('utf-8'))
    if (record['identity'] != identity.as_dict() or record['result'] != output['result']
            or record['record_sha256'] != evidence['record_sha256']
            or record['result_sha256'] != task_digest(record['result'])
            or record['audit'] != evidence['saved_audit']
            or task_digest({key: value for key, value in record.items() if key != 'record_sha256'}) != record['record_sha256']
            or task_digest(record['source_reading']) != record['source_reading_sha256']
            or record['source_reading_sha256'] != evidence['source_reading_sha256']):
        raise ValueError('Material registration replaces the saved Supplier record or source witness')
    mapping = seed.mapping
    original_refs = [value['ref'] for value in record['source_reading']]
    if mapping.sharing_authorized is not True:
        raise ValueError('Material registration requires explicit source sharing authorization')
    configuration = deepcopy(seed.contractor['configuration'])
    source = configuration['settings']['source_settings']
    projections = source['source_projection']['objects']
    schemas = contractor_execution_schemas()
    originals = {}
    for row in projections:
        ref = Reference.model_validate(row['ref'])
        if ref.key() in originals:
            raise ValueError('Material declaration repeats an original source reference')
        originals[ref.key()] = schemas.validate_projection(ref, row['value'])
    inventory, batch = originals[mapping.inventory_ref.key()], originals[mapping.batch_ref.key()]
    native = mapping.native_record
    expected_native = {'schema_version': 'contractor-material-stock-mapping.v1', 'run_id': request.context.run_id,
        'organization_id': seed.contractor['contractor_organization_id'],
        **{field: getattr(mapping, field).model_dump(mode='json') for field in (
            'receipt_ref', 'component_ref', 'inventory_ref', 'batch_ref', 'received_at')},
        'physical_slice_key': mapping.physical_slice_key, 'use_code': mapping.use_code,
        'use_release_refs': [ref.model_dump(mode='json') for ref in mapping.use_release_refs],
        'inventory_sha256': task_digest(inventory.model_dump(mode='json')),
        'batch_sha256': task_digest(batch.model_dump(mode='json'))}
    if native != expected_native:
        raise ValueError('Material registration changes the independently declared stock mapping')
    native_evidence = originals[mapping.native_evidence_ref.key()]
    if (native_evidence.source_kind != 'synthetic' or native_evidence.basis_kind != 'observed'
            or native_evidence.content_hash != task_digest(native)):
        raise ValueError('Material registration lacks its independently supplied simulated native observation')
    basis = ContractorReceivedMaterialView.model_validate({
        'ref': mapping.ref.model_dump(mode='json'), 'scope': mapping.scope.model_dump(mode='json'),
        'available_at': request.context.business_time.model_dump(mode='json'),
        'effective_window': inventory.effective_window.model_dump(mode='json'),
        'evidence_refs': [mapping.native_evidence_ref.model_dump(mode='json')],
        'run_id': identity.run_id, 'organization_id': seed.contractor['contractor_organization_id'],
        'supplier_organization_id': identity.organization_id, 'receiving_task_sha256': identity.key,
        'receiving_record_sha256': record['record_sha256'], 'receiving_result_sha256': record['result_sha256'],
        'receiving_source_reading_sha256': record['source_reading_sha256'],
        **{key: value for key, value in expected_native.items() if key not in {'schema_version', 'run_id', 'organization_id'}},
        'native_evidence_ref': mapping.native_evidence_ref.model_dump(mode='json'),
        'native_record_sha256': task_digest(native)})
    if basis.ref.key() in originals or basis.ref.key() not in {ref.key() for ref in request.context.visible_refs}:
        raise ValueError('Material registration requires a new explicitly authorized pending basis reference')
    projections.append({'ref': basis.ref.model_dump(mode='json'), 'value': basis.model_dump(mode='json')})
    connected_contractor = {**deepcopy(seed.contractor), 'configuration': configuration}
    registration = DeclaredReceivedMaterialRegistration.model_validate({
        'schema_version': 'contractor-received-material-registration.v1', 'registration_id': mapping.registration_id,
        'basis': basis, 'inventory': inventory, 'batch': batch, 'native_record': native,
        'recipient_actor_id': request.context.actor_id, 'recipient_function_ref': request.context.function_ref,
        'recipient_authorization_refs': request.context.authorization_refs,
        'sharing_authorized': mapping.sharing_authorized, 'shared_source_refs': original_refs, 'current_state': 'received'})
    directory = Path(output_directory).resolve()
    if directory.exists():
        raise FileExistsError('Material registration requires a new output directory')
    inputs = [seed_file, result_file, supplier_file]
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
        raise ValueError('Material seed, Supplier input or saved result changed before binding')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False,
        'inputs': [{'path': str(path), 'sha256': digest} for path, digest, _ in inputs]}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        atomic_json(directory / 'contractor-declaration.json', connected_contractor)
        atomic_json(directory / 'registrations.json', [registration.model_dump(mode='json')])
        result = assemble_v4_material_connection(supplier_result_path=result_file[0], supplier_input_path=supplier_file[0],
            contractor_input_path=directory / 'contractor-declaration.json', registrations_path=directory / 'registrations.json',
            output_directory=directory / 'connection')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in inputs):
            raise ValueError('Material binding sources changed during assembly')
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'supplier_task_sha256': identity.key,
            'result': result['status'], 'limitations': ['Original saved-result provenance bound; synthetic receiver stock declaration is not an actual native observation.']})
        return result
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', required=True, type=Path)
    parser.add_argument('--supplier-result', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(bind_v4_material_registration(seed_path=args.seed, supplier_result_path=args.supplier_result,
        output_directory=args.output)['status'])


if __name__ == '__main__':
    main()
