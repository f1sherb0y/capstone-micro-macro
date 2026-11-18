"""Plan or explicitly persist QS certification using independent original power."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.lifecycle_v5_qs_payment_calculation_offline import _read
from integration.qs_role_contract_host import build_role_host
from integration.role_contract_host import run_role_contract
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest

_FACTORY = 'integration.qs_role_contract_host:build_role_host'


def _prepare(case_path, reception_path):
    """Inspect supplied JSON only; the source factory validates actual durable reception."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != 'lifecycle-v5-qs-certification-input-case.v1'
            or case.get('scenario_id') != 'V5' or case.get('origin') != 'synthetic' or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'verify_output_directory', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-qs-certification-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('QS certification requires explicit current input and independently received basis/power')
    step = case['steps'][0]
    fixture, binding = step['input_fixture'], step['offline_binding']
    declaration, original = case['source_declaration'], binding['invocation']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    context = request['context']
    rows = {task_digest(row['ref']): row['value'] for row in sources['source_projection']['objects']}
    if (step['action_id'] != 'QS-A08' or step['allowed_choices'] != ['verify', 'request_evidence', 'certify', 'correct_certificate']
            or set(request) != set(original) or set(context) != set(original['context'])
            or any(request[k] != v for k, v in original.items() if k != 'context')
            or any(context[k] != v for k, v in original['context'].items() if k not in {'visible_refs', 'authorization_refs'})
            or not all(ref in context['authorization_refs'] for ref in original['context']['authorization_refs'])
            or sources['action_id'] != 'QS-A08' or sources['allow_saved_recovery'] is not False
            or sources['current_policy_version'] != declaration['policy_version']
            or len(rows) != len(sources['source_projection']['objects'])
            or any(rows.get(task_digest(row['ref'])) != row['value'] for row in fixture['objects'])
            or context['visible_refs'] != [row['ref'] for row in sources['source_projection']['objects']]
            or any(sources['source_projection'][key] != context[key] for key in ('run_id', 'business_time', 'read_token'))
            or sources['source_projection']['organization_id'] != fixture['organization_id']):
        raise ValueError('QS certification changes original current instruction, source facts or explicit authority')
    grants = {task_digest(row['ref']): row for row in sources['organization_snapshot']['authorizations']}
    baseline = binding['organization_snapshot']
    if (len(grants) != len(sources['organization_snapshot']['authorizations'])
            or sources['organization_snapshot']['run_id'] != case['run_id']
            or any(grants.get(task_digest(row['ref'])) != row for row in baseline['authorizations'])
            or any(row not in sources['organization_snapshot']['organizations'] for row in baseline['organizations'])
            or any(ref in sources['organization_snapshot']['inactive_authorization_refs'] for ref in context['authorization_refs'])):
        raise ValueError('QS certification replaces original actor/function/current grants')
    directory = Path(reception['verify_output_directory']).resolve()
    upstream = tuple(_read(directory / name) for name in ('configuration.json', 'qs/result.json', 'summary.json'))
    previous_config, verified, summary = (file[2] for file in upstream)
    previous = previous_config['settings']['source_settings']
    evidence, observed = verified['execution_evidence'], verified['result']
    declared = sources['certification_reception']
    identity = evidence['identity']
    if (verified['run_id'] != case['run_id'] or verified['action_id'] != 'QS-A08' or verified['source_mode'] != 'fixture'
            or observed['kind'] != 'completed' or observed['payload']['choice'] != 'verify'
            or summary['status'] != 'original_qs_payment_verified' or summary['result_sha256'] != task_digest(verified)
            or summary['inputs'][0]['sha256'] != declaration['verify_case_sha256']
            or evidence['result_table'] != 'qs_payment_results' or evidence['task']['identity'] != identity
            or evidence['task']['output'] != observed or evidence['task']['output_sha256'] != task_digest(observed)
            or verified['audit'] != [evidence['saved_audit']] or evidence['saved_audit']['result_sha256'] != task_digest(observed)
            or declared['verify_identity'] != identity or declared['verify_record_sha256'] != evidence['record_sha256']
            or declared['verify_result_sha256'] != task_digest(observed)
            or declared['verify_reading_sha256'] != evidence['source_reading_sha256']
            or any(sources[key] != previous[key] for key in ('calculation_request', 'calculation_settings',
                'calculation_record_sha256', 'calculation_publication_sha256'))
            or Path(sources['journal_path']).resolve() != Path(evidence['sources']['journal_path']).resolve()
            or any(rows.get(task_digest(row['ref'])) != row['value'] for row in previous['source_projection']['objects'])):
        raise ValueError('QS certification replaces original verified statement, journal or immutable valuation history')
    basis, power = declared['basis'], declared['authority']
    expected = declaration['future_signing_refs']
    if (basis['ref'] != expected['certification_basis_ref'] or power['ref'] != expected['certification_authority_ref']
            or basis['authority_ref'] != power['ref'] or request['action_input']['certification_authority_ref'] != power['ref']
            or basis['statement_sha256'] != task_digest(observed['payload']['statement'])
            or rows.get(task_digest(basis['ref'])) != basis or rows.get(task_digest(power['ref'])) != power
            or declared['native_evidence_ref'] != declaration['native_evidence_ref']):
        raise ValueError('Independent QS basis substitutes the predeclared original reference, verified statement or power')
    native = {'schema_version': 'qs-independent-certification-native.v1', 'verify_identity': identity,
        'verify_record_sha256': evidence['record_sha256'], 'verify_result_sha256': task_digest(observed),
        'verify_reading_sha256': evidence['source_reading_sha256'], 'statement': observed['payload']['statement'],
        'basis': basis, 'authority': power, 'received_at': declared['received_at'],
        'current_context': context, 'current_input': request['action_input']}
    evidence_row = rows.get(task_digest(declared['native_evidence_ref']))
    if (declared['native_payload'] != native or not isinstance(evidence_row, dict)
            or evidence_row['source_kind'] != 'synthetic' or evidence_row['basis_kind'] != 'observed'
            or evidence_row['content_hash'] != task_digest(native)):
        raise ValueError('Independent QS basis lacks complete observed native reception evidence')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'QS-A08', 'source_factory': 'integration.qs_payment_certification_fixture_sources:build_sources',
            'source_version': 'configured-qs-payment-certification-fixture-sources.v1', 'source_settings': sources,
            'macro_version': sources['source_projection']['macro_version'], 'client_version': 'role-contract-qs-fixture.v1',
            'policy_version': sources['current_policy_version'], 'model_version': 'offline-fixture-no-model.v1'}}
    return (case_file, reception_file, *upstream), case, request, config


