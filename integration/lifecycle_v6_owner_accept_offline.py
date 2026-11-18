"""Plan or explicitly evaluate one synthetic V6 scoped Owner acceptance opinion."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings
from integration.owner_role_contract_host import OwnerRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_closeout_objects import (
    OwnerCloseoutCaseView, OwnerCloseoutStateView, OwnerCloseoutProfileView,
    OwnerCloseoutContractView, ContractorContinuingResponsibilityView, owner_closeout_schemas,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_SOURCES = 'integration.owner_role_contract_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V6'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V6 Owner acceptance requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = OwnerRoleContractSettings.model_validate(configuration.settings)
    source = OwnerFixtureSourceSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'OWN-A12' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'accept_scope'
            or context.contract_ref.id != 'OWN-A12' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'OWN-A12'
            or settings.source_factory != _SOURCES or settings.source_version != 'configured-owner-fixture-sources.v1'
            or source.action_id != 'OWN-A12' or source.allow_saved_recovery
            or any(value is not None for name, value in settings.model_dump().items() if name.endswith('_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V6 Owner acceptance changes original offline action, factory, run or snapshot')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V6 Owner acceptance changes complete original visible source identities')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V6 Owner acceptance aliases independent organization source identities')
    schemas = owner_closeout_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V6 offline Owner acceptance evidence must declare its synthetic origin')

    def original(reference, schema):
        return schema.model_validate(originals[reference.key()])

    anchor = original(context.scope.ref, OwnerCloseoutCaseView)
    state = original(anchor.closeout_state_ref, OwnerCloseoutStateView)
    profile = original(state.decision_profile_ref, OwnerCloseoutProfileView)
    contract = original(profile.contract_ref, OwnerCloseoutContractView)
    if (request.action_input['scope_ref'] != context.scope.model_dump(mode='json')
            or state.organization_id != projection['organization_id'] or state.scope != context.scope
            or state.coverage != 'complete' or state.as_of != context.business_time
            or profile.state_ref != state.ref or profile.scope != context.scope or profile.choice != 'accept_scope'
            or profile.organization_id != state.organization_id or profile.actor_id != context.actor_id
            or profile.function_ref != context.function_ref or profile.authority_ref not in context.authorization_refs
            or contract.ref not in state.contract_refs or contract.owner_id != state.organization_id
            or contract.coverage != 'complete' or contract.as_of != context.business_time
            or profile.handover_ref is None or profile.handover_ref not in contract.handover_refs
            or profile.handover_ref.model_dump(mode='json') != step['expected_handover_ref']
            or profile.accepted_scope is None or profile.accepted_scope.model_dump(mode='json') != step['expected_accepted_scope']
            or [value.model_dump(mode='json') for value in profile.remaining_issue_refs] != step['expected_remaining_issue_refs']):
        raise ValueError('V6 Owner acceptance changes original state, contract, specific scope or retained issues')
    for field in ('handover_refs', 'verification_refs', 'permit_refs', 'defect_refs', 'settlement_refs'):
        references = [Reference.model_validate(value) for value in request.action_input[field]]
        if len(set(references)) != len(references) or set(references) != set(getattr(state, field)):
            raise ValueError('V6 Owner acceptance omits original state history: ' + field)
    duties = [value.model_dump(mode='json') for value in state.responsibility_refs]
    if not duties or duties != step['expected_continuing_responsibility_refs']:
        raise ValueError('V6 Owner acceptance changes its declared remaining responsibilities')
    for reference in state.responsibility_refs:
        duty = original(reference, ContractorContinuingResponsibilityView)
        if (duty.contract_ref not in state.contract_refs or duty.organization_id != contract.contractor_id
                or duty.remaining.model_dump() != {'state': 'known', 'value': True}):
            raise ValueError('V6 Owner acceptance substitutes or discharges a continuing duty')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v6_owner_accept_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 Owner acceptance execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V6 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-owner-accept-plan.v1', 'scenario_id': 'V6', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'OWN-A12', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_handover_ref': deepcopy(step['expected_handover_ref']),
        'expected_accepted_scope': deepcopy(step['expected_accepted_scope']),
        'expected_remaining_issue_refs': deepcopy(step['expected_remaining_issue_refs']),
        'source_continuing_responsibility_refs': deepcopy(step['expected_continuing_responsibility_refs']),
        'limitations': ['Isolated synthetic scoped acceptance opinion; guarantee remains an original input source.',
            'No native reception/acceptance, legal use permission, asset transfer, settlement or full V6 chain proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-owner-accept-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V6 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Owner', 'action_id': 'OWN-A12', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'OWN-A12'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'owner_closeout_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'accept_scope'
                or result['payload']['handover_ref'] != step['expected_handover_ref']
                or result['payload']['accepted_scope'] != step['expected_accepted_scope']
                or result['payload']['remaining_issue_refs'] != step['expected_remaining_issue_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V6 Owner acceptance did not preserve its exact scoped opinion and remaining issues without transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V6 original Owner acceptance input changed during evaluation')
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
    print(run_v6_owner_accept_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
