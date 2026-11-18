"""Plan or explicitly execute independently supplied V1 offline action inputs."""
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
_SCHEMAS = {
    'OWN-A02': 'src.actions.contracts.owner_study_objects:owner_study_schemas',
    'OWN-A03': 'src.actions.contracts.owner_investment_objects:owner_investment_schemas',
}
_CASES = {
    'v1-stop-then-reject': [('OWN-A02', 'completed', 'stop'), ('OWN-A03', 'completed', 'reject')],
    'v1-investment-revision': [('OWN-A03', 'completed', 'revise')],
    'v1-investment-missing-policy': [('OWN-A03', 'needs_information', None)],
}
_MISSING_FIELDS = {'v1-investment-missing-policy': ['declared_investment_policy']}


def _prepare(path):
    """Copy explicitly authored inputs only; construct no host or permissions."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    case = json.loads(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V1'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('run_id'), str)
            or not case['run_id'].strip()
            or case.get('case_id') not in _CASES
            or [(step.get('action_id'), step.get('expected_kind'), step.get('expected_choice'))
                for step in case.get('steps', [])] != _CASES[case['case_id']]):
        raise ValueError('V1 offline entry requires an explicitly registered synthetic case and its original outcome expectation')
    prepared = []
    for index, step in enumerate(case['steps']):
        fixture, binding = step['input_fixture'], step['offline_binding']
        expected_missing = _MISSING_FIELDS.get(case['case_id'], [])
        if step.get('expected_missing_fields', []) != expected_missing:
            raise ValueError('V1 input changes the registered missing-information expectation')
        request = deepcopy(binding['invocation'])
        request['action_input'] = deepcopy(fixture['input'])
        context = request['context']
        if (fixture['origin'] != 'synthetic' or context['run_id'] != case['run_id']
                or context['execution_mode'] != 'offline_fixture' or request['execution_path'] != 'deterministic'
                or context['contract_ref']['id'] != step['action_id']
                or context['operation_id'] != step['operation_id']
                or context['business_time'] != fixture['business_time']
                or context['actor_id'] != fixture['actor_id']
                or context['scope']['kind'] != 'assessment_case'
                or context['scope']['ref'] != fixture['input']['case_ref']
                or binding['schema_factory'] != _SCHEMAS[step['action_id']]):
            raise ValueError('V1 offline binding changes its authored run, mode, action or original input identity')
        projection = deepcopy(binding['source_projection_envelope'])
        projection['objects'] = deepcopy(fixture['objects'] + binding['supplemental_objects'])
        configuration = {'schema_version': 'role-contract-host-config.v1',
            'host_id': ('v1-refusal-' if case['case_id'] == 'v1-stop-then-reject'
                else 'v1-revision-' if case['case_id'] == 'v1-investment-revision'
                else 'v1-information-') + str(index + 1), 'version': '1',
            'settings': {'action_id': step['action_id'], 'schema_factory': binding['schema_factory'],
                'source_note': binding['source_note'], 'organization_snapshot': deepcopy(binding['organization_snapshot']),
                'source_projection': projection}}
        prepared.append({'request': request, 'configuration': configuration,
            'expected_kind': step['expected_kind'], 'expected_choice': step['expected_choice'],
            'expected_missing_fields': deepcopy(expected_missing)})
    if len(prepared) == 2:
        first, second = [step['request']['context'] for step in prepared]
        if (first['business_time']['clock_ref'] != second['business_time']['clock_ref']
                or first['business_time']['offset'] >= second['business_time']['offset']
                or first['operation_id'] == second['operation_id'] or first['task_ref'] == second['task_ref']
                or first['read_token'] == second['read_token'] or first['actor_id'] != second['actor_id']
                or first['scope']['ref']['id'] != second['scope']['ref']['id']
                or case['steps'][0]['input_fixture']['organization_id'] != case['steps'][1]['input_fixture']['organization_id']
                or case['transition']['from_case_ref'] != first['scope']['ref']
                or case['transition']['to_case_ref'] != second['scope']['ref']):
            raise ValueError('V1 steps require the same case/actor/clock and distinct ordered invocation identities')
    return path, hashlib.sha256(raw).hexdigest(), case, prepared


def run_v1_offline(*, case_path, output_directory, execute=False):
    """Default to a plan; execution is deterministic, ordered and never replayed."""
    if type(execute) is not bool:
        raise ValueError('V1 execution requires an explicit boolean execute selection')
    path, source_sha, case, steps = _prepare(case_path)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v1-offline-plan.v1', 'origin': 'synthetic',
        'run_id': case['run_id'], 'case_path': str(path), 'case_sha256': source_sha,
        'factory': _FACTORY, 'mode': 'execute_offline' if execute else 'plan_only',
        'steps': [{'action_id': step['request']['context']['contract_ref']['id'],
            'operation_id': step['request']['context']['operation_id'],
            'request_sha256': task_digest(step['request']), 'configuration_sha256': task_digest(step['configuration']),
            'expected_kind': step['expected_kind'], 'expected_choice': step['expected_choice'],
            'expected_missing_fields': deepcopy(step['expected_missing_fields'])}
            for step in steps],
        'limitations': 'Explicit local synthetic decisions only. No native case publication, completed research, formal effect, receipt or full V1 acceptance.'}
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v1-offline-attempt.v1',
        'case_sha256': source_sha, 'status': 'started', 'completed_steps': []}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        results = []
        for index, step in enumerate(steps):
            if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha:
                raise ValueError('V1 input case changed during execution')
            result = run_role_contract(request=step['request'], configuration=step['configuration'],
                factory=build_role_host, specification=_FACTORY,
                output_directory=directory / ('step-' + str(index + 1)), offline=True)
            observed = result['result']
            if (observed['kind'] != step['expected_kind']
                    or observed.get('payload', {}).get('choice') != step['expected_choice']
                    or observed.get('missing_fields', []) != step['expected_missing_fields']):
                raise ValueError('V1 original action did not produce the registered outcome or missing-information request')
            results.append({'action_id': plan['steps'][index]['action_id'],
                'result_path': 'step-' + str(index + 1) + '/result.json',
                'result_sha256': task_digest(result), 'kind': observed['kind'],
                'choice': observed.get('payload', {}).get('choice'),
                'missing_fields': deepcopy(observed.get('missing_fields', []))})
            attempt['completed_steps'] = deepcopy(results)
            atomic_json(directory / 'attempt.json', attempt)
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha:
            raise ValueError('V1 input case changed during execution')
        summary = {**plan, 'status': ('local_refusal_decisions_completed' if case['case_id'] == 'v1-stop-then-reject'
            else 'local_information_request_formed' if case['case_id'] in _MISSING_FIELDS
            else 'local_revision_decision_completed'), 'results': results,
            'transition': deepcopy(case['transition']), 'remaining_requirements': deepcopy(case['remaining_requirements'])}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path,
        default=Path('tests/fixtures/roles/lifecycle_v1_stop_reject.v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v1_offline(case_path=args.case, output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
