"""Plan or explicitly evaluate V5 Bank initiation from the original approved-draw journal."""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from integration.bank_role_contract_host import build_role_host
from integration.role_contract_host import run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest

_FACTORY = 'integration.bank_role_contract_host:build_role_host'
_SOURCE_FACTORY = 'integration.bank_draw_execution_fixture_sources:build_sources'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(case_path, reception_path, *, scenario_id='V5',
        case_schema='lifecycle-v5-execution-input-case.v1', expected_kind='completed'):
    """Inspect supplied JSON only; neither create sources nor open a journal."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') != case_schema or case.get('scenario_id') != scenario_id
            or case.get('origin') != 'synthetic' or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'draw_result_path', 'request', 'source_settings'}
            or reception['schema_version'] != 'lifecycle-v5-execution-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 execution requires one explicit original input and independently registered original draw approval')
    step = case['steps'][0]
    binding, fixture = step['offline_binding'], step['input_fixture']
    request, sources = deepcopy(reception['request']), deepcopy(reception['source_settings'])
    original = binding['invocation']
    context, projection = request['context'], sources['source_projection']
    rows = {task_digest(row['ref']): row for row in projection['objects']}
    baseline = fixture['objects']
    if (step['action_id'] != 'BANK-A07' or step['expected_kind'] != expected_kind
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
    draw_file = _read(reception['draw_result_path'])
    draw = draw_file[2]
    evidence = draw['execution_evidence']
    relation = sources['draw_reception']
    identity, basis = relation['identity'], relation['basis']
    approval, arrangement = relation['approval'], relation['arrangement']
    operation = request['action_input']['operation_context']
    native = relation['native_payload']
    if (draw['run_id'] != case['run_id'] or draw['action_id'] != 'BANK-A06' or draw['source_mode'] != 'fixture'
            or draw['result']['kind'] != 'completed' or draw['result']['payload']['choice'] != 'approve_draw'
            or identity != evidence['identity'] or identity['role'] != 'Bank' or identity['action_id'] != 'BANK-A06'
            or identity['organization_id'] != projection['organization_id']
            or evidence['result_table'] != 'bank_draw_results'
            or Path(evidence['sources']['journal_path']).resolve() != Path(sources['journal_path']).resolve()
            or basis['draw_record_sha256'] != evidence['record_sha256']
            or basis['draw_input_sha256'] != identity['input_sha256']
            or basis['draw_context_sha256'] != identity['context_sha256']
            or basis['draw_result_sha256'] != task_digest(draw['result'])
            or basis['draw_audit_sha256'] != task_digest(evidence['saved_audit'])
            or basis['draw_source_reading_sha256'] != evidence['source_reading_sha256']
            or operation['kind'] != 'initiate' or approval['ref'] != operation['draw_approval_ref']
            or basis['approval_ref'] != approval['ref'] or arrangement['ref'] != request['action_input']['arrangement_ref']
            or approval['arrangement_ref'] != arrangement['ref'] or approval['terms_ref'] != arrangement['terms_ref']
            or approval['lender_id'] != projection['organization_id'] or arrangement['lender_id'] != projection['organization_id']
            or approval['borrower_id'] != arrangement['borrower_id']
            or Decimal(approval['amount']['value']) != Decimal(draw['result']['payload']['approved_amount']['value'])
            or approval['amount']['currency'] != draw['result']['payload']['approved_amount']['currency']
            or [line['transfer'] for line in approval['lines']] != draw['result']['payload']['transfer_lines']
            or operation['lines'] != draw['result']['payload']['transfer_lines']
            or basis['approval_sha256'] != task_digest(approval)
            or basis['execution_arrangement_sha256'] != task_digest(arrangement)
            or basis['draw_conditions_sha256'] != task_digest(draw['result']['payload']['conditions'])
            or rows.get(task_digest(basis['ref']), {}).get('value') != basis
            or rows.get(task_digest(approval['ref']), {}).get('value') != approval
            or rows.get(task_digest(arrangement['ref']), {}).get('value') != arrangement):
        raise ValueError('V5 execution replaces original approved draw, journal, independent approval or full transfer lines')
    expected_native = {'schema_version': 'bank-draw-approval-registration.v1', 'source_identity': identity,
        'source_record_sha256': evidence['record_sha256'], 'native_approval_id': basis['native_approval_id'],
        'native_event_id': basis['native_event_id'], 'registered_at': basis['registered_at'],
        'draw_request': native['draw_request'], 'draw_arrangement': native['draw_arrangement'], 'draw_terms': native['draw_terms'],
        'draw_conditions': draw['result']['payload']['conditions'], 'approval': approval, 'arrangement': arrangement,
        'current_state': 'registered'}
    expected_relation = {'schema_version': 'bank-draw-approval-relation.v1', 'source_identity': identity,
        'basis': {k: v for k, v in basis.items() if k not in {'evidence_refs', 'relation_evidence_refs'}},
        'current_state': 'active'}
    if (native != expected_native or relation['relation_payload'] != expected_relation
            or basis['native_source_sha256'] != task_digest(native)
            or basis['draw_request_sha256'] != task_digest(native['draw_request'])
            or basis['draw_request_ref'] != native['draw_request']['ref']
            or basis['draw_arrangement_sha256'] != task_digest(native['draw_arrangement'])
            or basis['draw_terms_sha256'] != task_digest(native['draw_terms'])
            or approval['batch_key'] != native['draw_request']['batch_key']
            or approval['terms_ref'] != native['draw_terms']['ref']):
        raise ValueError('V5 independent approval registration changes original batch, terms, conditions or relation')
    refs = [basis['native_evidence_ref'], *basis['relation_evidence_refs']]
    if len({task_digest(ref) for ref in refs}) != len(refs) or len(refs) < 2:
        raise ValueError('V5 execution needs separate native approval and independently authored relation evidence')
    for index, ref in enumerate(refs):
        observed = rows.get(task_digest(ref), {}).get('value')
        expected_hash = task_digest(native if index == 0 else expected_relation)
        if (not isinstance(observed, dict) or observed['source_kind'] != 'synthetic'
                or observed['basis_kind'] != 'observed' or observed['content_hash'] != expected_hash):
            raise ValueError('V5 approval registration or relation lacks exact independently observed evidence')
    config = {'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
        'settings': {'action_id': 'BANK-A07', 'source_factory': _SOURCE_FACTORY,
            'source_version': 'configured-bank-draw-execution-fixture-sources.v1', 'source_settings': sources,
            'macro_version': projection['macro_version'], 'client_version': 'role-contract-bank-fixture.v1',
            'policy_version': 'role-contract-bank-fixture.v1', 'model_version': 'offline-fixture-no-model.v1',
            'draw_approval_inputs': {'version': 'v5-explicit-execution-approval.v1', 'selections': {
                context['operation_id']: {'draw_identity': identity, 'basis_ref': basis['ref']}}}}}
    return (case_file, reception_file, draw_file), case, request, config


def run_v5_execution_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('Bank execution requires an explicit boolean selection')
    files, case, request, config = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-execution-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'mode': 'execute_offline' if execute else 'plan_only', 'action_id': 'BANK-A07', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'allowed_choices': case['steps'][0]['allowed_choices'], 'predecessor_requirements': case['predecessor_requirements'],
        'dependent_steps': case['dependent_steps'], 'remaining_requirements': case['remaining_requirements'],
        'limitations': case['limitations']}
    for name, value in [('request', request), ('configuration', config), ('draw-result-input', files[2][2]),
            ('reception-input', files[1][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-execution-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 execution source input changed before evaluation')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'execution', offline=True)
        observed, execution = result['result'], result['execution_evidence']
        identity, audit = execution['identity'], execution['saved_audit']
        task, handoff = execution['task'], execution['draw_approval_input']
        reception = config['settings']['source_settings']['draw_reception']
        basis = reception['basis']
        context = request['context']
        expected_identity = {'run_id': case['run_id'], 'organization_id': case['steps'][0]['input_fixture']['organization_id'],
            'role': 'Bank', 'action_id': 'BANK-A07', 'request_id': context['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
        expected_provenance = {k: basis[k] for k in ('draw_task_sha256', 'draw_record_sha256', 'draw_input_sha256',
            'draw_context_sha256', 'draw_result_sha256', 'draw_audit_sha256', 'draw_source_reading_sha256',
            'draw_request_sha256', 'draw_arrangement_sha256', 'draw_terms_sha256', 'draw_conditions_sha256',
            'execution_arrangement_sha256', 'approval_sha256')}
        expected_provenance.update(basis_ref=basis['ref'], basis_sha256=task_digest(basis),
            native_approval_id=basis['native_approval_id'], native_event_id=basis['native_event_id'])
        operation = request['action_input']['operation_context']
        if (observed['kind'] != 'completed' or observed['payload']['choice'] not in plan['allowed_choices']
                or any(identity.get(k) != v for k, v in expected_identity.items())
                or execution['result_table'] != 'bank_execution_results' or task['identity'] != identity
                or task['state'] != 'output_formed' or task['output'] != observed
                or task['output_sha256'] != task_digest(observed) or result['audit'] != [audit]
                or audit['input_sha256'] != identity['input_sha256'] or audit['result_sha256'] != task_digest(observed)
                or audit['action_id'] != 'BANK-A07' or audit['run_id'] != case['run_id']
                or audit['operation_id'] != context['operation_id'] or audit['reading']['read_token'] != context['read_token']
                or handoff != {'kind': 'prepared', 'source_mode': 'fixture', 'provenance': expected_provenance,
                    'draw_identity': reception['identity'], 'approval_ref': operation['draw_approval_ref']}
                or observed['payload']['choice'] == 'execute' and (
                    observed['payload']['approval_ref'] != operation['draw_approval_ref']
                    or observed['payload']['path_ref'] != operation['path_ref'] or observed['payload']['lines'] != operation['lines'])):
            raise ValueError('V5 original execution decision or durable approval lineage differs from supplied input')
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 execution source input changed during evaluation')
        atomic_json(directory / 'persistent-evidence.json', execution)
        summary = {**plan, 'status': 'local_bank_execution_decision_completed', 'observed_choice': observed['payload']['choice'],
            'result_path': 'execution/result.json', 'result_sha256': task_digest(result),
            'persistent_evidence_sha256': task_digest(execution), 'draw_approval_input': deepcopy(handoff)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_execution_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True, help='Original Bank draw result, independent registered approval/relation and current Bank sources')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v5_execution_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