def run_v5_qs_certification_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('QS certification requires explicit boolean offline execution')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-qs-certification-offline-plan.v1', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'QS-A08', 'mode': 'execute_offline' if execute else 'plan_only',
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'limitations': case['limitations'], 'remaining_requirements': case['remaining_requirements']}
    for name, value in [('request', request), ('configuration', config), ('reception-input', files[1][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    for index, file in enumerate(files[2:]):
        atomic_json(directory / f'verification-input-{index}.json', file[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-qs-certification-attempt.v1', 'status': 'started'}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('Independent QS certification reception changed before evaluation')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'qs', offline=True)
        observed, evidence = result['result'], result['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        registration = config['settings']['source_settings']['certification_reception']
        provenance = evidence['sources']['independent_certification_input']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'QS', 'action_id': 'QS-A08', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (observed['kind'] != 'completed' or observed['payload']['choice'] != 'certify'
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or evidence['result_table'] != 'qs_payment_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed or task['output_sha256'] != task_digest(observed)
                or result['audit'] != [audit] or audit['input_sha256'] != identity['input_sha256']
                or audit['result_sha256'] != task_digest(observed) or audit['operation_id'] != identity['request_id']
                or audit['run_id'] != case['run_id'] or audit['action_id'] != 'QS-A08'
                or observed['payload']['statement'] != files[3][2]['result']['payload']['statement']
                or observed['payload']['certification_basis_ref'] != registration['basis']['ref']
                or any(provenance[key] != registration[key] for key in
                    ('verify_identity', 'verify_record_sha256', 'verify_result_sha256', 'verify_reading_sha256'))
                or provenance['basis_ref'] != registration['basis']['ref'] or provenance['authority_ref'] != registration['authority']['ref']
                or provenance['native_payload_sha256'] != task_digest(registration['native_payload'])):
            raise ValueError('Original QS certification decision or durable independent authority reception differs from supplied lineage')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('Independent QS certification reception changed during evaluation')
        atomic_json(directory / 'persistent-evidence.json', evidence)
        summary = {**plan, 'status': 'local_qs_certification_decision_completed', 'result_path': 'qs/result.json',
            'result_sha256': task_digest(result), 'record_sha256': evidence['record_sha256'],
            'independent_certification_input': deepcopy(provenance)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_qs_certification_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_qs_certification_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'status': report.get('status', 'planned_not_executed'),
        'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
