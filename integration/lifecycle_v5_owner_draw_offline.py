"""Plan or explicitly evaluate V5 Owner drawing from an independently signed facility."""
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
_SOURCE_FACTORY = 'integration.bank_arrangement_owner_fixture_sources:build_sources'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(case_path, reception_path):
    """Inspect supplied JSON; no factories, journal or banking operation."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != 'lifecycle-v5-owner-draw-input-case.v1'
            or case.get('scenario_id') != 'V5' or case.get('origin') != 'synthetic'
            or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'arrangement_result_path', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-owner-draw-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 drawing requires one explicit input and independent signed facility reception')
    step = case['steps'][0]
    binding, fixture = step['offline_binding'], step['input_fixture']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    original = binding['invocation']
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
            or sources['action_id'] != 'OWN-A06' or sources['allow_saved_recovery'] is not False
            or sources['organization_snapshot']['run_id'] != case['run_id']
            or len(rows) != len(projection['objects'])
            or any(rows.get(task_digest(row['ref'])) != row for row in fixture['objects'])
            or context['visible_refs'] != [row['ref'] for row in projection['objects']]
            or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
            or projection['organization_id'] != fixture['organization_id']
            or projection['macro_version'] != binding['source_projection_envelope']['macro_version']):
        raise ValueError('V5 draw reception changes original input/decision or omits explicit current authorization')
    bank_file = _read(reception['arrangement_result_path'])
    bank = bank_file[2]
    evidence = bank['execution_evidence']
    history, registration = sources['bank_history'], sources['registration']
    identity, arrangement = history['identity'], registration['arrangement']
    offer = registration['offer']
    borrower, lender = registration['borrower_acceptance'], registration['lender_confirmation']
    task_key = task_digest([identity['run_id'], identity['organization_id'], identity['purpose'], identity['request_id']])
    payload = bank['result']['payload']
    if (bank['run_id'] != case['run_id'] or bank['action_id'] != 'BANK-A05' or bank['source_mode'] != 'fixture'
            or bank['result']['kind'] != 'completed' or payload['choice'] != 'confirm'
            or identity != evidence['identity'] or identity['role'] != 'Bank' or identity['action_id'] != 'BANK-A05'
            or evidence['result_table'] != 'bank_arrangement_results'
            or Path(evidence['sources']['journal_path']).resolve() != Path(history['source_settings']['journal_path']).resolve()
            or Path(sources['journal_path']).resolve() == Path(history['source_settings']['journal_path']).resolve()
            or registration['source_identity'] != identity or registration['run_id'] != case['run_id']
            or registration['source_record_sha256'] != evidence['record_sha256']
            or registration['source_result_sha256'] != task_digest(bank['result'])
            or registration['source_reading_sha256'] != evidence['source_reading_sha256']
            or registration['current_state'] != 'registered' or registration['sharing_authorized'] is not True
            or arrangement['ref'] not in request['action_input']['arrangement_refs']
            or arrangement['borrower_id'] != projection['organization_id'] or arrangement['lender_id'] != identity['organization_id']
            or arrangement['offer_ref'] != offer['ref'] or offer['ref'] != payload['offer_ref']
            or arrangement['borrower_acceptance_ref'] != borrower['ref'] or borrower['ref'] != payload['acceptance_ref']
            or arrangement['lender_confirmation_ref'] != lender['ref']
            or borrower['offer_ref'] != offer['ref'] or lender['offer_ref'] != offer['ref']
            or borrower['decision'] != 'accept' or lender['decision'] != 'accept'
            or borrower['organization_id'] != arrangement['borrower_id'] or lender['organization_id'] != arrangement['lender_id']
            or history['request']['context']['business_time'] != context['business_time']
            or task_digest(history['request']['action_input']) != identity['input_sha256']
            or registration['recipient_organization_id'] != projection['organization_id']
            or registration['recipient_actor_id'] != context['actor_id']
            or registration['recipient_function_ref'] != context['function_ref']
            or registration['recipient_authorization_refs'] != context['authorization_refs']
            or arrangement['as_of'] != context['business_time']
            or any(rows.get(task_digest(obj['ref']), {}).get('value') != obj for obj in (arrangement, borrower, lender))):
        raise ValueError('V5 draw substitutes original Bank confirmation, both acceptances or actual current facility')
    receipt = rows.get(task_digest(registration['receipt_ref']), {}).get('value')
    native = rows.get(task_digest(registration['native_evidence_ref']), {}).get('value')
    if (not isinstance(receipt, dict) or not isinstance(native, dict)
            or receipt['source_task_sha256'] != task_key
            or any(receipt[k] != registration[k] for k in ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256'))
            or receipt['native_record_sha256'] != task_digest(registration)
            or receipt['arrangement_ref'] != arrangement['ref'] or receipt['arrangement_sha256'] != task_digest(arrangement)
            or receipt['accepted_terms'] != offer['terms']
            or receipt['confirmed_conditions_sha256'] != task_digest(payload['conditions'])
            or receipt['signed_at'] != registration['signed_at']
            or native['source_kind'] != 'synthetic' or native['basis_kind'] != 'observed'
            or native['content_hash'] != task_digest(registration)):
        raise ValueError('V5 signed facility receipt lacks exact original confirmation and observed independent registration')
    facility = registration['native_facility']
    expected_facility = {'schema_version': 'bank-signed-facility.v1', 'run_id': case['run_id'],
        'source_identity': identity, 'source_record_sha256': evidence['record_sha256'],
        'accepted_terms': offer['terms'], 'confirmed_conditions': payload['conditions'], 'arrangement': arrangement,
        'borrower_acceptance': borrower, 'lender_confirmation': lender,
        'condition_mappings': registration['condition_mappings'], 'signed_at': registration['signed_at'],
        'current_state': 'registered'}
    if facility != expected_facility:
        raise ValueError('V5 independent facility declaration replaces original full terms, conditions or current draw history')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'OWN-A06', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-owner-bank-arrangement-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projection['macro_version'], 'client_version': 'role-contract-owner-fixture.v1',
            'policy_version': 'role-contract-owner-fixture.v1', 'model_version': 'offline-fixture-no-model.v1',
            'payment_arrangement_inputs': {'version': 'v5-explicit-owner-draw-arrangement.v1', 'selections': {
                context['operation_id']: {'source_task_sha256': task_key, 'receipt_ref': registration['receipt_ref']}}}}}
    return (case_file, reception_file, bank_file), case, request, config


def run_v5_owner_draw_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('Owner drawing requires an explicit boolean execution selection')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-owner-draw-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'mode': 'execute_offline' if execute else 'plan_only', 'action_id': 'OWN-A06', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'allowed_choices': case['steps'][0]['allowed_choices'], 'predecessor_requirements': case['predecessor_requirements'],
        'dependent_steps': case['dependent_steps'], 'remaining_requirements': case['remaining_requirements'],
        'limitations': case['limitations']}
    for name, value in [('request', request), ('configuration', config), ('arrangement-result-input', files[2][2]),
            ('reception-input', files[1][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-owner-draw-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Owner drawing source changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=True)
        observed, execution = result['result'], result['execution_evidence']
        identity, audit = execution['identity'], execution['saved_audit']
        task, handoff = execution['task'], execution['payment_arrangement_input']
        registration = config['settings']['source_settings']['registration']
        context = request['context']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'Owner', 'action_id': 'OWN-A06', 'request_id': context['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
        selection = config['settings']['payment_arrangement_inputs']['selections'][context['operation_id']]
        expected_provenance = {**selection, **{k: registration[k] for k in
            ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256')},
            'execution_source_reading_sha256': execution['source_reading_sha256']}
        draw = case['source_declaration']['draw_authorization']
        if (observed['kind'] != 'completed' or observed['payload']['choice'] not in plan['allowed_choices']
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or execution['result_table'] != 'owner_payment_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed
                or task['output_sha256'] != task_digest(observed) or result['audit'] != [audit]
                or audit['input_sha256'] != identity['input_sha256'] or audit['result_sha256'] != task_digest(observed)
                or audit['action_id'] != 'OWN-A06' or audit['run_id'] != case['run_id']
                or audit['operation_id'] != context['operation_id'] or audit['reading']['read_token'] != context['read_token']
                or handoff != expected_provenance
                or observed['payload']['choice'] == 'draw_request' and any(observed['payload'][k] != draw[k]
                    for k in ('arrangement_ref', 'amount', 'beneficiary_id'))
                or observed['payload']['choice'] == 'draw_request'
                    and observed['payload']['condition_refs'] != draw['condition_evidence_refs']):
            raise ValueError('V5 Owner result or durable signed facility reception differs from original explicit draw')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Owner drawing source changed during execution')
        atomic_json(directory / 'persistent-evidence.json', execution)
        summary = {**plan, 'status': 'local_owner_payment_decision_completed', 'observed_choice': observed['payload']['choice'],
            'result_path': 'owner/result.json', 'result_sha256': task_digest(result),
            'persistent_evidence_sha256': task_digest(execution), 'payment_arrangement_input': deepcopy(handoff)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_owner_draw_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True, help='Explicit signed facility reception, current sources and original Bank history')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_owner_draw_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
