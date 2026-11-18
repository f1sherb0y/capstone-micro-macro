"""Plan or explicitly run the independent synthetic V3 procedural intake."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.role_contract_fixture_host import build_role_host
from integration.role_contract_host import run_role_contract
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest


_FACTORY = 'integration.role_contract_fixture_host:build_role_host'
_SCHEMA = 'src.actions.contracts.government_objects:government_intake_schemas'


def _prepare(path):
    """Preserve supplied inputs and grants; construct no application components."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    case = json.loads(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V3'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('run_id'), str)
            or not case['run_id'].strip()
            or [(s.get('action_id'), s.get('expected_kind'), s.get('expected_choice'))
                for s in case.get('steps', [])] != [('GOV-A02', 'completed', 'accept_for_processing')]):
        raise ValueError('V3 intake entry requires one explicitly supplied synthetic completeness input')
    step = case['steps'][0]
    fixture, binding = step['input_fixture'], step['offline_binding']
    request = deepcopy(binding['invocation'])
    request['action_input'] = deepcopy(fixture['input'])
    context = request['context']
    source = deepcopy(binding['source_projection_envelope'])
    source['objects'] = deepcopy(fixture['objects'] + binding['supplemental_objects'])
    if (fixture['source_kind'] != 'synthetic' or context['execution_mode'] != 'offline_fixture'
            or request['execution_path'] != 'deterministic' or context['run_id'] != case['run_id']
            or context['contract_ref']['id'] != 'GOV-A02' or context['operation_id'] != step['operation_id']
            or context['actor_id'] != fixture['actor_id'] or context['business_time'] != fixture['business_time']
            or context['scope'] != fixture['input']['scope'] or binding['schema_factory'] != _SCHEMA
            or binding['organization_snapshot']['run_id'] != case['run_id']
            or source['organization_id'] != fixture['organization_id']
            or any(source[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
            or context['visible_refs'] != [o['ref'] for o in source['objects']]):
        raise ValueError('V3 binding changes its original action, scope, identity or source declaration')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'GOV-A02', 'schema_factory': _SCHEMA, 'source_note': binding['source_note'],
            'organization_snapshot': deepcopy(binding['organization_snapshot']), 'source_projection': source}}
    return path, hashlib.sha256(raw).hexdigest(), case, request, config


def run_v3_offline(*, case_path, output_directory, execute=False):
    """Execute only local completeness; retain pending publication and review links."""
    if type(execute) is not bool:
        raise ValueError('V3 execution requires an explicit boolean selection')
    path, source_sha, case, request, config = _prepare(case_path)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v3-offline-plan.v1', 'origin': 'synthetic',
        'run_id': case['run_id'], 'case_path': str(path), 'case_sha256': source_sha,
        'factory': _FACTORY, 'mode': 'execute_offline' if execute else 'plan_only',
        'action_id': 'GOV-A02', 'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'expected_kind': 'completed', 'expected_choice': 'accept_for_processing',
        'predecessor_requirements': deepcopy(case['predecessor_requirements']),
        'dependent_steps': deepcopy(case['dependent_steps']),
        'remaining_requirements': deepcopy(case['remaining_requirements']),
        'limitations': 'Independent synthetic procedural intake only; no original A07 publication, native reception, registered case, technical approval or use permit.'}
    atomic_json(directory / 'request.json', request)
    atomic_json(directory / 'configuration.json', config)
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v3-offline-attempt.v1', 'case_sha256': source_sha, 'status': 'started'}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha:
            raise ValueError('V3 input changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'step-1', offline=True)
        observed = result['result']
        if (observed['kind'] != 'completed' or observed.get('payload', {}).get('choice') != 'accept_for_processing'
                or observed['payload'].get('scope') != request['context']['scope']):
            raise ValueError('Original GOV-A02 did not produce the declared same-scope procedural acceptance')
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha:
            raise ValueError('V3 input changed during execution')
        summary = {**plan, 'status': 'local_procedural_intake_completed',
            'result_path': 'step-1/result.json', 'result_sha256': task_digest(result)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v3_intake_inputs.v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v3_offline(case_path=args.case, output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
