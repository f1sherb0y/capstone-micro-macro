"""Plan or explicitly evaluate V5 Owner reconciliation from independently observed original Bank receipts."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.owner_role_contract_host import build_role_host
from integration.role_contract_host import run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest

_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_SOURCE_FACTORY = 'integration.bank_execution_owner_fixture_sources:build_sources'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(case_path, reception_path):
    """Inspect explicit supplied JSON; do not open journals or construct sources."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != 'lifecycle-v5-owner-reconcile-input-case.v1'
            or case.get('scenario_id') != 'V5' or case.get('origin') != 'synthetic'
            or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'bank_reconcile_result_path',
                'owner_draw_result_path', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-owner-reconcile-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 Owner reconciliation requires explicit input and original Bank/Owner execution lineage')
    step = case['steps'][0]
    binding, fixture = step['offline_binding'], step['input_fixture']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    original, declaration = binding['invocation'], case['source_declaration']
    context, projection = request['context'], sources['source_projection']
    rows = {task_digest(row['ref']): row for row in projection['objects']}
    if (step['action_id'] != 'OWN-A06' or step['expected_kind'] != 'completed'
            or step['allowed_choices'] != ['draw_request', 'pay', 'repay', 'dispute', 'negotiate', 'reconcile']
            or fixture['source_kind'] != 'synthetic' or request['execution_path'] != 'deterministic'
            or context['execution_mode'] != 'offline_fixture' or context['run_id'] != case['run_id']
            or context['contract_ref']['id'] != 'OWN-A06' or context['operation_id'] != step['operation_id']
            or context['actor_id'] != fixture['actor_id'] or context['business_time'] != fixture['business_time']
            or request['action_input'] != fixture['input']
            or binding['schema_factory'] != 'src.actions.contracts.owner_payment_objects:owner_payment_schemas'
            or set(request) != set(original) or set(context) != set(original['context'])
            or any(request[k] != v for k, v in original.items() if k != 'context')
            or any(context[k] != v for k, v in original['context'].items()
                if k not in {'read_token', 'visible_refs', 'authorization_refs'})
            or not all(ref in context['authorization_refs'] for ref in original['context']['authorization_refs'])
            or sources['action_id'] != 'OWN-A06' or sources['allow_saved_recovery'] is not False
            or sources['organization_snapshot']['run_id'] != case['run_id']
            or sources['owner_policy_version'] != declaration['owner_policy_version']
            or len(rows) != len(projection['objects'])
            or any(rows.get(task_digest(row['ref'])) != row for row in fixture['objects'])
            or context['visible_refs'] != [row['ref'] for row in projection['objects']]
            or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
            or projection['organization_id'] != fixture['organization_id']
            or projection['macro_version'] != binding['source_projection_envelope']['macro_version']):
        raise ValueError('V5 reception changes current Owner input, explicit authority or original historical draw facts')
    snapshot, baseline_snapshot = sources['organization_snapshot'], binding['organization_snapshot']
    grants = {task_digest(row['ref']): row for row in snapshot['authorizations']}
    if (len(grants) != len(snapshot['authorizations'])
            or any(grants.get(task_digest(row['ref'])) != row for row in baseline_snapshot['authorizations'])
            or snapshot['organizations'] != baseline_snapshot['organizations']
            or snapshot['inactive_authorization_refs'] != baseline_snapshot['inactive_authorization_refs']):
        raise ValueError('V5 reception substitutes historical or explicit current Owner authority')
    bank_file, owner_file = _read(reception['bank_reconcile_result_path']), _read(reception['owner_draw_result_path'])
    registration, history = sources['registration'], sources['bank_history']
    for file, action, choice, role, prefix, journal in (
            (bank_file, 'BANK-A07', 'reconcile', 'Bank', 'source', history['source_settings']['journal_path']),
            (owner_file, 'OWN-A06', 'draw_request', 'Owner', 'owner_draw', sources['journal_path'])):
        result, evidence = file[2]['result'], file[2]['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        if (file[2]['run_id'] != case['run_id'] or file[2]['action_id'] != action or file[2]['source_mode'] != 'fixture'
                or result['kind'] != 'completed' or result['payload']['choice'] != choice
                or identity['run_id'] != case['run_id'] or identity['action_id'] != action or identity['role'] != role
                or identity['request_id'] == context['operation_id']
                or evidence['result_table'] != ('bank_execution_results' if role == 'Bank' else 'owner_payment_results')
                or task['identity'] != identity or task['output'] != result or task['output_sha256'] != task_digest(result)
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or file[2]['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or audit['input_sha256'] != identity['input_sha256'] or audit['run_id'] != case['run_id']
                or audit['action_id'] != action or audit['operation_id'] != identity['request_id']
                or registration[prefix + '_identity'] != identity
                or registration[prefix + '_record_sha256'] != evidence['record_sha256']
                or registration[prefix + '_result_sha256'] != task_digest(result)
                or registration[prefix + '_reading_sha256'] != evidence['source_reading_sha256']
                or Path(evidence['sources']['journal_path']).resolve() != Path(journal).resolve()):
            raise ValueError('V5 reception lacks original completed durable Bank/Owner history and matching source hashes')
    bank_identity = bank_file[2]['execution_evidence']['identity']
    owner_identity = owner_file[2]['execution_evidence']['identity']
    task_key = task_digest([bank_identity['run_id'], bank_identity['organization_id'],
        bank_identity['purpose'], bank_identity['request_id']])
    owner_execution, bank_execution = registration['owner_execution'], registration['bank_execution']
    draw = registration['owner_authorization']
    bank_rows = {task_digest(row['ref']): row['value'] for row in history['source_settings']['source_projection']['objects']}
    if (registration['schema_version'] != 'bank-execution-owner-registration.v1'
            or registration['run_id'] != case['run_id'] or registration['current_state'] != 'observed'
            or registration['sharing_authorized'] is not True or history['identity'] != bank_identity
            or history['request']['context']['business_time'] != context['business_time']
            or history['request']['context']['run_id'] != case['run_id']
            or task_digest(history['request']['action_input']) != bank_identity['input_sha256']
            or bank_identity['organization_id'] != bank_execution['lender_id']
            or owner_identity['organization_id'] != projection['organization_id']
            or Path(sources['journal_path']).resolve() == Path(history['source_settings']['journal_path']).resolve()
            or registration['receipt_ref'] != declaration['reception_ref']
            or registration['recipient_organization_id'] != projection['organization_id']
            or registration['recipient_actor_id'] != context['actor_id']
            or registration['recipient_function_ref'] != context['function_ref']
            or registration['recipient_authorization_refs'] != context['authorization_refs']
            or registration['scope'] != context['scope']
            or owner_execution['ref'] != declaration['owner_execution_ref']
            or request['action_input']['pending_execution_refs'] != [owner_execution['ref']]
            or owner_execution['authorization_ref'] != draw['ref'] or owner_execution['operation'] != 'draw_request'
            or any(draw[k] != owner_file[2]['result']['payload'][k] for k in ('arrangement_ref', 'amount', 'beneficiary_id'))
            or bank_execution['ref'] not in bank_file[2]['result']['payload']['execution_refs']
            or any(rows.get(task_digest(obj['ref']), {}).get('value') != obj for obj in (owner_execution, draw))
            or any(bank_rows.get(task_digest(obj['ref'])) != obj
                for obj in [bank_execution, *registration['bank_receipts']])
            or any(rows.get(task_digest(row['ref']), {}).get('value') != row['value'] for row in registration['owner_sources'])):
        raise ValueError('V5 received execution substitutes original draw, selected Bank history or observed financial sources')
    received = rows.get(task_digest(registration['receipt_ref']), {}).get('value')
    native = rows.get(task_digest(registration['native_evidence_ref']), {}).get('value')
    terminal = registration['owner_receipt']
    if (not isinstance(received, dict) or not isinstance(native, dict)
            or received['source_task_sha256'] != task_key
            or any(received[k] != registration[k] for k in ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256'))
            or received['bank_execution_ref'] != bank_execution['ref'] or received['owner_execution_ref'] != owner_execution['ref']
            or received['owner_execution_sha256'] != task_digest(owner_execution)
            or received['native_record_sha256'] != task_digest(registration)
            or received['native_evidence_ref'] != registration['native_evidence_ref']
            or native['source_kind'] != 'synthetic' or native['basis_kind'] != 'observed'
            or native['content_hash'] != task_digest(registration)
            or terminal is not None and rows.get(task_digest(terminal['ref']), {}).get('value') != terminal):
        raise ValueError('V5 settlement reception lacks independently observed original command/receipt/effect evidence')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'OWN-A06', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-owner-bank-execution-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projection['macro_version'], 'client_version': 'role-contract-owner-fixture.v1',
            'policy_version': sources['owner_policy_version'], 'model_version': 'offline-fixture-no-model.v1',
            'bank_execution_inputs': {'version': 'v5-explicit-owner-bank-execution.v1', 'selections': {
                context['operation_id']: {'source_task_sha256': task_key, 'reception_ref': registration['receipt_ref']}}}}}
    return (case_file, reception_file, bank_file, owner_file), case, request, config


