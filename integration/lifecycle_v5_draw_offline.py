"""Plan or explicitly evaluate V5 Bank approval of an independently received Owner draw."""
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
_SOURCE_FACTORY = 'integration.owner_draw_bank_fixture_sources:build_sources'
_NATIVE_KINDS = frozenset({'DrawRequest', 'FinanceArrangement', 'FinanceTerms', 'DrawCapacity',
    'FundingPurpose', 'Account', 'FeeRule', 'Requirement', 'DrawBatch', 'CreditReinstatement',
    'PaymentExecution', 'PaymentReceipt', 'Obligation', 'TimeWindow'})


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(case_path, reception_path):
    """Inspect supplied JSON; no source construction, journal or approval."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != 'lifecycle-v5-draw-input-case.v1'
            or case.get('scenario_id') != 'V5' or case.get('origin') != 'synthetic'
            or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'owner_result_path', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-draw-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 Bank drawing requires explicit input and independently registered original Owner draw')
    step = case['steps'][0]
    binding, fixture = step['offline_binding'], step['input_fixture']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    original = binding['invocation']
    context, projection = request['context'], sources['source_projection']
    rows = {task_digest(row['ref']): row for row in projection['objects']}
    if (step['action_id'] != 'BANK-A06' or step['expected_kind'] != 'completed'
            or step['allowed_choices'] != ['approve_draw', 'decline_draw']
            or fixture['source_kind'] != 'synthetic' or request['execution_path'] != 'deterministic'
            or context['execution_mode'] != 'offline_fixture' or context['run_id'] != case['run_id']
            or context['contract_ref']['id'] != 'BANK-A06' or context['operation_id'] != step['operation_id']
            or context['actor_id'] != fixture['actor_id'] or context['business_time'] != fixture['business_time']
            or request['action_input'] != fixture['input']
            or binding['schema_factory'] != 'integration.bank_arrangement_handoff:bank_arrangement_handoff_schemas'
            or set(request) != set(original) or set(context) != set(original['context'])
            or any(request[k] != v for k, v in original.items() if k != 'context')
            or any(context[k] != v for k, v in original['context'].items()
                if k not in {'read_token', 'visible_refs', 'authorization_refs'})
            or sources['action_id'] != 'BANK-A06' or sources['allow_saved_recovery'] is not False
            or sources['organization_snapshot']['run_id'] != case['run_id']
            or len(rows) != len(projection['objects'])
            or any(rows.get(task_digest(row['ref'])) != row for row in fixture['objects'])
            or context['visible_refs'] != [row['ref'] for row in projection['objects']]
            or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
            or projection['organization_id'] != fixture['organization_id']
            or projection['macro_version'] != binding['source_projection_envelope']['macro_version']):
        raise ValueError('V5 Bank reception changes original policy/input/current facility or explicit authorization')
    owner_file = _read(reception['owner_result_path'])
    owner = owner_file[2]
    evidence = owner['execution_evidence']
    history, registration = sources['owner_history'], sources['registration']
    identity, draw = history['identity'], registration['owner_authorization']
    arrangement, signed = registration['owner_arrangement'], registration['owner_arrangement_receipt']
    received = registration['draw_request']
    payload = owner['result']['payload']
    task_key = task_digest([identity['run_id'], identity['organization_id'], identity['purpose'], identity['request_id']])
    if (owner['run_id'] != case['run_id'] or owner['action_id'] != 'OWN-A06' or owner['source_mode'] != 'fixture'
            or owner['result']['kind'] != 'completed' or payload['choice'] != 'draw_request'
            or identity != evidence['identity'] or identity['role'] != 'Owner' or identity['action_id'] != 'OWN-A06'
            or evidence['result_table'] != 'owner_payment_results'
            or Path(evidence['sources']['journal_path']).resolve() != Path(history['source_settings']['journal_path']).resolve()
            or Path(sources['journal_path']).resolve() == Path(history['source_settings']['journal_path']).resolve()
            or Path(sources['journal_path']).resolve() != Path(evidence['sources']['bank_arrangement']['bank_sources']['journal_path']).resolve()
            or registration['source_identity'] != identity or registration['run_id'] != case['run_id']
            or registration['source_record_sha256'] != evidence['record_sha256']
            or registration['source_result_sha256'] != task_digest(owner['result'])
            or registration['source_reading_sha256'] != evidence['source_reading_sha256']
            or registration['current_state'] != 'submitted' or registration['sharing_authorized'] is not True
            or received['ref'] != request['action_input']['draw_request_ref']
            or received['arrangement_ref'] != request['action_input']['arrangement_ref']
            or received['arrangement_ref'] != arrangement['ref'] or draw['arrangement_ref'] != arrangement['ref']
            or received['arrangement_ref'] != payload['arrangement_ref']
            or draw['amount'] != payload['amount'] or received['requested_amount'] != payload['amount']
            or draw['beneficiary_id'] != payload['beneficiary_id']
            or received['transfer_lines'] != case['source_declaration']['expected_transfer_lines']
            or received['purpose_ref'] != request['action_input']['purpose_ref']
            or received['borrower_id'] != identity['organization_id'] or draw['organization_id'] != identity['organization_id']
            or received['lender_id'] != projection['organization_id'] or received['status'] != 'submitted'
            or history['request']['context']['business_time'] != context['business_time']
            or task_digest(history['request']['action_input']) != identity['input_sha256']
            or registration['recipient_organization_id'] != projection['organization_id']
            or registration['recipient_actor_id'] != context['actor_id']
            or registration['recipient_function_ref'] != context['function_ref']
            or registration['recipient_authorization_refs'] != context['authorization_refs']
            or rows.get(task_digest(received['ref']), {}).get('value') != received):
        raise ValueError('V5 Bank draw substitutes original Owner amount/parties/journals or independent native request')
    prior = evidence['payment_arrangement_input']
    if (signed['ref'] != prior['receipt_ref']
            or any(signed[k] != prior[k] for k in ('source_task_sha256', 'source_record_sha256', 'source_result_sha256', 'source_reading_sha256'))
            or signed['arrangement_ref'] != arrangement['ref'] or signed['arrangement_sha256'] != task_digest(arrangement)
            or draw['condition_evidence_refs'] != payload['condition_refs']):
        raise ValueError('V5 Bank draw omits original durable signed facility reception or condition evidence')
    receipt = rows.get(task_digest(registration['receipt_ref']), {}).get('value')
    native = rows.get(task_digest(registration['native_evidence_ref']), {}).get('value')
    if (not isinstance(receipt, dict) or not isinstance(native, dict)
            or receipt['source_task_sha256'] != task_key
            or any(receipt[k] != registration[k] for k in ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256'))
            or receipt['native_record_sha256'] != task_digest(registration)
            or receipt['owner_draw_authorization_ref'] != draw['ref'] or receipt['owner_draw_authorization_sha256'] != task_digest(draw)
            or receipt['draw_request_ref'] != received['ref'] or receipt['draw_request_sha256'] != task_digest(received)
            or receipt['transfer_lines'] != received['transfer_lines']
            or receipt['condition_relations'] != registration['condition_relations']
            or native['source_kind'] != 'synthetic' or native['basis_kind'] != 'observed'
            or native['content_hash'] != task_digest(registration)):
        raise ValueError('V5 actual request receipt lacks original lineage, full transfers or observed registration')
    declared = {task_digest(row['ref']): row for row in registration['bank_sources']}
    current = {key: row for key, row in rows.items() if row['ref']['kind'] in _NATIVE_KINDS}
    native_body = registration['native_request']
    if (len(declared) != len(registration['bank_sources']) or declared != current
            or native_body['schema_version'] != 'bank-owner-draw-registration.v1'
            or native_body['run_id'] != case['run_id'] or native_body['source_identity'] != identity
            or native_body['source_record_sha256'] != evidence['record_sha256']
            or native_body['owner_authorization'] != draw or native_body['owner_arrangement'] != arrangement
            or native_body['owner_arrangement_receipt'] != signed or native_body['draw_request'] != received
            or native_body['condition_relations'] != registration['condition_relations']
            or native_body['bank_sources'] != registration['bank_sources']
            or task_digest(native_body['owner_source_reading']) != evidence['source_reading_sha256']):
        raise ValueError('V5 native mapping changes original complete Owner history or explicit current Bank sources')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'BANK-A06', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-bank-owner-draw-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projection['macro_version'], 'client_version': 'role-contract-bank-fixture.v1',
            'policy_version': 'role-contract-bank-fixture.v1', 'model_version': 'offline-fixture-no-model.v1',
            'owner_draw_request_inputs': {'version': 'v5-explicit-owner-draw-request.v1', 'selections': {
                context['operation_id']: {'source_task_sha256': task_key, 'receipt_ref': registration['receipt_ref']}}}}}
    return (case_file, reception_file, owner_file), case, request, config


def run_v5_draw_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('Bank draw approval requires an explicit boolean execution selection')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-draw-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'mode': 'execute_offline' if execute else 'plan_only', 'action_id': 'BANK-A06', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'allowed_choices': case['steps'][0]['allowed_choices'], 'predecessor_requirements': case['predecessor_requirements'],
        'dependent_steps': case['dependent_steps'], 'remaining_requirements': case['remaining_requirements'],
        'limitations': case['limitations']}
    for name, value in [('request', request), ('configuration', config), ('owner-result-input', files[2][2]),
            ('reception-input', files[1][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-draw-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Bank draw approval source changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'bank', offline=True)
        observed, execution = result['result'], result['execution_evidence']
        identity, audit = execution['identity'], execution['saved_audit']
        task, handoff = execution['task'], execution['owner_draw_request_input']
        registration = config['settings']['source_settings']['registration']
        context = request['context']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'Bank', 'action_id': 'BANK-A06', 'request_id': context['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
        selection = config['settings']['owner_draw_request_inputs']['selections'][context['operation_id']]
        expected_provenance = {**selection, **{k: registration[k] for k in
            ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256')},
            'execution_source_reading_sha256': execution['source_reading_sha256']}
        profile = next(row['value'] for row in case['steps'][0]['input_fixture']['objects']
            if row['ref']['kind'] == 'DrawDecisionProfile')
        if (observed['kind'] != 'completed' or observed['payload']['choice'] not in plan['allowed_choices']
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or execution['result_table'] != 'bank_draw_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed
                or task['output_sha256'] != task_digest(observed) or result['audit'] != [audit]
                or audit['input_sha256'] != identity['input_sha256'] or audit['result_sha256'] != task_digest(observed)
                or audit['action_id'] != 'BANK-A06' or audit['run_id'] != case['run_id']
                or audit['operation_id'] != context['operation_id'] or audit['reading']['read_token'] != context['read_token']
                or handoff != expected_provenance
                or observed['payload']['choice'] == 'approve_draw' and any(observed['payload'][k] != profile[k]
                    for k in ('approved_amount', 'transfer_lines'))):
            raise ValueError('V5 Bank result or durable original request reception differs from explicit approval')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Bank draw approval source changed during execution')
        atomic_json(directory / 'persistent-evidence.json', execution)
        summary = {**plan, 'status': 'local_bank_draw_decision_completed', 'observed_choice': observed['payload']['choice'],
            'result_path': 'bank/result.json', 'result_sha256': task_digest(result),
            'persistent_evidence_sha256': task_digest(execution), 'owner_draw_request_input': deepcopy(handoff)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_draw_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True, help='Explicit Owner draw reception, signed facility/current Bank sources and original Owner history')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_draw_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
