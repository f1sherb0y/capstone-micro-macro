"""Plan or explicitly evaluate one synthetic V6 Bank retain input without native effects."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings
from integration.bank_role_contract_host import BankRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.bank_closeout_objects import BankCloseoutArrangementView, BankCloseoutProfileView
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


_FACTORY = 'integration.bank_role_contract_host:build_role_host'
_SOURCES = 'integration.bank_role_contract_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V6'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V6 Bank retain requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = BankRoleContractSettings.model_validate(configuration.settings)
    source = BankFixtureSourceSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'BANK-A11' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'retain'
            or context.contract_ref.id != 'BANK-A11' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'BANK-A11'
            or settings.source_factory != _SOURCES or settings.source_version != 'configured-bank-fixture-sources.v1'
            or source.action_id != 'BANK-A11' or source.allow_saved_recovery
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V6 Bank retain changes original offline action, source factory, run or snapshot')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V6 Bank retain changes complete original visible projection identities')
    arrangement = BankCloseoutArrangementView.model_validate(
        originals[Reference.model_validate(request.action_input['arrangement_ref']).key()])
    profile = BankCloseoutProfileView.model_validate(originals[arrangement.closeout_profile_ref.key()])
    expected_refs = [Reference.model_validate(value) for value in step['expected_remaining_obligation_refs']]
    if (profile.choice != 'retain' or profile.release_candidate_refs or profile.security_close_refs
            or arrangement.lender_id != projection['organization_id']
            or profile.organization_id != arrangement.lender_id or profile.arrangement_ref != arrangement.ref
            or len(set(expected_refs)) != len(expected_refs) or not expected_refs
            or set(expected_refs) != set(arrangement.remaining_obligation_refs)):
        raise ValueError('V6 retain requires the explicitly selected original unresolved duties without release candidates')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v6_bank_retain_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 Bank retain execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V6 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-bank-retain-plan.v1', 'scenario_id': 'V6', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'BANK-A11', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_remaining_obligation_refs': deepcopy(step['expected_remaining_obligation_refs']),
        'limitations': ['Isolated synthetic retain case; no native release, cash or debt effects.',
            'Other V6 actions, closure branches, connected inputs and formal behavior remain pending.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-bank-retain-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V6 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'bank', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Bank', 'action_id': 'BANK-A11', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'BANK-A11'
                or evidence['result_table'] != 'bank_closeout_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'retain'
                or result['payload']['arrangement_ref'] != request['action_input']['arrangement_ref']
                or result['payload']['release_amounts'] or result['payload']['retain_security_refs'] != request['action_input']['security_refs']
                or result['payload']['remaining_obligation_refs'] != step['expected_remaining_obligation_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V6 Bank retain did not preserve its original completed result and exact unresolved duties without transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V6 original Bank retain input changed during evaluation')
        summary = {**plan, 'mode': 'executed_offline', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result': deepcopy(result), 'real_model_calls': 0}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v6_bank_retain_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
