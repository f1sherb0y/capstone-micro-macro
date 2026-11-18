"""Assemble V4 material connections from saved A09 and independently supplied stock."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.contractor_role_contract_host import ContractorRoleContractSettings
from integration.lifecycle_v4_contractor_material import _prepare_data
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_receiving_contractor_fixture_sources import (
    ContractorSupplierReceivingFixtureSettings, DeclaredReceivedMaterialRegistration,
)
from integration.supplier_role_contract_host import SupplierRoleContractSettings
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_execution_objects import contractor_execution_schemas
from src.coordination.tasks import TaskIdentity, task_digest


_SOURCES = 'integration.supplier_receiving_contractor_fixture_sources:build_sources'
_VERSION = 'configured-contractor-supplier-receiving-fixture-sources.v1'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def assemble_v4_material_connection(*, supplier_result_path, supplier_input_path,
        contractor_input_path, registrations_path, output_directory):
    """Produce configuration only; do not run factories, query journals or create stock."""
    files = [_read(path) for path in (supplier_result_path, supplier_input_path,
        contractor_input_path, registrations_path)]
    original, supplier_case, contractor, supplied_registrations = [item[2] for item in files]
    if (supplier_case.get('schema_version') != 'lifecycle-input-case.v1'
            or supplier_case.get('scenario_id') != 'V4' or supplier_case.get('origin') != 'synthetic'
            or not isinstance(supplier_case.get('steps'), list) or len(supplier_case['steps']) != 1
            or not isinstance(contractor, dict) or set(contractor) != {
                'run_id', 'contractor_organization_id', 'request', 'configuration'}
            or not isinstance(supplied_registrations, list) or not supplied_registrations):
        raise ValueError('Connection assembly requires original synthetic A09 input, Contractor input and independent registrations')
    step = supplier_case['steps'][0]
    supplier_request = RoleContractInvocation.model_validate(step['request'])
    supplier_configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    supplier_settings = SupplierRoleContractSettings.model_validate(supplier_configuration.settings)
    request = RoleContractInvocation.model_validate(contractor['request'])
    configuration = RoleContractHostConfiguration.model_validate(contractor['configuration'])
    settings = ContractorRoleContractSettings.model_validate(configuration.settings)
    identity = TaskIdentity(**original['execution_evidence']['identity'])
    context = request.context
    if (step.get('action_id') != 'SUPPLIER-A09'
            or step.get('host') != 'integration.supplier_role_contract_host:build_role_host'
            or supplier_case['run_id'] != context.run_id or contractor['run_id'] != context.run_id
            or supplier_request.context.run_id != context.run_id
            or identity.run_id != context.run_id or identity.role != 'Supplier' or identity.action_id != 'SUPPLIER-A09'
            or supplier_settings.action_id != 'SUPPLIER-A09'
            or (supplier_settings.source_factory, supplier_settings.source_version) not in {
                ('integration.supplier_receiving_fixture_sources:build_sources', 'configured-supplier-receiving-fixture-sources.v1'),
                ('integration.supplier_logistics_receiving_fixture_sources:build_sources', 'configured-supplier-logistics-receiving-fixture-sources.v1')}
            or supplier_request.execution_path != 'deterministic' or request.execution_path != 'deterministic'
            or supplier_request.context.execution_mode != 'offline_fixture' or context.execution_mode != 'offline_fixture'
            or context.contract_ref.id != 'CONTRACTOR-A07' or settings.action_id != 'CONTRACTOR-A07'
            or settings.source_factory != 'integration.contractor_execution_fixture_sources:build_sources'
            or settings.source_version != 'configured-contractor-execution-fixture-sources.v1'
            or identity.organization_id == contractor['contractor_organization_id']
            or identity.input_sha256 != task_digest(supplier_request.action_input)
            or identity.context_sha256 != task_digest(supplier_request.context.model_dump(mode='json'))
            or identity.request_id != supplier_request.context.operation_id
            or original.get('request_sha256') != task_digest(supplier_request.model_dump(mode='json'))
            or original.get('configuration', {}).get('sha256') != task_digest(supplier_configuration.model_dump(mode='json'))
            or supplier_request.context.scope != context.scope
            or supplier_request.context.business_time.clock_ref != context.business_time.clock_ref
            or supplier_request.context.business_time.offset > context.business_time.offset):
        raise ValueError('Connection assembly changes original same-run inputs, versions, source factories or chronology')
    registrations = [DeclaredReceivedMaterialRegistration.model_validate(row) for row in supplied_registrations]
    if (len({row.registration_id for row in registrations}) != len(registrations)
            or len({row.basis.ref.key() for row in registrations}) != len(registrations)):
        raise ValueError('Connection assembly repeats independent registration identities')
    projection = settings.source_settings['source_projection']
    rows = projection['objects']
    sources = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(sources) != len(rows) or projection['organization_id'] != contractor['contractor_organization_id']:
        raise ValueError('Connection assembly changes original Contractor source identities or organization')
    schemas = contractor_execution_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
    for registration in registrations:
        basis = registration.basis
        if (registration.current_state != 'received' or registration.sharing_authorized is not True
                or basis.run_id != context.run_id or basis.organization_id != contractor['contractor_organization_id']
                or basis.supplier_organization_id != identity.organization_id
                or basis.receiving_task_sha256 != identity.key
                or basis.receiving_record_sha256 != original['execution_evidence']['record_sha256']
                or basis.receiving_result_sha256 != task_digest(original['result'])
                or basis.receiving_source_reading_sha256 != original['execution_evidence']['source_reading_sha256']
                or registration.recipient_actor_id != context.actor_id
                or registration.recipient_function_ref != context.function_ref
                or registration.recipient_authorization_refs != context.authorization_refs):
            raise ValueError('Connection declaration changes independent receiver or original Supplier provenance')
        for value in (basis, registration.inventory, registration.batch):
            supplied = sources.get(value.ref.key())
            if supplied is None or schemas.validate_projection(value.ref, supplied) != value:
                raise ValueError('Connection declaration differs from original authorized Contractor basis or stock')
        if (basis.inventory_ref != registration.inventory.ref or basis.batch_ref != registration.batch.ref
                or basis.inventory_sha256 != task_digest(registration.inventory.model_dump(mode='json'))
                or basis.batch_sha256 != task_digest(registration.batch.model_dump(mode='json'))
                or basis.native_record_sha256 != task_digest(registration.native_record)):
            raise ValueError('Connection declaration changes original stock or native mapping hashes')
    supplier_journal = Path(supplier_settings.source_settings['journal_path']).resolve()
    contractor_journal = Path(settings.source_settings['journal_path']).resolve()
    if not supplier_journal.is_file() or supplier_journal == contractor_journal or contractor_journal.exists():
        raise ValueError('Connection requires existing separate Supplier journal and a new Contractor journal')
    connected_source = {**deepcopy(settings.source_settings),
        'supplier_history': {'request': supplier_request.model_dump(mode='json'),
            'source_settings': deepcopy(supplier_settings.source_settings), 'identity': identity.as_dict(),
            **{name: getattr(supplier_settings, name) for name in (
                'macro_version', 'client_version', 'policy_version', 'model_version')}},
        'registrations': [row.model_dump(mode='json') for row in registrations]}
    connected_source = ContractorSupplierReceivingFixtureSettings.model_validate(connected_source).model_dump(mode='json')
    if any(getattr(settings, name) is not None for name in (
            'feedback_inputs', 'received_material_inputs', 'received_payment_inputs',
            'received_award_inputs', 'received_tender_inputs', 'received_permit_inputs')):
        raise ValueError('Connection assembly requires explicit isolated Contractor material configuration')
    configuration_data = configuration.model_dump(mode='json')
    configuration_data['settings'].update(source_factory=_SOURCES, source_version=_VERSION,
        source_settings=connected_source, received_material_inputs={
            'version': 'configured-received-material-selection.v1',
            'selections': {context.operation_id: {'source_task_sha256': identity.key,
                'material_basis_refs': [row.basis.ref.model_dump(mode='json') for row in registrations]}}})
    ContractorRoleContractSettings.model_validate(configuration_data['settings'])
    connected = {**deepcopy(contractor), 'request': request.model_dump(mode='json'), 'configuration': configuration_data}
    bases = [row.basis.model_dump(mode='json') for row in registrations]
    directory = Path(output_directory).resolve()
    if directory.exists():
        raise FileExistsError('Connection assembly requires a new output directory')
    contractor_file, basis_file = directory / 'contractor-input.json', directory / 'material-basis.json'
    data = {'schema_version': 'lifecycle-v4-contractor-material-input.v1', 'scenario_id': 'V4',
        **{key: connected[key] for key in ('run_id', 'contractor_organization_id', 'request', 'configuration')},
        'source_mode': 'fixture', 'supplier_receiving': {'result_path': str(files[0][0]),
            'result_file_sha256': files[0][1], 'identity': identity.as_dict(),
            'record_sha256': original['execution_evidence']['record_sha256'], 'result_sha256': task_digest(original['result']),
            'reading_sha256': original['execution_evidence']['source_reading_sha256'],
            'material_basis_refs': [row.basis.ref.model_dump(mode='json') for row in registrations]},
        'assembly_sources': {}}
    def encoded(value):
        return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    generated = [(contractor_file, hashlib.sha256(encoded(connected)).hexdigest(), connected),
        (basis_file, hashlib.sha256(encoded(bases)).hexdigest(), bases)]
    for label, item in zip(('contractor_input', 'material_basis'), generated):
        data['assembly_sources'][label] = {'path': str(item[0]), 'file_sha256': item[1]}
    destination = directory / 'material-input.json'
    _prepare_data((destination, task_digest(data), data),
        captured_sources={item[0]: item for item in [files[0], *generated]})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
        raise ValueError('Original connection input changed before assembly')
    directory.mkdir(parents=True, exist_ok=False)
    for path, _, value in generated:
        path.write_bytes(encoded(value))
    destination.write_bytes(encoded(data))
    manifest = {'schema_version': 'lifecycle-v4-material-connection-assembly.v1', 'status': 'assembled_unverified',
        'origin': 'synthetic', 'run_id': context.run_id, 'mode': 'configuration_only',
        'original_files': [{'path': str(path), 'sha256': digest} for path, digest, _ in files],
        'generated_files': [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (contractor_file, basis_file, destination)],
        'supplier_task_sha256': identity.key, 'source_factory': _SOURCES, 'real_model_calls': 0,
        'limitations': ['Configuration assembled from supplied originals; original journals and independent source relations are checked by the host at explicit execution.',
            'No receipt, inspection, release, stock, consumption or work outcome is generated.']}
    atomic_json(directory / 'assembly.json', manifest)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
        atomic_json(directory / 'assembly.json', {**manifest, 'status': 'failed',
            'reason': 'original_input_changed_during_assembly', 'automatic_retry': False})
        raise ValueError('Original connection input changed during assembly; review saved artifacts before retrying')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('supplier-result', 'supplier-input', 'contractor-input', 'registrations', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    print(assemble_v4_material_connection(supplier_result_path=args.supplier_result,
        supplier_input_path=args.supplier_input, contractor_input_path=args.contractor_input,
        registrations_path=args.registrations, output_directory=args.output)['status'])


if __name__ == '__main__':
    main()
