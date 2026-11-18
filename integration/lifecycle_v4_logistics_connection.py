"""Assemble saved A08 and independent shipment declarations into an A09 input."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_logistics_fixture_sources import SupplierLogisticsFixtureSettings
from integration.supplier_logistics_handoff import supplier_logistics_handoff_schemas
from integration.supplier_logistics_receiving_fixture_sources import (
    DeclaredLogisticsReceivingRegistration, SupplierLogisticsReceivingFixtureSettings,
)
from integration.supplier_role_contract_host import SupplierRoleContractSettings
from integration.supplier_quality_logistics_fixture_sources import SupplierQualityLogisticsFixtureSettings
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskIdentity, task_digest


_SOURCES = 'integration.supplier_logistics_receiving_fixture_sources:build_sources'
_VERSION = 'configured-supplier-logistics-receiving-fixture-sources.v1'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def assemble_v4_logistics_connection(*, logistics_result_path, logistics_input_path,
        receiving_input_path, registration_path, output_directory):
    """Read existing evidence and write configuration; never execute an action."""
    files = [_read(path) for path in (logistics_result_path, logistics_input_path,
        receiving_input_path, registration_path)]
    output, logistics_case, receiving_case, declaration = [item[2] for item in files]
    for case in (logistics_case, receiving_case):
        if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
                or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
            raise ValueError('Logistics connection requires original explicit synthetic V4 inputs')
    logistics_step, step = logistics_case['steps'][0], receiving_case['steps'][0]
    old_request = RoleContractInvocation.model_validate(logistics_step['request'])
    old_configuration = RoleContractHostConfiguration.model_validate(logistics_step['configuration'])
    old_settings = SupplierRoleContractSettings.model_validate(old_configuration.settings)
    linked_quality = old_settings.source_factory == 'integration.supplier_quality_logistics_fixture_sources:build_sources'
    old_source = (SupplierQualityLogisticsFixtureSettings if linked_quality else SupplierLogisticsFixtureSettings).model_validate(old_settings.source_settings)
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    registration = DeclaredLogisticsReceivingRegistration.model_validate(declaration)
    evidence = output['execution_evidence']
    identity = TaskIdentity(**evidence['identity'])
    context = request.context
    if (logistics_step['action_id'] != 'SUPPLIER-A08' or step['action_id'] != 'SUPPLIER-A09'
            or old_request.context.contract_ref.id != 'SUPPLIER-A08' or context.contract_ref.id != 'SUPPLIER-A09'
            or old_settings.action_id != 'SUPPLIER-A08' or settings.action_id != 'SUPPLIER-A09'
            or (old_settings.source_factory, old_settings.source_version) not in {
                ('integration.supplier_logistics_fixture_sources:build_sources', 'configured-supplier-logistics-fixture-sources.v1'),
                ('integration.supplier_quality_logistics_fixture_sources:build_sources', 'configured-supplier-quality-logistics-fixture-sources.v1')}
            or settings.source_factory != 'integration.supplier_receiving_fixture_sources:build_sources'
            or settings.source_version != 'configured-supplier-receiving-fixture-sources.v1'
            or settings.logistics_inputs is not None
            or any(getattr(settings, name) is not None for name in ('feedback_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs'))
            or identity.action_id != 'SUPPLIER-A08' or identity.role != 'Supplier'
            or identity.run_id != context.run_id or old_request.context.run_id != context.run_id
            or logistics_case['run_id'] != context.run_id or receiving_case['run_id'] != context.run_id
            or identity.request_id != old_request.context.operation_id
            or identity.context_sha256 != task_digest(old_request.context.model_dump(mode='json'))
            or identity.input_sha256 != task_digest(old_request.action_input)
            or identity.organization_id != old_source.source_projection['organization_id']
            or identity.organization_id != settings.source_settings['source_projection']['organization_id']
            or old_request.context.scope != context.scope
            or old_request.context.business_time.clock_ref != context.business_time.clock_ref
            or old_request.context.business_time.offset > context.business_time.offset
            or old_request.context.operation_id == context.operation_id
            or old_request.context.execution_mode != 'offline_fixture' or context.execution_mode != 'offline_fixture'
            or old_request.execution_path != 'deterministic' or request.execution_path != 'deterministic'
            or output.get('request_sha256') != task_digest(old_request.model_dump(mode='json'))
            or output.get('configuration', {}).get('sha256') != task_digest(old_configuration.model_dump(mode='json'))
            or output.get('source_mode') != 'fixture' or output.get('macro_execution') != 'not_performed'
            or evidence.get('result_table') != 'supplier_logistics_results' or evidence.get('model_host') is not None):
        raise ValueError('Logistics connection changes original A08/A09 identity, configuration, authority or chronology')
    journal = Path(old_source.journal_path).resolve()
    if not journal.is_file() or journal == Path(settings.source_settings['journal_path']).resolve():
        raise ValueError('Logistics connection requires the existing separate original A08 journal')
    record = read_original_supplier_result(journal_path=journal, output=output, identity=identity)
    basis = registration.basis
    expected = {'run_id': context.run_id, 'organization_id': identity.organization_id, 'scope': context.scope,
        'logistics_task_sha256': identity.key, 'logistics_record_sha256': record['record_sha256'],
        'logistics_result_sha256': record['result_sha256'], 'logistics_audit_sha256': task_digest(record['audit']),
        'logistics_source_reading_sha256': record['source_reading_sha256']}
    if registration.current_state != 'observed' or any(getattr(basis, key) != value for key, value in expected.items()):
        raise ValueError('Independent logistics relation changes original saved evidence')
    current = deepcopy(settings.source_settings)
    rows = current['source_projection']['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows):
        raise ValueError('Receiving connection repeats original source references')
    if basis.ref.key() in originals:
        if originals[basis.ref.key()] != basis.model_dump(mode='json'):
            raise ValueError('Receiving connection replaces a different source relation')
    else:
        if basis.ref.key() not in {ref.key() for ref in context.visible_refs}:
            raise ValueError('Receiving input must explicitly authorize its pending source relation')
        rows.append({'ref': basis.ref.model_dump(mode='json'), 'value': basis.model_dump(mode='json')})
    # Keep original declared ordering, including an explicitly reserved relation ref.
    current_rows = {Reference.model_validate(row['ref']).key(): row for row in rows}
    if set(current_rows) != {ref.key() for ref in context.visible_refs}:
        raise ValueError('Receiving connection changes the explicitly declared complete source set')
    current['source_projection']['objects'] = [current_rows[ref.key()] for ref in context.visible_refs]
    source = SupplierLogisticsReceivingFixtureSettings.model_validate({**current,
        'logistics_history': {'request': old_request.model_dump(mode='json'), 'source_settings': old_source.model_dump(mode='json'),
            'identity': identity.as_dict(), **{key: getattr(old_settings, key) for key in ('macro_version', 'client_version', 'policy_version', 'model_version')}},
        'registration': registration.model_dump(mode='json')})
    schemas = supplier_logistics_handoff_schemas()
    for item in source.source_projection['objects']:
        schemas.validate_projection(Reference.model_validate(item['ref']), item['value'])
    connected = deepcopy(receiving_case)
    connected['status'] = 'input_prepared_execution_pending'
    linked_settings = connected['steps'][0]['configuration']['settings']
    linked_settings.update(source_factory=_SOURCES, source_version=_VERSION, source_settings=source.model_dump(mode='json'),
        logistics_inputs={'version': 'v4-logistics-receiving-selection.v1', 'selections': {context.operation_id:
            {'logistics_identity': identity.as_dict(), 'basis_ref': basis.ref.model_dump(mode='json')}}})
    SupplierRoleContractSettings.model_validate(linked_settings)
    connected['source_declaration']['logistics_connection_inputs'] = [{'path': str(path), 'sha256': digest} for path, digest, _ in files]
    directory = Path(output_directory).resolve()
    journal_roots = (journal.parent, Path(current['journal_path']).resolve().parent)
    if any(directory == root or directory in root.parents or root in directory.parents for root in journal_roots):
        raise ValueError('Configuration output must be separate from both action journals')
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
        raise ValueError('Original logistics connection inputs changed during assembly')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed'}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        atomic_json(directory / 'receiving-input.json', connected)
        result = {'schema_version': 'lifecycle-v4-logistics-connection-assembly.v1', 'status': 'assembled_unverified',
            'logistics_identity': identity.as_dict(), 'registration_sha256': task_digest(registration.model_dump(mode='json')),
            'receiving_input_path': str(directory / 'receiving-input.json'), 'action_execution': 'not_performed',
            'inputs': connected['source_declaration']['logistics_connection_inputs']}
        atomic_json(directory / 'assembly.json', result)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
            raise ValueError('Original logistics connection inputs changed while saving configuration')
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return result
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logistics-result', required=True, type=Path)
    parser.add_argument('--logistics-input', required=True, type=Path)
    parser.add_argument('--receiving-input', required=True, type=Path)
    parser.add_argument('--registration', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    assemble_v4_logistics_connection(logistics_result_path=args.logistics_result,
        logistics_input_path=args.logistics_input, receiving_input_path=args.receiving_input,
        registration_path=args.registration, output_directory=args.output)


if __name__ == '__main__':
    main()
