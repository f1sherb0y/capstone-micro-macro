"""Plan or explicitly evaluate one synthetic V6 Supplier change proposal."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_remedy_fixture_sources import SupplierRemedyFixtureSettings
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_remedy_objects import (
    SupplierRemedyOrderView, SupplierRemedyProfileView, SupplierSupplyChangeProposalView,
    supplier_remedy_schemas,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_remedy_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V6'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V6 supply change requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    source = SupplierRemedyFixtureSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A11' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'propose_change'
            or context.contract_ref.id != 'SUPPLIER-A11' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A11'
            or settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-remedy-fixture-sources.v1'
            or source.action_id != 'SUPPLIER-A11' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V6 supply change alters original offline action, source factory, run or snapshot')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V6 supply change aliases independent organization source identities')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V6 supply change alters complete original visible projection identities')
    schemas = supplier_remedy_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V6 offline supply change evidence must declare its synthetic origin')
    inputs = request.action_input
    order = SupplierRemedyOrderView.model_validate(originals[Reference.model_validate(inputs['order_ref']).key()])
    profile = SupplierRemedyProfileView.model_validate(originals[Reference.model_validate(inputs['remedy_profile_ref']).key()])
    if (profile.choice != 'propose_change' or profile.order_ref != order.ref or profile.change_proposal_ref is None
            or order.supplier_id != projection['organization_id'] or profile.organization_id != order.supplier_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or order.coverage != 'complete' or order.as_of != context.business_time
            or inputs['authority_refs'] != [value.model_dump(mode='json') for value in context.authorization_refs]):
        raise ValueError('V6 supply change requires its original current order and explicitly selected proposal')
    for supplied, field in (('batch_refs', 'batch_refs'), ('installed_use_refs', 'material_use_refs'),
            ('change_refs', 'change_refs'), ('defect_refs', 'defect_refs')):
        values = [Reference.model_validate(value) for value in inputs[supplied]]
        if len(set(values)) != len(values) or set(values) != set(getattr(order, field)):
            raise ValueError('V6 supply change omits original order history: ' + field)
    proposal = SupplierSupplyChangeProposalView.model_validate(originals[profile.change_proposal_ref.key()])
    affected, unaffected = set(profile.affected_line_refs), set(profile.unaffected_line_refs)
    if (not affected or not unaffected or affected & unaffected or affected | unaffected != set(order.line_refs)
            or len(affected) != len(profile.affected_line_refs) or len(unaffected) != len(profile.unaffected_line_refs)
            or proposal.order_ref != order.ref or proposal.author_organization_id != order.supplier_id
            or proposal.author_action_id != 'SUPPLIER-A11' or proposal.status not in {'proposal', 'pending'}
            or not proposal.lines or len(proposal.lines) != len(proposal.line_order_refs)
            or len(set(proposal.line_order_refs)) != len(proposal.line_order_refs) or set(proposal.line_order_refs) != affected
            or [value.model_dump(mode='json') for value in proposal.lines] != step['expected_lines']
            or [value.model_dump(mode='json') for value in profile.affected_line_refs] != step['expected_affected_line_refs']
            or [value.model_dump(mode='json') for value in profile.unaffected_line_refs] != step['expected_unaffected_line_refs']
            or not order.material_use_refs
            or inputs['installed_use_refs'] != step['expected_installed_use_refs']):
        raise ValueError('V6 supply change alters its specific proposal, unaffected lines or retained installed use')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v6_supplier_change_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 supply change execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V6 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-supplier-change-plan.v1', 'scenario_id': 'V6', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A11', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_lines': deepcopy(step['expected_lines']), 'expected_affected_line_refs': deepcopy(step['expected_affected_line_refs']),
        'source_unaffected_line_refs': deepcopy(step['expected_unaffected_line_refs']),
        'source_installed_use_refs': deepcopy(step['expected_installed_use_refs']),
        'limitations': ['Isolated synthetic proposal; unaffected lines and installed use are retained input sources.',
            'No formal order amendment, approved equivalence, native removal/replacement, refund or connected V6 behavior proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-supplier-change-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V6 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'supplier', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Supplier', 'action_id': 'SUPPLIER-A11', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A11'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_remedy_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'propose_change'
                or result['payload']['lines'] != step['expected_lines']
                or result['payload']['affected_line_refs'] != step['expected_affected_line_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V6 supply change did not preserve its exact proposal and original result without transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V6 original Supplier change input changed during evaluation')
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
    print(run_v6_supplier_change_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
