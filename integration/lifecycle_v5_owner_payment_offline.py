"""Plan or explicitly evaluate V5 Owner payment from independently issued QS certificates and actual cash."""
import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from integration.owner_role_contract_host import build_role_host
from integration.role_contract_host import run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest

_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_SOURCE_FACTORY = 'integration.qs_certificate_owner_fixture_sources:build_sources'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(case_path, reception_path):
    """Inspect independently supplied plain JSON without factories or journals."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != 'lifecycle-v5-owner-payment-input-case.v1'
            or case.get('scenario_id') != 'V5' or case.get('origin') != 'synthetic' or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'owner_reconcile_result_path',
                'qs_result_paths', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-owner-payment-reception.v1'
            or reception['input_case_sha256'] != case_file[1] or not reception['qs_result_paths']):
        raise ValueError('V5 payment requires explicit authorization, original Owner/QS results and independent certificate mapping')
    step = case['steps'][0]
    binding, fixture = step['offline_binding'], step['input_fixture']
    declaration, original = case['source_declaration'], binding['invocation']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    context, projection = request['context'], sources['source_projection']
    rows = {task_digest(row['ref']): row for row in projection['objects']}
    if (step['action_id'] != 'OWN-A06' or step['expected_kind'] != 'completed'
            or step['allowed_choices'] != ['draw_request', 'pay', 'repay', 'dispute', 'negotiate', 'reconcile']
            or fixture['source_kind'] != 'synthetic' or request['execution_path'] != 'deterministic'
            or set(request) != set(original) or set(context) != set(original['context'])
            or any(request[k] != v for k, v in original.items() if k != 'context')
            or any(context[k] != v for k, v in original['context'].items()
                if k not in {'read_token', 'visible_refs', 'authorization_refs'})
            or not all(ref in context['authorization_refs'] for ref in original['context']['authorization_refs'])
            or context['execution_mode'] != 'offline_fixture' or sources['action_id'] != 'OWN-A06'
            or sources['allow_saved_recovery'] is not False or len(rows) != len(projection['objects'])
            or any(rows.get(task_digest(row['ref'])) != row for row in fixture['objects'])
            or context['visible_refs'] != [row['ref'] for row in projection['objects']]
            or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
            or projection['organization_id'] != fixture['organization_id']
            or projection['macro_version'] != binding['source_projection_envelope']['macro_version']):
        raise ValueError('V5 payment changes explicit current instruction, input, authority or supplied original facts')
    snapshot, baseline = sources['organization_snapshot'], binding['organization_snapshot']
    grants = {task_digest(row['ref']): row for row in snapshot['authorizations']}
    if (snapshot['run_id'] != case['run_id'] or snapshot['organizations'] != baseline['organizations']
            or snapshot['inactive_authorization_refs'] != baseline['inactive_authorization_refs']
            or len(grants) != len(snapshot['authorizations'])
            or any(grants.get(task_digest(row['ref'])) != row for row in baseline['authorizations'])):
        raise ValueError('V5 payment substitutes original current Owner organization or authorization')
    owner_file = _read(reception['owner_reconcile_result_path'])
    owner = owner_file[2]
    own_evidence = owner['execution_evidence']
    if (owner['run_id'] != case['run_id'] or owner['action_id'] != 'OWN-A06' or owner['source_mode'] != 'fixture'
            or owner['result']['kind'] != 'completed' or owner['result']['payload']['choice'] != 'reconcile'
            or own_evidence['identity']['organization_id'] != projection['organization_id']
            or own_evidence['identity']['request_id'] != 'v5-owner-reconcile-24'
            or own_evidence['identity']['run_id'] != case['run_id']
            or own_evidence['identity']['role'] != 'Owner' or own_evidence['identity']['action_id'] != 'OWN-A06'
            or own_evidence['result_table'] != 'owner_payment_results'
            or Path(own_evidence['sources']['journal_path']).resolve() != Path(sources['journal_path']).resolve()
            or own_evidence['task']['output'] != owner['result']
            or own_evidence['task']['output_sha256'] != task_digest(owner['result'])
            or own_evidence['task']['identity'] != own_evidence['identity']
            or owner['audit'] != [own_evidence['saved_audit']]
            or own_evidence['saved_audit']['result_sha256'] != task_digest(owner['result'])
            or not isinstance(own_evidence['bank_execution_input'], dict)):
        raise ValueError('V5 payment lacks original same-journal Owner reconciliation and durable Bank reception')
    histories = {task_digest(row['identity']): row for row in sources['histories']}
    registrations = {task_digest(row['source_identity']): row for row in sources['registrations']}
    mapping = sources['mapping']
    if (len(histories) != len(sources['histories']) or len(registrations) != len(sources['registrations'])
            or set(histories) != set(registrations) or mapping['receipt_refs'] != declaration['certificate_receipt_refs']
            or len(registrations) != len(mapping['receipt_refs'])
            or mapping['recipient_organization_id'] != projection['organization_id']
            or mapping['recipient_actor_id'] != context['actor_id'] or mapping['recipient_function_ref'] != context['function_ref']
            or mapping['recipient_authorization_refs'] != context['authorization_refs'] or mapping['run_id'] != case['run_id']):
        raise ValueError('V5 payment omits complete independent certificate selections or receiver authority')
    qs_files = tuple(_read(path) for path in reception['qs_result_paths'])
    seen = set()
    for file in qs_files:
        result, evidence = file[2]['result'], file[2]['execution_evidence']
        identity = evidence['identity']
        key = task_digest(identity)
        if key in seen or key not in histories:
            raise ValueError('V5 payment repeats or substitutes an explicitly selected original QS task')
        seen.add(key)
        history, registration = histories[key], registrations[key]
        receipt = registration['receipt']
        task_key = task_digest([identity['run_id'], identity['organization_id'], identity['purpose'], identity['request_id']])
        if (file[2]['run_id'] != case['run_id'] or file[2]['action_id'] != 'QS-A08' or file[2]['source_mode'] != 'fixture'
                or identity['role'] != 'QS' or identity['action_id'] != 'QS-A08' or identity['run_id'] != case['run_id']
                or result['kind'] != 'completed' or result['payload']['choice'] not in {'certify', 'correct_certificate'}
                or evidence['result_table'] != 'qs_payment_results' or evidence['task']['identity'] != identity
                or evidence['task']['output'] != result or evidence['task']['output_sha256'] != task_digest(result)
                or file[2]['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(result)
                or registration['source_record_sha256'] != evidence['record_sha256']
                or registration['source_reading_sha256'] != evidence['source_reading_sha256']
                or registration['source_result_sha256'] != task_digest(result)
                or receipt['source_task_sha256'] != task_key
                or any(receipt[k] != registration[k] for k in ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256'))
                or history['identity']['versions']['client'] != history['client_version']
                or history['identity']['versions']['model'] != history['model_version']
                or history['model_version'] != 'offline-fixture-no-model.v1'
                or history['request']['context']['business_time'] != context['business_time']
                or Path(history['source_settings']['journal_path']).resolve() != Path(evidence['sources']['journal_path']).resolve()
                or Path(history['source_settings']['journal_path']).resolve() == Path(sources['journal_path']).resolve()
                or rows.get(task_digest(receipt['ref']), {}).get('value') != receipt
                or registration['native_issuance']['statement'] != result['payload']['statement']):
            raise ValueError('V5 payment certificate replaces original QS decision, statement, journal or received issuance')
        payload = deepcopy(registration)
        del payload['receipt']['native_record_sha256']
        native = rows.get(task_digest(receipt['native_evidence_ref']), {}).get('value')
        if (receipt['native_record_sha256'] != task_digest(payload) or not isinstance(native, dict)
                or native['source_kind'] != 'synthetic' or native['basis_kind'] != 'observed'
                or native['content_hash'] != task_digest(payload)):
            raise ValueError('V5 actual certificate reception lacks independently observed complete original registration')
    if seen != set(histories):
        raise ValueError('V5 payment omits one or more original certificate result files')
    for row in [*mapping['obligations'], *mapping['components']]:
        if rows.get(task_digest(row['ref']), {}).get('value') != row or row['as_of'] != context['business_time']:
            raise ValueError('V5 payment changes actual current due/paid/offset source snapshots')
    for row in mapping['settlement_sources']:
        if rows.get(task_digest(row['ref']), {}).get('value') != row['value']:
            raise ValueError('V5 payment changes independently observed account/funding/reservation/execution history')
    account = rows[task_digest(request['action_input']['account_refs'][0])]['value']
    obligation = rows[task_digest(request['action_input']['due_refs'][0])]['value']
    expected = declaration['required_actual_snapshot']
    for value, names in ((account, ('actual_cash', 'restricted_cash', 'reserved_cash')),
            (obligation, ('actual_due', 'actual_paid', 'actual_offset'))):
        for name in names:
            state = value[name]
            if (state['state'] != 'known' or Fraction(state['value']['value']) != Fraction(expected[name])
                    or state['value']['currency'] != expected['currency']):
                raise ValueError('V5 payment observed amount differs from explicit independent current snapshot requirement')
    selections = [{'source_task_sha256': row['receipt']['source_task_sha256'], 'receipt_ref': row['receipt']['ref']}
        for row in sources['registrations']]
    allocated = any(row['receipt'].get('allocations') is not None for row in sources['registrations'])
    selection = {'certificates': selections} if allocated or len(selections) > 1 else selections[0]
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'OWN-A06', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-owner-qs-certificate-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projection['macro_version'], 'client_version': 'role-contract-owner-fixture.v1',
            'policy_version': declaration['owner_policy_version'], 'model_version': 'offline-fixture-no-model.v1',
            'certificate_inputs': {'version': 'v5-explicit-certified-payment.v1', 'selections': {context['operation_id']: selection}}}}
    return (case_file, reception_file, owner_file, *qs_files), case, request, config


def run_v5_owner_payment_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('Owner payment requires an explicit boolean execution selection')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-owner-payment-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'mode': 'execute_offline' if execute else 'plan_only', 'action_id': 'OWN-A06', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'allowed_choices': case['steps'][0]['allowed_choices'], 'predecessor_requirements': case['predecessor_requirements'],
        'dependent_steps': case['dependent_steps'], 'remaining_requirements': case['remaining_requirements'],
        'limitations': case['limitations']}
    for name, value in [('request', request), ('configuration', config), ('owner-reconcile-result-input', files[2][2]),
            ('reception-input', files[1][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    for index, file in enumerate(files[3:]):
        atomic_json(directory / f'qs-result-input-{index}.json', file[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-owner-payment-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Owner payment source changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=True)
        observed, execution = result['result'], result['execution_evidence']
        identity, audit = execution['identity'], execution['saved_audit']
        task, handoff = execution['task'], execution['certificate_input']
        context = request['context']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'Owner', 'action_id': 'OWN-A06', 'request_id': context['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
        registrations = config['settings']['source_settings']['registrations']
        selection = config['settings']['certificate_inputs']['selections'][context['operation_id']]
        provenance = [{'source_task_sha256': row['receipt']['source_task_sha256'], 'receipt_ref': row['receipt']['ref'],
            **{k: row[k] for k in ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256')}} for row in registrations]
        expected_provenance = ({'certificates': provenance} if 'certificates' in selection else provenance[0])
        expected_provenance['execution_source_reading_sha256'] = execution['source_reading_sha256']
        authorization = case['source_declaration']['payment_authorization']
        snapshot = case['source_declaration']['required_actual_snapshot']
        free = Fraction(snapshot['actual_cash']) - Fraction(snapshot['restricted_cash']) - Fraction(snapshot['reserved_cash'])
        requested = Fraction(authorization['lines'][0]['amount']['value'])
        expected_amount = min(free, requested)
        if (observed['kind'] != 'completed' or observed['payload']['choice'] not in plan['allowed_choices']
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or execution['result_table'] != 'owner_payment_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed
                or task['output_sha256'] != task_digest(observed) or result['audit'] != [audit]
                or audit['input_sha256'] != identity['input_sha256'] or audit['result_sha256'] != task_digest(observed)
                or audit['action_id'] != 'OWN-A06' or audit['run_id'] != case['run_id']
                or audit['operation_id'] != context['operation_id'] or audit['reading']['read_token'] != context['read_token']
                or handoff != expected_provenance
                or observed['payload']['choice'] != 'pay' or observed['payload']['account_ref'] != authorization['account_ref']
                or len(observed['payload']['lines']) != 1
                or observed['payload']['lines'][0]['obligation_ref'] != authorization['lines'][0]['obligation_ref']
                or observed['payload']['lines'][0]['payee_id'] != authorization['lines'][0]['payee_id']
                or observed['payload']['lines'][0]['component_refs'] != [p['component_ref'] for p in authorization['lines'][0]['component_amounts']]
                or observed['payload']['lines'][0]['amount']['currency'] != snapshot['currency']
                or Fraction(observed['payload']['lines'][0]['amount']['value']) != expected_amount):
            raise ValueError('V5 Owner result or durable certificate reception differs from original explicit payment')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 Owner payment source changed during execution')
        atomic_json(directory / 'persistent-evidence.json', execution)
        summary = {**plan, 'status': 'local_owner_partial_payment_decision_completed', 'observed_choice': observed['payload']['choice'],
            'result_path': 'owner/result.json', 'result_sha256': task_digest(result),
            'persistent_evidence_sha256': task_digest(execution), 'certificate_input': deepcopy(handoff)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_owner_payment_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True, help='Original Owner reconciliation and QS results, independently issued certificates and actual financial snapshots')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_owner_payment_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
