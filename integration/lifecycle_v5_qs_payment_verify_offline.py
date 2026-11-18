"""Plan or explicitly persist V5 QS verification of original published payment results."""
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
_SOURCE_FACTORY = 'integration.qs_payment_published_fixture_sources:build_sources'


def _prepare(case_path, reception_path):
    """Inspect supplied JSON only; persistent publication is rechecked by the actual source factory."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') not in {'lifecycle-v5-qs-payment-verify-input-case.v1',
            'lifecycle-v5-qs-payment-verify-input-case.v2'}
            or case.get('scenario_id') != 'V5' or case.get('origin') != 'synthetic' or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'calculation_output_directory', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-qs-payment-verify-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 QS verification requires original published calculation reception and explicit current input')
    step = case['steps'][0]
    fixture, binding = step['input_fixture'], step['offline_binding']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    context, original = request['context'], binding['invocation']
    if (step['action_id'] != 'QS-A08' or step['allowed_choices'] != ['verify', 'request_evidence', 'certify', 'correct_certificate']
            or set(request) != set(original) or set(context) != set(original['context'])
            or any(request[k] != v for k, v in original.items() if k != 'context')
            or any(context[k] != v for k, v in original['context'].items()
                if k not in {'authorization_refs', 'visible_refs'})
            or not all(ref in context['authorization_refs'] for ref in original['context']['authorization_refs'])
            or sources['action_id'] != 'QS-A08' or sources['allow_saved_recovery'] is not False
            or sources['source_projection']['run_id'] != case['run_id']
            or sources['source_projection']['organization_id'] != fixture['organization_id']
            or request['action_input']['certification_authority_ref'] is not None):
        raise ValueError('V5 QS verification changes the original input, publication boundary or current authority')
    directory = Path(reception['calculation_output_directory']).resolve()
    upstream = tuple(_read(directory / name) for name in ('plan.json', 'request.json', 'configuration.json',
        'calculation-result.json', 'published-source-projection.json', 'summary.json'))
    plan, calculation_request, settings, calculation, projected, summary = (row[2] for row in upstream)
    record, publication = calculation['record'], calculation['publication']
    if (plan['run_id'] != case['run_id'] or plan['action_id'] != 'QS-A08' or plan['mode'] != 'execute_offline'
            or plan['inputs'][0]['sha256'] != case['source_declaration']['calculation_case_sha256']
            or summary['status'] != 'original_qs_calculation_saved_and_published' or calculation['kind'] != 'prepared'
            or plan['request_sha256'] != task_digest(calculation_request) or plan['configuration_sha256'] != task_digest(settings)
            or sources['calculation_request'] != calculation_request or sources['calculation_settings'] != settings
            or settings['publication_request']['context'] != context
            or sources['calculation_record_sha256'] != record['record_sha256']
            or sources['calculation_publication_sha256'] != publication['record_sha256']
            or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
            or publication['record_sha256'] != task_digest({k: v for k, v in publication.items() if k != 'record_sha256'})
            or summary['record_sha256'] != record['record_sha256'] or summary['publication_sha256'] != publication['record_sha256']
            or publication['execution_sha256'] != record['record_sha256']
            or publication['context'] != context or record['context'] != calculation_request['context']
            or record['action_input'] != calculation_request['action_input']
            or sources['source_projection'] != projected or summary['source_projection_sha256'] != task_digest(projected)
            or sources['organization_snapshot'] != settings['publication_sources']['organization_snapshot']
            or Path(sources['journal_path']).resolve() != Path(settings['production_sources']['journal_path']).resolve()
            or not Path(sources['journal_path']).is_file()):
        raise ValueError('V5 QS verification replaces original saved method execution, same journal or fresh publication')
    projections = record['prepared']['projections']
    targets = {row['result_kind']: row['ref'] for row in projections}
    rows = {task_digest(row['ref']): row for row in projected['objects']}
    if (targets != case['source_declaration']['result_targets']
            or request['action_input']['measurement_result_refs'] != [row['ref'] for row in projections]
            or publication['objects'] != [{'ref': row['ref'], 'value': row} for row in projections]
            or any(rows.get(task_digest(row['ref'])) != row for row in fixture['objects'])
            or len(rows) != len(projected['objects'])
            or any(rows.get(task_digest(row['ref']), {}).get('value') != row for row in projections)
            or any(projected[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))):
        raise ValueError('V5 QS verification omits or changes original complete calculation/source bundle')
    configuration = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'QS-A08', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-qs-payment-published-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projected['macro_version'], 'client_version': 'role-contract-qs-fixture.v1',
            'policy_version': case['source_declaration']['policy_version'], 'model_version': 'offline-fixture-no-model.v1'}}
    return (case_file, reception_file, *upstream), case, request, configuration


def run_v5_qs_payment_verify_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('QS verification requires an explicit boolean execution choice')
    files, case, request, configuration = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-qs-payment-verify-offline-plan.v1', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'QS-A08', 'mode': 'execute_offline' if execute else 'plan_only',
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'limitations': case['limitations'], 'remaining_requirements': case['remaining_requirements']}
    for name, value in [('request', request), ('configuration', configuration), ('plan', plan), ('reception-input', files[1][2])]:
        atomic_json(directory / f'{name}.json', value)
    for index, file in enumerate(files[2:]):
        atomic_json(directory / f'calculation-input-{index}.json', file[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-qs-payment-verify-attempt.v1', 'status': 'started'}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('Original QS verification sources changed before execution')
        result = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'qs', offline=True)
        observed, evidence = result['result'], result['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        sources = configuration['settings']['source_settings']
        provenance = evidence['sources']['payment_calculation_input']
        expected_identity = {'run_id': case['run_id'], 'organization_id': sources['source_projection']['organization_id'],
            'role': 'QS', 'action_id': 'QS-A08', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        original = files[5][2]['record']['prepared']['projections'][0]
        statement = observed.get('payload', {}).get('statement', {})
        report = original['report']
        if (observed['kind'] != 'completed' or observed['payload']['choice'] != 'verify'
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or evidence['result_table'] != 'qs_payment_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed or task['output_sha256'] != task_digest(observed)
                or result['audit'] != [audit] or audit['input_sha256'] != identity['input_sha256']
                or audit['result_sha256'] != task_digest(observed) or audit['operation_id'] != identity['request_id']
                or audit['run_id'] != case['run_id'] or audit['action_id'] != 'QS-A08'
                or provenance['calculation_record_sha256'] != sources['calculation_record_sha256']
                or provenance['calculation_publication_sha256'] != sources['calculation_publication_sha256']
                or provenance['measurement_result_refs'] != request['action_input']['measurement_result_refs']
                or statement.get('contract_ref') != request['action_input']['contract_ref']
                or statement.get('source_application_ref') != request['action_input']['application_ref']
                or statement.get('calculation_ref') != original['ref']
                or any(statement.get(k) != report[k] for k in ('assessed_amount', 'recognized_amount', 'disputed_amount'))):
            raise ValueError('QS verification result or durable calculation reception changes original complete valuation')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('Original QS verification sources changed during execution')
        atomic_json(directory / 'persistent-evidence.json', evidence)
        summary = {**plan, 'status': 'original_qs_payment_verified', 'result_path': 'qs/result.json',
            'result_sha256': task_digest(result), 'record_sha256': evidence['record_sha256'],
            'payment_calculation_input': deepcopy(provenance)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_qs_payment_verify_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_qs_payment_verify_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'status': report.get('status', 'planned_not_executed'),
        'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
