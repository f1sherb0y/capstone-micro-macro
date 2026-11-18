"""Plan or explicitly evaluate one synthetic V6 Owner resume proposal."""
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
from src.actions.contracts.owner_continuation_objects import (
    OwnerContinuationProfileView, OwnerContinuationStateView, OwnerContinuationDutyView,
    OwnerContinuationCommitmentView, OwnerContinuationVerificationView, owner_continuation_schemas,
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
        raise ValueError('V6 Owner resume requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = OwnerRoleContractSettings.model_validate(configuration.settings)
    source = OwnerFixtureSourceSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'OWN-A13' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'resume'
            or context.contract_ref.id != 'OWN-A13' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'OWN-A13'
            or settings.source_factory != _SOURCES or settings.source_version != 'configured-owner-fixture-sources.v1'
            or source.action_id != 'OWN-A13' or source.allow_saved_recovery
            or any(value is not None for name, value in settings.model_dump().items() if name.endswith('_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V6 Owner resume changes original offline action, factory, run or snapshot')
    rows = projection['objects']
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if (len(set(identities)) != len(identities)
            or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]):
        raise ValueError('V6 Owner resume aliases organization identities or changes original visible sources')
    schemas = owner_continuation_schemas()
    originals = {}
    for row in rows:
        reference = Reference.model_validate(row['ref'])
        if reference.key() in originals:
            raise ValueError('V6 Owner resume repeats original source identities')
        originals[reference.key()] = schemas.validate_projection(reference, row['value'])
        if reference.kind == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V6 offline Owner resume evidence must declare its synthetic origin')

    def original(reference, schema):
        value = originals[reference.key()]
        if not isinstance(value, schema):
            raise ValueError('V6 Owner resume changes an original concrete source')
        return value

    inputs = request.action_input
    profile = original(Reference.model_validate(inputs['continuation_profile_ref']), OwnerContinuationProfileView)
    state = original(profile.state_ref, OwnerContinuationStateView)
    if (inputs['scope_ref'] != context.scope.model_dump(mode='json')
            or profile.choice != 'resume' or profile.scope != context.scope or state.scope != context.scope
            or profile.organization_id != projection['organization_id'] or state.organization_id != profile.organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs
            or state.coverage != 'complete' or state.as_of != context.business_time
            or profile.scope_choice.model_dump(mode='json') != step['expected_scope']
            or not state.obligation_refs or profile.retained_obligation_refs != state.obligation_refs
            or [value.model_dump(mode='json') for value in profile.retained_obligation_refs] != step['expected_retained_obligation_refs']
            or profile.release_candidate_refs or profile.transfer_plan_ref is not None):
        raise ValueError('V6 Owner resume changes original current scope, retained debt or release/transfer intent')
    for field in ('risk_refs', 'contract_refs', 'resource_refs', 'obligation_refs'):
        references = [Reference.model_validate(value) for value in inputs[field]]
        if len(set(references)) != len(references) or set(references) != set(getattr(state, field)):
            raise ValueError('V6 Owner resume omits original state history: ' + field)
    if ([value.model_dump(mode='json') for value in state.retained_duty_refs] != step['expected_continuing_duty_refs']
            or not state.retained_duty_refs
            or [value.model_dump(mode='json') for value in state.resource_refs] != step['expected_held_resource_refs']
            or not state.resource_refs):
        raise ValueError('V6 Owner resume changes original continuing duties or held resources')
    for reference in state.retained_duty_refs:
        duty = original(reference, OwnerContinuationDutyView)
        if duty.remains.model_dump() != {'state': 'known', 'value': True} or not set(duty.obligation_refs) <= set(state.obligation_refs):
            raise ValueError('V6 Owner resume discharges a declared duty or substitutes its retained obligation')
    for reference in state.resource_refs:
        if original(reference, OwnerContinuationCommitmentView).status != 'held':
            raise ValueError('V6 Owner resume changes an original held resource')
    if (not profile.readiness_refs or len(set(profile.readiness_refs)) != len(profile.readiness_refs)
            or [value.model_dump(mode='json') for value in profile.readiness_refs] != step['expected_readiness_refs']):
        raise ValueError('V6 Owner resume requires its exact current readiness checks')
    checked = {}
    for reference in profile.readiness_refs:
        check = original(reference, OwnerContinuationVerificationView)
        if (check.state_ref != state.ref or check.state_sha256 != task_digest(state.model_dump(mode='json'))
                or check.as_of != context.business_time or not check.source_digests):
            raise ValueError('V6 Owner resume reuses an earlier state or empty source readiness check')
        for source_digest in check.source_digests:
            if task_digest(originals[source_digest.source_ref.key()].model_dump(mode='json')) != source_digest.content_sha256:
                raise ValueError('V6 Owner resume changes an original checked source version')
        checked.setdefault(check.contract_ref, set()).add(check.family)
    targets = {None, *state.contract_refs}
    families = {'funding', 'resources', 'permits', 'rights', 'versions', 'safety'}
    if set(checked) != targets or any(not families <= checked[target] for target in targets):
        raise ValueError('V6 Owner resume omits a current readiness family for scope or contract')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v6_owner_resume_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 Owner resume execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V6 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-owner-resume-plan.v1', 'scenario_id': 'V6', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'OWN-A13', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_scope': deepcopy(step['expected_scope']),
        'expected_retained_obligation_refs': deepcopy(step['expected_retained_obligation_refs']),
        'expected_readiness_refs': deepcopy(step['expected_readiness_refs']),
        'source_continuing_duty_refs': deepcopy(step['expected_continuing_duty_refs']),
        'source_held_resource_refs': deepcopy(step['expected_held_resource_refs']),
        'limitations': ['Isolated synthetic resume proposal; duties and held resources remain original input sources.',
            'No actual closeout feedback, native transition, release, permit issuance, payment or complete V6 chain proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-owner-resume-attempt.v1', 'status': 'started',
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
            'role': 'Owner', 'action_id': 'OWN-A13', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'OWN-A13'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'owner_continuation_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'resume'
                or result['payload']['scope'] != step['expected_scope']
                or result['payload']['retained_obligation_refs'] != step['expected_retained_obligation_refs']
                or result['payload']['readiness_refs'] != step['expected_readiness_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V6 Owner resume did not preserve its exact proposal, readiness and original debt without transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V6 original Owner resume input changed during evaluation')
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
    print(run_v6_owner_resume_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
