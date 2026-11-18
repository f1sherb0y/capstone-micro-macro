"""Plan or explicitly evaluate one synthetic V4 Supplier external batch-check request."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_quality_fixture_sources import SupplierQualityFixtureSettings
from integration.supplier_production_quality_fixture_sources import SupplierProductionQualityFixtureSettings
from integration.supplier_execution_handoff import supplier_execution_handoff_schemas
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_quality_objects import (
    SupplierQualityBatchView, SupplierQualityProfileView, SupplierQualityMethodView,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_quality_fixture_sources:build_sources'
_LINKED_SOURCES = 'integration.supplier_production_quality_fixture_sources:build_sources'
_LINKED_VERSION = 'configured-supplier-production-quality-fixture-sources.v1'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V4 quality request requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    linked = settings.source_factory == _LINKED_SOURCES
    source = (SupplierProductionQualityFixtureSettings if linked else SupplierQualityFixtureSettings).model_validate(settings.source_settings)
    if linked:
        selection = settings.execution_inputs
        if (settings.source_version != _LINKED_VERSION or selection is None
                or set(selection.selections) != {request.context.operation_id}
                or selection.selections[request.context.operation_id].execution_identity.as_dict() != source.production_history.identity.as_dict()
                or selection.selections[request.context.operation_id].basis_ref != source.registration.basis.ref):
            raise ValueError('V4 connected quality requires selected original A06 and independent production relation')
    elif settings.execution_inputs is not None:
        raise ValueError('V4 standalone quality cannot silently declare a production connection')
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A07' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'request_external_check'
            or context.contract_ref.id != 'SUPPLIER-A07' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A07'
            or not linked and (settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-quality-fixture-sources.v1')
            or source.action_id != 'SUPPLIER-A07' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'planning_inputs', 'quality_inputs', 'logistics_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V4 quality request alters original offline action, source factory, run or snapshot')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V4 quality request aliases independent organization source identities')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V4 quality request alters complete original visible projection identities')
    schemas = supplier_execution_handoff_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V4 offline quality evidence must declare its synthetic origin')
    inputs = request.action_input
    batch = SupplierQualityBatchView.model_validate(originals[Reference.model_validate(inputs['batch_ref']).key()])
    profile = SupplierQualityProfileView.model_validate(originals[Reference.model_validate(inputs['inspection_profile_ref']).key()])
    if (inputs['scope_ref'] != context.scope.model_dump(mode='json')
            or batch.ref.model_dump(mode='json') != step['expected_batch_ref']
            or batch.organization_id != projection['organization_id'] or batch.scope != context.scope
            or batch.state != 'pending_inspection' or batch.as_of != context.business_time
            or profile.batch_ref != batch.ref or profile.organization_id != batch.organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or profile.choice != 'request_external_check' or profile.method_ref is None
            or profile.disposition_right_ref is not None or profile.quantity is not None
            or profile.remedy_plan_ref is not None or profile.deviation_refs
            or not inputs['requirement_refs'] or not inputs['known_defect_refs']
            or inputs['known_defect_refs'] != step['expected_known_defect_refs']
            or inputs['evidence_refs'] != step['expected_evidence_refs']):
        raise ValueError('V4 quality request requires its original pending batch, visible defects and external-check selection')
    for supplied, field in (('requirement_refs', 'requirement_refs'), ('evidence_refs', 'evidence_refs_received'),
            ('known_defect_refs', 'known_defect_refs')):
        values = [Reference.model_validate(value).key() for value in inputs[supplied]]
        if len(set(values)) != len(values) or values != [ref.key() for ref in getattr(profile, field)]:
            raise ValueError('V4 quality request changes original received requirements, observations or defects')
        if supplied != 'evidence_refs' and values != [ref.key() for ref in getattr(batch, field)]:
            raise ValueError('V4 quality request omits original batch requirements or visible defects')
    method = SupplierQualityMethodView.model_validate(originals[profile.method_ref.key()])
    if (method.ref.model_dump(mode='json') != step['expected_method_ref']
            or method.executor_organization_id != step['expected_executor_organization_id']
            or method.executor_organization_id == batch.organization_id
            or method.requirement_refs != profile.requirement_refs
            or method.executor_authority_ref not in [value.ref for value in source.organization_snapshot.authorizations]):
        raise ValueError('V4 quality request substitutes its selected independent external inspection method or authority')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v4_supplier_quality_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 quality request execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V4 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-supplier-quality-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A07', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_method_ref': deepcopy(step['expected_method_ref']),
        'expected_evidence_refs': deepcopy(step['expected_evidence_refs']),
        'source_batch_ref': deepcopy(step['expected_batch_ref']),
        'source_known_defect_refs': deepcopy(step['expected_known_defect_refs']),
        'source_executor_organization_id': step['expected_executor_organization_id'],
        'source_execution_selection': deepcopy(configuration['settings'].get('execution_inputs')),
        'limitations': ['Isolated synthetic external-check request; pending batch and visible defect are retained source assumptions.',
            'No actual independent inspection, passed result, customer acceptance, stock/disposition effect or connected V4 quality chain proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-supplier-quality-attempt.v1', 'status': 'started',
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
            'role': 'Supplier', 'action_id': 'SUPPLIER-A07', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A07'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_quality_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'request_external_check'
                or result['payload']['method_ref'] != step['expected_method_ref']
                or result['payload']['evidence_refs'] != step['expected_evidence_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V4 quality request did not preserve its exact independent inspection request and original result without transport')
        production = configuration['settings'].get('execution_inputs')
        if production is not None:
            selected = production['selections'][request['context']['operation_id']]
            basis = configuration['settings']['source_settings']['registration']['basis']
            provenance = evidence.get('execution_input')
            if (not isinstance(provenance, dict) or provenance.get('kind') != 'prepared'
                    or provenance.get('execution_identity') != selected['execution_identity']
                    or provenance.get('batch_ref') != request['action_input']['batch_ref']
                    or provenance.get('basis_sha256') != task_digest(basis)
                    or provenance.get('execution_record_sha256') != basis['execution_record_sha256']
                    or provenance.get('execution_result_sha256') != basis['execution_result_sha256']):
                raise ValueError('V4 connected quality lost selected original production provenance')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V4 original Supplier quality input changed during evaluation')
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
    print(run_v4_supplier_quality_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
