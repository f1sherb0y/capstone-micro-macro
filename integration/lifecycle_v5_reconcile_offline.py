"""Plan or explicitly evaluate V5 Bank existing processing from independently observed original commands."""
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
_SOURCE_FACTORY = 'integration.bank_execution_receipt_fixture_sources:build_sources'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(case_path, reception_path):
    """Inspect supplied JSON only; neither create sources nor open a journal."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != 'lifecycle-v5-reconcile-input-case.v1' or case.get('scenario_id') != 'V5'
            or case.get('origin') != 'synthetic' or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'execution_result_path', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-reconcile-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 execution requires explicit existing input and independently observed original commands/receipts')
    step = case['steps'][0]
    binding, fixture = step['offline_binding'], step['input_fixture']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    original = binding['invocation']
    context, projection = request['context'], sources['source_projection']
    rows = {task_digest(row['ref']): row for row in projection['objects']}
    baseline = fixture['objects']
    if (step['action_id'] != 'BANK-A07' or step['expected_kind'] != 'completed'
            or step['allowed_choices'] != ['execute', 'reconcile', 'cancel_unexecuted']
            or fixture['source_kind'] != 'synthetic' or request['execution_path'] != 'deterministic'
            or context['execution_mode'] != 'offline_fixture' or context['run_id'] != case['run_id']
            or context['contract_ref']['id'] != 'BANK-A07' or context['operation_id'] != step['operation_id']
            or context['actor_id'] != fixture['actor_id'] or context['business_time'] != fixture['business_time']
            or request['action_input'] != fixture['input']
            or binding['schema_factory'] != 'integration.bank_draw_handoff:bank_draw_handoff_schemas'
            or set(request) != set(original) or set(context) != set(original['context'])
            or any(request[k] != v for k, v in original.items() if k != 'context')
            or any(context[k] != v for k, v in original['context'].items()
                if k not in {'read_token', 'visible_refs', 'authorization_refs'})
            or sources['action_id'] != 'BANK-A07' or sources['allow_saved_recovery'] is not False
            or sources['organization_snapshot']['run_id'] != case['run_id']
            or len(rows) != len(projection['objects'])
            or any(rows.get(task_digest(row['ref'])) != row for row in baseline)
            or context['visible_refs'] != [row['ref'] for row in projection['objects']]
            or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
            or projection['organization_id'] != fixture['organization_id']
            or projection['macro_version'] != binding['source_projection_envelope']['macro_version']):
        raise ValueError('V5 execution reception changes original action/input/facts or omits its explicit current authorization')
    execution_file = _read(reception['execution_result_path'])
    execution = execution_file[2]
    evidence = execution['execution_evidence']
    declared = sources['execution_reception']
    identity = declared['identity']
    operation = request['action_input']['operation_context']
    task_key = task_digest([identity['run_id'], identity['organization_id'], identity['purpose'], identity['request_id']])
    if (execution['run_id'] != case['run_id'] or execution['action_id'] != 'BANK-A07'
            or execution['source_mode'] != 'fixture' or execution['result']['kind'] != 'completed'
            or execution['result']['payload']['choice'] != 'execute'
            or identity != evidence['identity'] or identity['role'] != 'Bank' or identity['action_id'] != 'BANK-A07'
            or identity['organization_id'] != projection['organization_id']
            or identity['request_id'] == context['operation_id'] or evidence['result_table'] != 'bank_execution_results'
            or Path(evidence['sources']['journal_path']).resolve() != Path(sources['journal_path']).resolve()
            or declared['source_record_sha256'] != evidence['record_sha256']
            or declared['source_result_sha256'] != task_digest(execution['result'])
            or declared['source_reading_sha256'] != evidence['source_reading_sha256']
            or operation['kind'] != 'existing' or not operation['execution_refs']
            or not isinstance(evidence['draw_approval_input'], dict)):
        raise ValueError('V5 reconciliation requires original same-Bank initiation with durable independent approval reception')
    commands = {task_digest(row['ref']): row for row in declared['executions']}
    receipts = {task_digest(row['ref']): row for row in declared['receipts']}
    if (len(commands) != len(declared['executions']) or len(receipts) != len(declared['receipts'])
            or set(commands) != {task_digest(ref) for ref in operation['execution_refs']}
            or set(receipts) != {task_digest(ref) for ref in request['action_input']['receipt_refs']}
            or len({row['command_id'] for row in commands.values()}) != len(commands)
            or len({row['business_key'] for row in commands.values()}) != len(commands)
            or any(rows.get(key, {}).get('value') != row for key, row in {**commands, **receipts}.items())):
        raise ValueError('V5 reception repeats or omits original actual command/receipt selections')
    used = set()
    for command in commands.values():
        if (command['lender_id'] != projection['organization_id']
                or command['arrangement_ref'] != request['action_input']['arrangement_ref']
                or command['approval_ref'] != execution['result']['payload']['approval_ref']
                or command['path_ref'] != execution['result']['payload']['path_ref']
                or [line['transfer'] for line in command['lines']] != execution['result']['payload']['lines']):
            raise ValueError('V5 actual command substitutes original approval, path, parties or transfers')
        for ref in command['receipt_refs']:
            key = task_digest(ref)
            if key not in receipts:
                if command['receipt_coverage'] == 'complete':
                    raise ValueError('V5 complete command history omits a receipt source')
                continue
            observed = receipts[key]
            if (key in used or observed['execution_ref'] != command['ref']
                    or any(observed[k] != command[k] for k in
                        ('lender_id', 'borrower_id', 'arrangement_ref', 'approval_ref', 'path_ref', 'command_id', 'business_key'))):
                raise ValueError('V5 actual receipt changes original command identity or is reused')
            used.add(key)
    if used != set(receipts):
        raise ValueError('V5 input includes receipts unrelated to selected original commands')
    native = declared['native_payload']
    approval = native['original_approval']
    if (approval['ref'] != execution['result']['payload']['approval_ref']
            or task_digest(approval) != evidence['draw_approval_input']['provenance']['approval_sha256']):
        raise ValueError('V5 command history replaces original independently registered approval')
    expected_native = {'schema_version': 'bank-execution-observation.v1', 'source_identity': identity,
        'source_record_sha256': evidence['record_sha256'], 'source_result_sha256': task_digest(execution['result']),
        'source_reading_sha256': evidence['source_reading_sha256'], 'original_approval': approval,
        'executions': declared['executions'], 'receipts': declared['receipts'], 'current_state': 'observed'}
    expected_relation = {'schema_version': 'bank-execution-observation-relation.v1', 'source_identity': identity,
        'source_record_sha256': evidence['record_sha256'], 'current_context_sha256': task_digest(context),
        'current_input_sha256': task_digest(request['action_input']),
        'native_payload_sha256': task_digest(expected_native), 'current_state': 'active'}
    if (native != expected_native or declared['relation_payload'] != expected_relation
            or declared['native_evidence_ref'] == declared['relation_evidence_ref']):
        raise ValueError('V5 independent native observation or current relation differs from original complete command history')
    for ref, payload in [(declared['native_evidence_ref'], expected_native),
            (declared['relation_evidence_ref'], expected_relation)]:
        observed = rows.get(task_digest(ref), {}).get('value')
        if (not isinstance(observed, dict) or observed['source_kind'] != 'synthetic'
                or observed['basis_kind'] != 'observed' or observed['content_hash'] != task_digest(payload)):
            raise ValueError('V5 command history lacks separate observed native and current relation evidence')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'BANK-A07', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-bank-execution-receipt-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projection['macro_version'], 'client_version': 'role-contract-bank-fixture.v1',
            'policy_version': 'role-contract-bank-fixture.v1', 'model_version': 'offline-fixture-no-model.v1',
            'execution_receipt_inputs': {'version': 'v5-explicit-existing-receipts.v1', 'selections': {
                context['operation_id']: {'source_task_sha256': task_key}}}}}
    return (case_file, reception_file, execution_file), case, request, config


def run_v5_reconcile_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('Bank existing processing requires an explicit boolean execution selection')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-reconcile-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'mode': 'execute_offline' if execute else 'plan_only', 'action_id': 'BANK-A07', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'allowed_choices': case['steps'][0]['allowed_choices'], 'predecessor_requirements': case['predecessor_requirements'],
        'dependent_steps': case['dependent_steps'], 'remaining_requirements': case['remaining_requirements'],
        'limitations': case['limitations']}
    for name, value in [('request', request), ('configuration', config), ('execution-result-input', files[2][2]),
            ('reception-input', files[1][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-reconcile-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 original command observation changed before evaluation')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'reconcile', offline=True)
        observed, execution = result['result'], result['execution_evidence']
        identity, audit = execution['identity'], execution['saved_audit']
        task, handoff = execution['task'], execution['execution_receipt_input']
        reception = config['settings']['source_settings']['execution_reception']
        context = request['context']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'Bank', 'action_id': 'BANK-A07', 'request_id': context['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
        selection = config['settings']['execution_receipt_inputs']['selections'][context['operation_id']]
        expected_provenance = {**selection, **{k: reception[k] for k in
            ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256')},
            'native_payload_sha256': task_digest(reception['native_payload']),
            'relation_payload_sha256': task_digest(reception['relation_payload']),
            'execution_refs': [row['ref'] for row in reception['executions']],
            'receipt_refs': [row['ref'] for row in reception['receipts']]}
        if (observed['kind'] != 'completed' or observed['payload']['choice'] not in {'reconcile', 'cancel_unexecuted'}
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or execution['result_table'] != 'bank_execution_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed
                or task['output_sha256'] != task_digest(observed) or result['audit'] != [audit]
                or audit['input_sha256'] != identity['input_sha256'] or audit['result_sha256'] != task_digest(observed)
                or audit['action_id'] != 'BANK-A07' or audit['run_id'] != case['run_id']
                or audit['operation_id'] != context['operation_id'] or audit['reading']['read_token'] != context['read_token']
                or handoff != expected_provenance
                or observed['payload']['execution_refs'] != request['action_input']['operation_context']['execution_refs']):
            raise ValueError('V5 existing decision or durable original command reception differs from supplied sources')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 original command observation changed during evaluation')
        atomic_json(directory / 'persistent-evidence.json', execution)
        summary = {**plan, 'status': 'local_bank_existing_decision_completed', 'observed_choice': observed['payload']['choice'],
            'result_path': 'reconcile/result.json', 'result_sha256': task_digest(result),
            'persistent_evidence_sha256': task_digest(execution), 'execution_receipt_input': deepcopy(handoff)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_reconcile_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True, help='Original initiation result and independent actual command/receipt history/current sources')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_reconcile_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
