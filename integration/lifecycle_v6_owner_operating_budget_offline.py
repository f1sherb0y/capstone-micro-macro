"""Plan or explicitly evaluate one synthetic V6 future research-budget proposal."""
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
from src.actions.contracts.owner_operating_objects import (
    OwnerOperatingPortfolioView, OwnerOperatingProfileView, OwnerResearchBudgetView, owner_operating_schemas,
)
from src.coordination.tasks import task_digest
from src.methods.pricing import decimal_fraction


_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_SOURCES = 'integration.owner_role_contract_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V6'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V6 Owner budget requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = OwnerRoleContractSettings.model_validate(configuration.settings)
    source = OwnerFixtureSourceSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'OWN-A15' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'revise_research_budget'
            or context.contract_ref.id != 'OWN-A15' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'OWN-A15'
            or settings.source_factory != _SOURCES or settings.source_version != 'configured-owner-fixture-sources.v1'
            or source.action_id != 'OWN-A15' or source.allow_saved_recovery
            or any(value is not None for name, value in settings.model_dump().items() if name.endswith('_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V6 Owner budget changes original offline action, factory, run or snapshot')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if (len(originals) != len(rows) or len(set(identities)) != len(identities)
            or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]):
        raise ValueError('V6 Owner budget aliases original organizations or visible source identities')
    schemas = owner_operating_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V6 offline Owner budget evidence must declare its synthetic origin')
    inputs = request.action_input
    portfolio = OwnerOperatingPortfolioView.model_validate(originals[Reference.model_validate(inputs['portfolio_ref']).key()])
    profile = OwnerOperatingProfileView.model_validate(originals[Reference.model_validate(inputs['operating_profile_ref']).key()])
    if (profile.choice != 'revise_research_budget' or profile.portfolio_ref != portfolio.ref
            or inputs['organization_ref']['id'] != projection['organization_id']
            or profile.organization_id != projection['organization_id'] or portfolio.organization_id != profile.organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope or portfolio.scope != context.scope
            or portfolio.coverage != 'complete' or portfolio.as_of != context.business_time
            or profile.budget_authority_ref is None or profile.proposed_limit is None
            or profile.proposed_limit.model_dump(mode='json') != step['expected_proposed_limit']
            or [value.model_dump(mode='json') for value in profile.basis_refs] != step['expected_basis_refs']
            or inputs['learning_method_ref'] is not None or profile.preference_profile_ref is not None
            or profile.allocations or profile.allocation_task_refs or profile.replaced_commitment_refs
            or profile.allocation_revision_ref is not None):
        raise ValueError('V6 Owner budget changes its original portfolio, private proposal or learning/allocation selection')
    for field in ('obligation_refs', 'observation_refs'):
        references = [Reference.model_validate(value) for value in inputs[field]]
        if len(set(references)) != len(references) or set(references) != set(getattr(portfolio, field)):
            raise ValueError('V6 Owner budget omits original whole-organization sources: ' + field)
    if (not portfolio.obligation_refs or not set(profile.basis_refs) <= set(portfolio.observation_refs)
            or [value.model_dump(mode='json') for value in portfolio.obligation_refs] != step['expected_retained_obligation_refs']):
        raise ValueError('V6 Owner budget substitutes its private basis or drops original unpaid obligations')
    budget = OwnerResearchBudgetView.model_validate(originals[profile.budget_authority_ref.key()])
    amounts = (profile.proposed_limit, budget.maximum_limit, budget.actual_spent, budget.reserved)
    values = [decimal_fraction(amount.value) for amount in amounts]
    if (budget.organization_id != portfolio.organization_id or budget.author_organization_id != portfolio.organization_id
            or budget.as_of != context.business_time or budget.coverage != 'complete'
            or budget.permitted.model_dump() != {'state': 'known', 'value': True}
            or any(amount.currency != budget.currency for amount in amounts) or any(value < 0 for value in values)
            or not values[2] + values[3] <= values[0] <= values[1]):
        raise ValueError('V6 Owner budget changes original current authority or spent/reserved research boundaries')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v6_owner_operating_budget_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 Owner budget execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V6 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-owner-operating-budget-plan.v1', 'scenario_id': 'V6', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'OWN-A15', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_proposed_limit': deepcopy(step['expected_proposed_limit']),
        'expected_basis_refs': deepcopy(step['expected_basis_refs']),
        'source_retained_obligation_refs': deepcopy(step['expected_retained_obligation_refs']),
        'limitations': ['Isolated synthetic future research-budget proposal; original obligations remain input sources.',
            'No native budget/cash mutation, debt discharge, verified learning or complete V6 feedback cycle proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-owner-operating-budget-attempt.v1', 'status': 'started',
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
            'role': 'Owner', 'action_id': 'OWN-A15', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'OWN-A15'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'owner_operating_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'revise_research_budget'
                or result['payload']['proposed_limit'] != step['expected_proposed_limit']
                or result['payload']['basis_refs'] != step['expected_basis_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V6 Owner budget did not preserve its exact future-budget limit and private basis without transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V6 original Owner budget input changed during evaluation')
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
    print(run_v6_owner_operating_budget_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
