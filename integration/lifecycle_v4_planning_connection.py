"""Assemble original saved A05 and independent task formation into A06 sources."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.lifecycle_v4_logistics_connection import _read
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.sessions import atomic_json
from integration.supplier_planning_fixture_sources import SupplierPlanningFixtureSettings
from integration.supplier_order_planning_fixture_sources import (
    SupplierOrderPlanningFixtureSettings, check_order_connection_selection, check_order_connection_provenance,
)
from integration.supplier_planning_handoff import supplier_planning_handoff_schemas
from integration.supplier_planning_production_fixture_sources import (
    DeclaredFormedPurchaseTask, DeclaredPlanningProductionRegistration, SupplierPlanningProductionFixtureSettings,
)
from integration.supplier_role_contract_host import SupplierRoleContractSettings
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_planning_objects import SupplierPlannedTask
from src.coordination.tasks import TaskIdentity, task_digest


def assemble_v4_planning_connection(*, planning_result_path, planning_input_path,
        production_input_path, registration_path, output_directory):
    """Read actual saved provenance and write configuration without native effects."""
    files = [_read(path) for path in (planning_result_path, planning_input_path, production_input_path, registration_path)]
    output, planning_case, production_case, declaration = [item[2] for item in files]
    for case in (planning_case, production_case):
        if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
                or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
            raise ValueError('Planning connection requires original explicit synthetic V4 inputs')
    original_step, step = planning_case['steps'][0], production_case['steps'][0]
    original_request = RoleContractInvocation.model_validate(original_step['request'])
    original_configuration = RoleContractHostConfiguration.model_validate(original_step['configuration'])
    original_settings = SupplierRoleContractSettings.model_validate(original_configuration.settings)
    linked_order = original_settings.source_factory == 'integration.supplier_order_planning_fixture_sources:build_sources'
    original_source = (SupplierOrderPlanningFixtureSettings if linked_order else SupplierPlanningFixtureSettings).model_validate(original_settings.source_settings)
    if linked_order:
        check_order_connection_selection(request=original_request, settings=original_settings, source=original_source)
        check_order_connection_provenance(request=original_request, source=original_source, evidence=output['execution_evidence'])
    elif original_settings.order_inputs is not None:
        raise ValueError('Standalone planning history cannot declare an order connection')
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    registration = DeclaredPlanningProductionRegistration.model_validate(declaration)
    identity = TaskIdentity(**output['execution_evidence']['identity'])
    context = request.context
    if (original_step['action_id'] != 'SUPPLIER-A05' or step['action_id'] != 'SUPPLIER-A06'
            or original_step['host'] != 'integration.supplier_role_contract_host:build_role_host'
            or step['host'] != original_step['host']
            or original_request.context.contract_ref.id != 'SUPPLIER-A05' or context.contract_ref.id != 'SUPPLIER-A06'
            or original_settings.action_id != 'SUPPLIER-A05' or settings.action_id != 'SUPPLIER-A06'
            or (original_settings.source_factory, original_settings.source_version) not in {
                ('integration.supplier_planning_fixture_sources:build_sources', 'configured-supplier-planning-fixture-sources.v1'),
                ('integration.supplier_order_planning_fixture_sources:build_sources', 'configured-supplier-order-planning-fixture-sources.v1')}
            or settings.order_inputs is not None
            or settings.source_factory != 'integration.supplier_production_fixture_sources:build_sources'
            or settings.source_version != 'configured-supplier-production-fixture-sources.v1'
            or any(getattr(value, name) is not None for value in (original_settings, settings)
                for name in ('feedback_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or identity.action_id != 'SUPPLIER-A05' or identity.role != 'Supplier' or identity.purpose != 'action'
            or identity.run_id != context.run_id or original_request.context.run_id != context.run_id
            or planning_case['run_id'] != context.run_id or production_case['run_id'] != context.run_id
            or identity.request_id != original_request.context.operation_id
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
        raise ValueError('Planning connection changes original action, identity, configuration, scope or chronology')
    original_journal = Path(original_source.journal_path).resolve()
    recipient_journal = Path(settings.source_settings['journal_path']).resolve()
    if original_journal == recipient_journal:
        raise ValueError('Planning connection requires separate original and recipient journals')
    record = read_original_supplier_result(journal_path=original_journal, output=output, identity=identity)
    basis, formation = registration.basis, registration.formation_record
    expected = {'run_id': context.run_id, 'organization_id': identity.organization_id, 'scope': context.scope,
        'planning_task_sha256': identity.key, 'planning_record_sha256': record['record_sha256'],
        'planning_result_sha256': record['result_sha256'], 'planning_audit_sha256': task_digest(record['audit']),
        'planning_source_reading_sha256': record['source_reading_sha256']}
    if (registration.current_state != 'recorded' or any(getattr(basis, key) != value for key, value in expected.items())
            or basis.formation_record_ref != formation.ref
            or basis.formation_record_sha256 != task_digest(formation.model_dump(mode='json'))
            or formation.run_id != context.run_id or formation.organization_id != identity.organization_id
            or formation.scope != original_request.context.scope
            or formation.work_authority_ref.key() != Reference.model_validate(original_request.action_input['work_authority_ref']).key()
            or record['result']['payload']['choice'] not in {'plan_manufacture', 'plan_purchase', 'split_plan', 'revise_plan'}):
        raise ValueError('Planning relation changes original saved plan or independent task formation')
    planned = [SupplierPlannedTask.model_validate(row) for row in record['result']['payload']['tasks']]
    plans = {row.local_key: row for row in planned}
    lines = {row.planned_task.local_key: row for row in formation.lines}
    formed = {row.task.ref.key(): row for row in registration.tasks}
    selected = Reference.model_validate(request.action_input['task_ref'])
    if (len(plans) != len(planned) or len(lines) != len(formation.lines) or set(plans) != set(lines)
            or any(row.planned_task != plans[key] for key, row in lines.items())
            or len(formed) != len(registration.tasks) or set(formed) != {row.task_ref.key() for row in formation.lines}
            or selected.key() not in formed
            or any((row.mode == 'purchase') != isinstance(formed[lines[row.local_key].task_ref.key()], DeclaredFormedPurchaseTask)
                for row in planned)
            or any(row.task_sha256 != task_digest(formed[row.task_ref.key()].task.model_dump(mode='json')) for row in formation.lines)):
        raise ValueError('Native formation drops or changes original full plan or selected execution task')
    expected_native = {'schema_version': 'supplier-native-task-formation-observation.v1', 'run_id': context.run_id,
        'work_authority_ref': formation.work_authority_ref.model_dump(mode='json'),
        'recorded_at': registration.recorded_at.model_dump(mode='json'), 'producer': registration.producer,
        'formation_lines': [row.model_dump(mode='json') for row in formation.lines],
        'tasks': [row.model_dump(mode='json') for row in registration.tasks]}
    if registration.native_record != expected_native or task_digest(expected_native) != formation.native_source_sha256:
        raise ValueError('Planning connection changes independently declared native formation content')
    current = deepcopy(settings.source_settings)
    rows = {Reference.model_validate(row['ref']).key(): deepcopy(row) for row in current['source_projection']['objects']}
    if len(rows) != len(current['source_projection']['objects']):
        raise ValueError('Planning connection repeats current source identities')
    projections = [basis, formation]
    for row in registration.tasks:
        if isinstance(row, DeclaredFormedPurchaseTask):
            projections.extend([row.task, row.upstream_order, row.receipt_rule])
        else:
            projections.extend([row.task, row.method, row.release])
            for mapping in row.material_lineage:
                projections.extend([mapping.material, mapping.allocation])
    for projection in projections:
        value = projection.model_dump(mode='json')
        if projection.ref.key() in rows:
            if rows[projection.ref.key()]['value'] != value:
                raise ValueError('Planning connection replaces an independently declared current source')
        elif projection.ref.key() not in {ref.key() for ref in context.visible_refs}:
            raise ValueError('Production input must explicitly authorize its pending planning sources')
        else:
            rows[projection.ref.key()] = {'ref': projection.ref.model_dump(mode='json'), 'value': value}
    if len({ref.key() for ref in context.visible_refs}) != len(context.visible_refs) or set(rows) != {ref.key() for ref in context.visible_refs}:
        raise ValueError('Planning connection changes complete explicitly declared source identities')
    current['source_projection']['objects'] = [rows[ref.key()] for ref in context.visible_refs]
    source = SupplierPlanningProductionFixtureSettings.model_validate({**current,
        'planning_history': {'request': original_request.model_dump(mode='json'),
            'source_settings': original_source.model_dump(mode='json'), 'identity': identity.as_dict(),
            **{key: getattr(original_settings, key) for key in ('macro_version', 'client_version', 'policy_version', 'model_version')}},
        'registration': registration.model_dump(mode='json')})
    schemas = supplier_planning_handoff_schemas()
    for row in source.source_projection['objects']:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
    connected = deepcopy(production_case)
    linked = connected['steps'][0]['configuration']['settings']
    linked.update(source_factory='integration.supplier_planning_production_fixture_sources:build_sources',
        source_version='configured-supplier-planning-production-fixture-sources.v1', source_settings=source.model_dump(mode='json'),
        planning_inputs={'version': 'v4-planning-production-selection.v1', 'selections': {context.operation_id:
            {'planning_identity': identity.as_dict(), 'basis_ref': basis.ref.model_dump(mode='json')}}})
    SupplierRoleContractSettings.model_validate(linked)
    connected['status'] = 'input_prepared_execution_pending'
    inputs = [{'path': str(path), 'sha256': digest} for path, digest, _ in files]
    connected['source_declaration']['planning_connection_inputs'] = inputs
    directory = Path(output_directory).resolve()
    if any(directory == root or directory in root.parents or root in directory.parents
            for root in (original_journal.parent, recipient_journal.parent)):
        raise ValueError('Planning configuration output must be separate from action journals')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed', 'inputs': inputs}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
            raise ValueError('Planning connection original inputs changed during assembly')
        atomic_json(directory / 'production-input.json', connected)
        result = {'schema_version': 'lifecycle-v4-planning-connection-assembly.v1', 'status': 'assembled_unverified',
            'planning_identity': identity.as_dict(), 'registration_sha256': task_digest(registration.model_dump(mode='json')),
            'production_input_path': str(directory / 'production-input.json'), 'action_execution': 'not_performed', 'inputs': inputs}
        atomic_json(directory / 'assembly.json', result)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
            raise ValueError('Planning connection inputs changed while saving configuration')
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return result
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('planning-result', 'planning-input', 'production-input', 'registration', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    assemble_v4_planning_connection(planning_result_path=args.planning_result, planning_input_path=args.planning_input,
        production_input_path=args.production_input, registration_path=args.registration, output_directory=args.output)


if __name__ == '__main__':
    main()
