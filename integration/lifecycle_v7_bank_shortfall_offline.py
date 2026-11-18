"""Plan or explicitly evaluate the supplied synthetic V7 cash-shortfall case."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.bank_role_contract_host import build_role_host
from integration.lifecycle_v5_execution_offline import _FACTORY, _prepare
from integration.role_contract_host import run_role_contract
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest


_CODE = 'actual_same_currency_path_cash_after_original_reservations_available'


def run_v7_bank_shortfall_offline(*, case_path, reception_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V7 shortfall execution selection must be an explicit boolean')
    files, case, request, config = _prepare(case_path, reception_path, scenario_id='V7',
        case_schema='lifecycle-v7-bank-shortfall-input-case.v1', expected_kind='deferred')
    step = case['steps'][0]
    if step.get('expected_reason_code') != 'actual_bank_currency_path_funding_shortfall' or step.get('expected_condition_code') != _CODE:
        raise ValueError('V7 shortfall must explicitly expect the original actual-cash waiting condition')
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v7-bank-shortfall-plan.v1', 'scenario_id': 'V7',
        'run_id': case['run_id'], 'action_id': 'BANK-A07', 'origin': 'synthetic',
        'mode': 'execute_offline' if execute else 'plan_only',
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'expected_kind': 'deferred', 'expected_reason_code': step['expected_reason_code'],
        'expected_condition_code': _CODE, 'predecessor_requirements': deepcopy(case['predecessor_requirements']),
        'limitations': ['Independent explicit synthetic cash/authority input; it does not establish actual Bank cash or a real transport timeout.',
            'Original same-run approved-draw journal and independently registered approval reception remain required.']}
    for name, value in (('input', case), ('reception-input', files[1][2]), ('draw-result-input', files[2][2]),
            ('request', request), ('configuration', config), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v7-bank-shortfall-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V7 original case, reception or draw result changed before evaluation')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'bank', offline=True)
        observed, evidence = result['result'], result['execution_evidence']
        task, identity = evidence['task'], evidence['identity']
        operation = request['action_input']['operation_context']
        condition = observed.get('resume_condition', {})
        context = request['context']
        expected_identity = {'run_id': case['run_id'], 'organization_id': step['input_fixture']['organization_id'],
            'role': 'Bank', 'action_id': 'BANK-A07', 'request_id': context['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
        if (result['source_mode'] != 'fixture' or observed['kind'] != 'deferred'
                or observed.get('reason_code') != step['expected_reason_code']
                or condition.get('condition_code') != _CODE or condition.get('trigger') != 'dependency_change'
                or condition.get('object_refs') != [operation['funding_account_ref'], operation['path_ref']]
                or task['identity'] != identity or any(identity.get(key) != value for key, value in expected_identity.items())
                or task['state'] != 'waiting_input' or task['output'] is not None
                or task['submission'] is not None or task['receipt'] is not None
                or evidence['result_table'] != 'bank_execution_results' or result['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(observed)
                or evidence['draw_approval_input'] is None):
            raise ValueError('V7 cash shortfall did not retain its original incomplete task and exact registered-approval waiting condition')
        summary = {**plan, 'mode': 'evaluated_offline', 'result': deepcopy(observed),
            'identity': deepcopy(identity), 'record_sha256': evidence['record_sha256'],
            'draw_approval_input': deepcopy(evidence['draw_approval_input']),
            'limitations': ['This case only evaluates cash-shortfall waiting; it neither replenishes cash nor wakes/submits another task.',
                'Formal current-source profiles and other V7 exceptions remain separately unverified.']}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': 'deferred'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v7_bank_shortfall_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    result = run_v7_bank_shortfall_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline)
    print(result['mode'])


if __name__ == '__main__':
    main()
