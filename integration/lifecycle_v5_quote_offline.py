"""Plan or explicitly continue V5 quotation from the original recorded credit journal."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.bank_role_contract_host import build_role_host
from integration.role_contract_host import run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest

_FACTORY = 'integration.bank_role_contract_host:build_role_host'
_SOURCE_FACTORY = 'integration.bank_credit_quote_fixture_sources:build_sources'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(case_path, reception_path):
    """Inspect supplied JSON only; neither create sources nor open a journal."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != 'lifecycle-v5-quote-input-case.v1' or case.get('scenario_id') != 'V5'
            or case.get('origin') != 'synthetic' or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'credit_result_path', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-quote-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 quotation requires one explicit original input and independently recorded credit reception')
    step = case['steps'][0]
    binding, fixture = step['offline_binding'], step['input_fixture']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    original = binding['invocation']
    context, projection = request['context'], sources['source_projection']
    rows = {task_digest(row['ref']): row for row in projection['objects']}
    baseline = fixture['objects']
    if (step['action_id'] != 'BANK-A04' or step['expected_kind'] != 'completed'
            or step['allowed_choices'] != ['offer', 'conditional_offer', 'decline']
            or fixture['source_kind'] != 'synthetic' or request['execution_path'] != 'deterministic'
            or context['execution_mode'] != 'offline_fixture' or context['run_id'] != case['run_id']
            or context['contract_ref']['id'] != 'BANK-A04' or context['operation_id'] != step['operation_id']
            or context['actor_id'] != fixture['actor_id'] or context['business_time'] != fixture['business_time']
            or request['action_input'] != fixture['input']
            or binding['schema_factory'] != 'integration.bank_credit_handoff:bank_credit_handoff_schemas'
            or set(request) != set(original) or set(context) != set(original['context'])
            or any(request[k] != v for k, v in original.items() if k != 'context')
            or any(context[k] != v for k, v in original['context'].items()
                if k not in {'read_token', 'visible_refs', 'authorization_refs'})
            or sources['action_id'] != 'BANK-A04' or sources['allow_saved_recovery'] is not False
            or sources['organization_snapshot']['run_id'] != case['run_id']
            or len(rows) != len(projection['objects'])
            or any(rows.get(task_digest(row['ref'])) != row for row in baseline)
            or context['visible_refs'] != [row['ref'] for row in projection['objects']]
            or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
            or projection['organization_id'] != fixture['organization_id']
            or projection['macro_version'] != binding['source_projection_envelope']['macro_version']):
        raise ValueError('V5 quotation reception changes original action/input/facts or omits its explicit current authorization')
    credit_file = _read(reception['credit_result_path'])
    credit = credit_file[2]
    evidence = credit['execution_evidence']
    relation = sources['credit_reception']
    identity, basis = relation['identity'], relation['basis']
    assessment, recorded = relation['assessment'], relation['recorded']
    if (credit['run_id'] != case['run_id'] or credit['action_id'] != 'BANK-A03' or credit['source_mode'] != 'fixture'
            or credit['result']['kind'] != 'completed'
            or credit['result']['payload']['choice'] not in ['recommend', 'conditional', 'decline']
            or identity != evidence['identity'] or identity['role'] != 'Bank' or identity['action_id'] != 'BANK-A03'
            or identity['organization_id'] != projection['organization_id']
            or evidence['result_table'] != 'bank_credit_results'
            or Path(evidence['sources']['journal_path']).resolve() != Path(sources['journal_path']).resolve()
            or basis['credit_record_sha256'] != evidence['record_sha256']
            or basis['credit_input_sha256'] != identity['input_sha256']
            or basis['credit_context_sha256'] != identity['context_sha256']
            or basis['credit_result_sha256'] != task_digest(credit['result'])
            or basis['credit_audit_sha256'] != task_digest(evidence['saved_audit'])
            or basis['credit_source_reading_sha256'] != evidence['source_reading_sha256']
            or assessment['application_ref'] != request['action_input']['application_ref']
            or assessment['product_ref'] != request['action_input']['product_ref']
            or assessment['ref'] != request['action_input']['assessment_ref']
            or assessment['review_payload'] != credit['result']['payload']
            or task_digest(assessment['review_input']) != identity['input_sha256']
            or assessment['status'] != 'recorded' or recorded['input'] != assessment['review_input']
            or recorded['payload'] != assessment['review_payload']
            or recorded['ref'] != assessment['recorded_decision_ref']
            or basis['assessment_sha256'] != task_digest(assessment)
            or basis['recorded_decision_sha256'] != task_digest(recorded)
            or rows.get(task_digest(basis['ref']), {}).get('value') != basis
            or rows.get(task_digest(assessment['ref']), {}).get('value') != assessment
            or rows.get(task_digest(recorded['ref']), {}).get('value') != recorded):
        raise ValueError('V5 quote declaration substitutes the original review, journal or independent recorded assessment')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'BANK-A04', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-bank-credit-quote-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projection['macro_version'], 'client_version': 'role-contract-bank-fixture.v1',
            'policy_version': 'role-contract-bank-fixture.v1', 'model_version': 'offline-fixture-no-model.v1',
            'credit_inputs': {'version': 'v5-explicit-quote-credit.v1', 'selections': {
                context['operation_id']: {'credit_identity': identity, 'basis_ref': basis['ref']}}}}}
    return (case_file, reception_file, credit_file), case, request, config