def run_v5_owner_reconcile_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('Owner reconciliation requires an explicit boolean execution selection')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-owner-reconcile-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'mode': 'execute_offline' if execute else 'plan_only', 'action_id': 'OWN-A06', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'allowed_choices': case['steps'][0]['allowed_choices'], 'predecessor_requirements': case['predecessor_requirements'],
        'dependent_steps': case['dependent_steps'], 'remaining_requirements': case['remaining_requirements'],
        'limitations': case['limitations']}
    for name, value in [('request', request), ('configuration', config), ('bank-reconcile-result-input', files[2][2]), ('owner-draw-result-input', files[3][2]),
            ('reception-input', files[1][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-owner-reconcile-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Owner settlement source changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=True)
        observed, execution = result['result'], result['execution_evidence']
        identity, audit = execution['identity'], execution['saved_audit']
        task, handoff = execution['task'], execution['bank_execution_input']
        registration = config['settings']['source_settings']['registration']
        context = request['context']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'Owner', 'action_id': 'OWN-A06', 'request_id': context['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
        selection = config['settings']['bank_execution_inputs']['selections'][context['operation_id']]
        expected_provenance = {**selection, **{k: registration[k] for k in
            ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256')},
            'execution_source_reading_sha256': execution['source_reading_sha256']}
        if (observed['kind'] != 'completed' or observed['payload']['choice'] not in plan['allowed_choices']
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or execution['result_table'] != 'owner_payment_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed
                or task['output_sha256'] != task_digest(observed) or result['audit'] != [audit]
                or audit['input_sha256'] != identity['input_sha256'] or audit['result_sha256'] != task_digest(observed)
                or audit['action_id'] != 'OWN-A06' or audit['run_id'] != case['run_id']
                or audit['operation_id'] != context['operation_id'] or audit['reading']['read_token'] != context['read_token']
                or handoff != expected_provenance
                or observed['payload']['choice'] != 'reconcile'
                or observed['payload']['execution_refs'] != request['action_input']['pending_execution_refs']):
            raise ValueError('V5 Owner result or durable Bank execution reception differs from original explicit reconciliation')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Owner settlement source changed during execution')
        atomic_json(directory / 'persistent-evidence.json', execution)
        summary = {**plan, 'status': 'local_owner_reconciliation_completed', 'observed_choice': observed['payload']['choice'],
            'result_path': 'owner/result.json', 'result_sha256': task_digest(result),
            'persistent_evidence_sha256': task_digest(execution), 'bank_execution_input': deepcopy(handoff)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_owner_reconcile_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True, help='Original Bank reconciliation and Owner draw results, independent native settlement and current Owner sources')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_owner_reconcile_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
