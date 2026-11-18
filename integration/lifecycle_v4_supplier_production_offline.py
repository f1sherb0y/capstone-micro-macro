"""Plan or explicitly evaluate one synthetic V4 Supplier production input request."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_production_fixture_sources import SupplierProductionFixtureSettings
from integration.supplier_planning_production_fixture_sources import (
    SupplierPlanningProductionFixtureSettings, check_planning_connection_selection,
    check_planning_connection_provenance,
)
from integration.supplier_planning_handoff import supplier_planning_handoff_schemas
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_execution_objects import (
    SupplierExecutionTaskView, SupplierExecutionProfileView,
    SupplierProductionReleaseView, SupplierProductionGateView,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_production_fixture_sources:build_sources'
_LINKED_SOURCES = 'integration.supplier_planning_production_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V4 production request requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    linked = settings.source_factory == _LINKED_SOURCES
    source = (SupplierPlanningProductionFixtureSettings if linked else SupplierProductionFixtureSettings).model_validate(settings.source_settings)
    if linked:
        check_planning_connection_selection(request=request, settings=settings, source=source)
    elif settings.planning_inputs is not None:
        raise ValueError('Standalone production cannot silently declare a planning connection')
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A06' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'execute'
            or context.contract_ref.id != 'SUPPLIER-A06' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A06'
            or not linked and (settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-production-fixture-sources.v1')
            or source.action_id != 'SUPPLIER-A06' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V4 production request alters original offline action, source factory, run or snapshot')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V4 production request aliases independent organization source identities')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V4 production request alters complete original visible projection identities')
    schemas = supplier_planning_handoff_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V4 offline production evidence must declare its synthetic origin')
    inputs = request.action_input
    task = SupplierExecutionTaskView.model_validate(originals[Reference.model_validate(inputs['task_ref']).key()])
    profile = SupplierExecutionProfileView.model_validate(originals[task.profile_ref.key()])
    setup = inputs['execution_setup']
    if (task.ref.model_dump(mode='json') != step['expected_task_ref'] or task.mode != 'manufacture'
            or task.organization_id != projection['organization_id'] or task.scope != context.scope
            or task.state != 'released' or task.history_coverage != 'complete' or task.as_of != context.business_time
            or setup.get('kind') != 'production' or task.production_method_ref is None
            or task.production_method_ref.model_dump(mode='json') != setup['method_ref']
            or profile.task_ref != task.ref or profile.organization_id != task.organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or profile.choice != 'execute' or not profile.inputs or not profile.resources
            or [value.model_dump(mode='json') for value in profile.inputs] != step['expected_inputs']
            or [value.model_dump(mode='json') for value in profile.resources] != step['expected_resources']):
        raise ValueError('V4 production request requires its original released task and exact authorized inputs/resources')
    for name in ('prior_execution_refs', 'upstream_delivery_refs'):
        values = [Reference.model_validate(value) for value in inputs[name]]
        if len({ref.key() for ref in values}) != len(values) or [ref.key() for ref in values] != [ref.key() for ref in getattr(task, name)]:
            raise ValueError('V4 production request changes its complete original execution or delivery history')
    release = SupplierProductionReleaseView.model_validate(originals[Reference.model_validate(setup['release_ref']).key()])
    gate = SupplierProductionGateView.model_validate(originals[release.gate_ref.key()])
    if (release.organization_id != task.organization_id or release.task_ref != task.ref
            or release.method_ref != task.production_method_ref or release.status != 'released'
            or gate.task_ref != task.ref or gate.release_ref != release.ref or gate.producer != 'core'
            or gate.coverage != 'complete' or gate.as_of != context.business_time):
        raise ValueError('V4 production request substitutes its supplied original release/gate sources')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v4_supplier_production_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 production request execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V4 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-supplier-production-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A06', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_task_ref': deepcopy(step['expected_task_ref']),
        'expected_inputs': deepcopy(step['expected_inputs']),
        'expected_resources': deepcopy(step['expected_resources']),
        'source_planning_selection': deepcopy(configuration['settings'].get('planning_inputs')),
        'limitations': ['Isolated synthetic input request; release, gates, actual stock and reservations are supplied assumptions.',
            'No production quantity, loss, quality, lineage, cost, stock movement or connected V4 delivery chain proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-supplier-production-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V4 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'supplier', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Supplier', 'action_id': 'SUPPLIER-A06', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A06'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_execution_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'execute'
                or result['payload']['task_ref'] != step['expected_task_ref']
                or result['payload']['inputs'] != step['expected_inputs']
                or result['payload']['resources'] != step['expected_resources']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V4 production request did not preserve its exact task input request and original result without transport')
        if configuration['settings'].get('planning_inputs') is not None:
            source = SupplierPlanningProductionFixtureSettings.model_validate(configuration['settings']['source_settings'])
            check_planning_connection_provenance(request=RoleContractInvocation.model_validate(request),
                source=source, evidence=evidence)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V4 original Supplier production input changed during evaluation')
        summary = {**plan, 'mode': 'executed_offline', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result': deepcopy(result), 'real_model_calls': 0}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v4_supplier_production_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