def run_v5_quote_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('Quote execution requires an explicit boolean selection')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-quote-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'mode': 'execute_offline' if execute else 'plan_only', 'action_id': 'BANK-A04', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'allowed_choices': case['steps'][0]['allowed_choices'], 'predecessor_requirements': case['predecessor_requirements'],
        'dependent_steps': case['dependent_steps'], 'remaining_requirements': case['remaining_requirements'],
        'limitations': case['limitations']}
    atomic_json(directory / 'request.json', request)
    atomic_json(directory / 'configuration.json', config)
    atomic_json(directory / 'credit-result-input.json', files[2][2])
    atomic_json(directory / 'reception-input.json', files[1][2])
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-quote-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 quotation source input changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'quote', offline=True)
        observed, execution = result['result'], result['execution_evidence']
        identity, audit = execution['identity'], execution['saved_audit']
        task, handoff = execution['task'], execution['credit_input']
        reception = config['settings']['source_settings']['credit_reception']
        basis = reception['basis']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'Bank', 'action_id': 'BANK-A04', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        expected_provenance = {k: basis[k] for k in ('credit_task_sha256', 'credit_record_sha256', 'credit_input_sha256',
            'credit_context_sha256', 'credit_result_sha256', 'credit_audit_sha256', 'credit_source_reading_sha256',
            'assessment_sha256', 'recorded_decision_sha256')}
        expected_provenance.update(basis_ref=basis['ref'], basis_sha256=task_digest(basis),
            native_record_id=basis['native_record_id'], native_event_id=basis['native_event_id'])
        if (observed['kind'] != 'completed' or observed['payload']['choice'] not in plan['allowed_choices']
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or execution['result_table'] != 'bank_quote_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed
                or task['output_sha256'] != task_digest(observed) or result['audit'] != [audit]
                or audit['input_sha256'] != identity['input_sha256'] or audit['result_sha256'] != task_digest(observed)
                or audit['action_id'] != 'BANK-A04' or audit['run_id'] != case['run_id']
                or audit['operation_id'] != request['context']['operation_id']
                or audit['reading']['read_token'] != request['context']['read_token']
                or handoff != {'kind': 'prepared', 'source_mode': 'fixture', 'provenance': expected_provenance,
                    'credit_identity': reception['identity']}):
            raise ValueError('V5 original quotation result or durable review lineage does not match supplied sources')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 quotation source input changed during execution')
        atomic_json(directory / 'persistent-evidence.json', execution)
        summary = {**plan, 'status': 'local_quotation_completed', 'observed_choice': observed['payload']['choice'],
            'result_path': 'quote/result.json', 'result_sha256': task_digest(result),
            'persistent_evidence_sha256': task_digest(execution), 'credit_input': deepcopy(handoff)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_quote_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True, help='Complete explicit recorded-review lineage and current quotation sources')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_quote_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
