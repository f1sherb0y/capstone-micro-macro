"""Assemble original A07 evidence and independent release declarations into A08."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.lifecycle_v4_logistics_connection import _read
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.sessions import atomic_json
from integration.supplier_quality_fixture_sources import SupplierQualityFixtureSettings
from integration.supplier_production_quality_fixture_sources import SupplierProductionQualityFixtureSettings
from integration.supplier_quality_handoff import supplier_quality_handoff_schemas
from integration.supplier_quality_logistics_fixture_sources import (
    DeclaredQualityDispatchRegistration, SupplierQualityLogisticsFixtureSettings,
)
from integration.supplier_role_contract_host import SupplierRoleContractSettings
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskIdentity, task_digest


def assemble_v4_quality_connection(*, quality_result_path, quality_input_path,
        logistics_input_path, registration_path, output_directory):
    files = [_read(path) for path in (quality_result_path, quality_input_path, logistics_input_path, registration_path)]
    output, quality_case, logistics_case, declaration = [item[2] for item in files]
    for case in (quality_case, logistics_case):
        if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
                or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
            raise ValueError('Quality connection requires original explicit synthetic V4 inputs')
    quality_step, step = quality_case['steps'][0], logistics_case['steps'][0]
    original_request = RoleContractInvocation.model_validate(quality_step['request'])
    original_configuration = RoleContractHostConfiguration.model_validate(quality_step['configuration'])
    original_settings = SupplierRoleContractSettings.model_validate(original_configuration.settings)
    linked_production = original_settings.source_factory == 'integration.supplier_production_quality_fixture_sources:build_sources'
    original_source = (SupplierProductionQualityFixtureSettings if linked_production else SupplierQualityFixtureSettings).model_validate(original_settings.source_settings)
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    registration = DeclaredQualityDispatchRegistration.model_validate(declaration)
    identity = TaskIdentity(**output['execution_evidence']['identity'])
    context = request.context
    if (quality_step['action_id'] != 'SUPPLIER-A07' or step['action_id'] != 'SUPPLIER-A08'
            or original_request.context.contract_ref.id != 'SUPPLIER-A07' or context.contract_ref.id != 'SUPPLIER-A08'
            or original_settings.action_id != 'SUPPLIER-A07' or settings.action_id != 'SUPPLIER-A08'
            or (original_settings.source_factory, original_settings.source_version) not in {
                ('integration.supplier_quality_fixture_sources:build_sources', 'configured-supplier-quality-fixture-sources.v1'),
                ('integration.supplier_production_quality_fixture_sources:build_sources', 'configured-supplier-production-quality-fixture-sources.v1')}
            or settings.source_factory != 'integration.supplier_logistics_fixture_sources:build_sources'
            or settings.source_version != 'configured-supplier-logistics-fixture-sources.v1'
            or any(getattr(settings, name) is not None for name in ('feedback_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or identity.action_id != 'SUPPLIER-A07' or identity.role != 'Supplier' or identity.run_id != context.run_id
            or original_request.context.run_id != context.run_id or quality_case['run_id'] != context.run_id
            or logistics_case['run_id'] != context.run_id or identity.request_id != original_request.context.operation_id
            or identity.context_sha256 != task_digest(original_request.context.model_dump(mode='json'))
            or identity.input_sha256 != task_digest(original_request.action_input)
            or identity.organization_id != original_source.source_projection['organization_id']
            or identity.organization_id != settings.source_settings['source_projection']['organization_id']
            or original_request.context.scope != context.scope
            or original_request.context.business_time.clock_ref != context.business_time.clock_ref
            or original_request.context.business_time.offset > context.business_time.offset
            or original_request.context.operation_id == context.operation_id
            or original_request.context.execution_mode != 'offline_fixture' or context.execution_mode != 'offline_fixture'
            or original_request.execution_path != 'deterministic' or request.execution_path != 'deterministic'
            or output.get('request_sha256') != task_digest(original_request.model_dump(mode='json'))
            or output.get('configuration', {}).get('sha256') != task_digest(original_configuration.model_dump(mode='json'))):
        raise ValueError('Quality connection changes original identity, input, configuration, scope or chronology')
    source_journal = Path(original_source.journal_path).resolve()
    recipient_journal = Path(settings.source_settings['journal_path']).resolve()
    if source_journal == recipient_journal:
        raise ValueError('Quality connection requires separate original and recipient journals')
    record = read_original_supplier_result(journal_path=source_journal, output=output, identity=identity)
    basis = registration.basis
    expected = {'run_id': context.run_id, 'organization_id': identity.organization_id, 'scope': context.scope,
        'quality_task_sha256': identity.key, 'quality_record_sha256': record['record_sha256'],
        'quality_result_sha256': record['result_sha256'], 'quality_audit_sha256': task_digest(record['audit']),
        'quality_source_reading_sha256': record['source_reading_sha256']}
    if registration.current_state != 'released' or any(getattr(basis, key) != value for key, value in expected.items()):
        raise ValueError('Independent quality relation changes original saved evidence')
    current = deepcopy(settings.source_settings)
    rows = {Reference.model_validate(row['ref']).key(): deepcopy(row) for row in current['source_projection']['objects']}
    if len(rows) != len(current['source_projection']['objects']):
        raise ValueError('Quality connection repeats current source identities')
    for projection in (basis, registration.release_record, registration.batch, registration.release, *registration.dispatchables):
        value = projection.model_dump(mode='json')
        if projection.ref.key() in rows:
            if rows[projection.ref.key()]['value'] != value:
                raise ValueError('Quality connection replaces an independently declared current source')
        elif projection.ref.key() not in {ref.key() for ref in context.visible_refs}:
            raise ValueError('Logistics input must explicitly authorize its pending quality relation sources')
        else:
            rows[projection.ref.key()] = {'ref': projection.ref.model_dump(mode='json'), 'value': value}
    if set(rows) != {ref.key() for ref in context.visible_refs}:
        raise ValueError('Quality connection changes the complete explicitly declared source set')
    current['source_projection']['objects'] = [rows[ref.key()] for ref in context.visible_refs]
    source = SupplierQualityLogisticsFixtureSettings.model_validate({**current,
        'quality_history': {'request': original_request.model_dump(mode='json'),
            'source_settings': original_source.model_dump(mode='json'), 'identity': identity.as_dict(),
            **{key: getattr(original_settings, key) for key in ('macro_version', 'client_version', 'policy_version', 'model_version')}},
        'registration': registration.model_dump(mode='json')})
    schemas = supplier_quality_handoff_schemas()
    for row in source.source_projection['objects']:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
    connected = deepcopy(logistics_case)
    linked = connected['steps'][0]['configuration']['settings']
    linked.update(source_factory='integration.supplier_quality_logistics_fixture_sources:build_sources',
        source_version='configured-supplier-quality-logistics-fixture-sources.v1', source_settings=source.model_dump(mode='json'),
        quality_inputs={'version': 'v4-quality-logistics-selection.v1', 'selections': {context.operation_id:
            {'quality_identity': identity.as_dict(), 'basis_ref': basis.ref.model_dump(mode='json')}}})
    SupplierRoleContractSettings.model_validate(linked)
    connected['status'] = 'input_prepared_execution_pending'
    inputs = [{'path': str(path), 'sha256': digest} for path, digest, _ in files]
    connected['source_declaration']['quality_connection_inputs'] = inputs
    directory = Path(output_directory).resolve()
    if any(directory == root or directory in root.parents or root in directory.parents
            for root in (source_journal.parent, recipient_journal.parent)):
        raise ValueError('Quality configuration output must be separate from action journals')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed', 'inputs': inputs}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
            raise ValueError('Quality connection original inputs changed during assembly')
        atomic_json(directory / 'logistics-input.json', connected)
        result = {'schema_version': 'lifecycle-v4-quality-connection-assembly.v1', 'status': 'assembled_unverified',
            'quality_identity': identity.as_dict(), 'registration_sha256': task_digest(registration.model_dump(mode='json')),
            'logistics_input_path': str(directory / 'logistics-input.json'), 'action_execution': 'not_performed', 'inputs': inputs}
        atomic_json(directory / 'assembly.json', result)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
            raise ValueError('Quality connection original inputs changed while saving configuration')
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return result
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('quality-result', 'quality-input', 'logistics-input', 'registration', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    assemble_v4_quality_connection(quality_result_path=args.quality_result, quality_input_path=args.quality_input,
        logistics_input_path=args.logistics_input, registration_path=args.registration, output_directory=args.output)


if __name__ == '__main__':
    main()
