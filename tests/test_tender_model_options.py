"""Synthetic sources/model only; no native run, paid request or bid submission."""
from copy import deepcopy
from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from integration.contractor_bid_actions import ContractorBidActionAssembler
from integration.contractor_tender_model_options import build_model_host
from src.actions.contracts.common import ActionContext, Reference
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskStore, task_digest
from src.organization.models import Authorization, Organization
from src.organization.registry import OrganizationRegistry


class SyntheticSelectionClient:
    def __init__(self):
        self.calls = []

    def request_policy(self):
        return {'schema_version': 'model-request-policy.v1', 'max_requests_per_call': 1,
            'internal_retries': 0, 'provider': 'synthetic', 'model': 'synthetic-selection'}

    def chat_with_metadata(self, messages, *, temperature):
        assert temperature == 0
        self.calls.append(deepcopy(messages))
        tag, text = messages[-1]['content'].split('\n', 1)
        request = json.loads(text)
        result = {'option_id': request['options'][1]['option_id']}
        if tag == 'ACTION_DISCUSSION_REVIEW':
            result['reason'] = 'Synthetic reviewer chooses the second independently priced option.'
        return SimpleNamespace(content=json.dumps(result), metadata={'usage_metadata': {
            'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}})


def build_case(tmp_path, strategy, mutation=None):
    examples = Path(__file__).resolve().parents[1] / 'integration/examples'
    source = json.loads((examples / 'role_contract_contractor_bid_host.json').read_bytes())['settings']['source_settings']
    invocation = json.loads((examples / 'role_contract_contractor_bid_invocation.json').read_bytes())
    invocation['context']['execution_mode'] = 'llm'
    rows = source['source_projection']['objects']
    original = next(row['value'] for row in rows if row['ref']['kind'] == 'ContractorPricingProfile')
    alternative = deepcopy(original)
    alternative['ref']['id'] += '-explicit-alternative'
    alternative['markup_fraction'] = '0.1'
    candidates = next(row['value'] for row in rows if row['ref']['kind'] == 'CandidateSet')
    candidates['candidates'].append({'ref': alternative['ref'], 'permitted_choices': ['submit_bid']})
    if mutation == 'foreign':
        alternative['organization_id'] = 'different-contractor'
    elif mutation == 'permission':
        candidates['candidates'][-1]['permitted_choices'] = ['decline_bid']
    elif mutation == 'late':
        alternative['available_at']['offset'] = invocation['context']['business_time']['offset'] + 1
    rows.append({'ref': alternative['ref'], 'value': alternative})
    invocation['context']['visible_refs'].append(alternative['ref'])
    context = ActionContext.model_validate(invocation['context'])
    snapshot = source['organization_snapshot']
    for grant in snapshot['authorizations']:
        if grant['ref'] in invocation['context']['authorization_refs']:
            grant['readable_refs'].append(alternative['ref'])
            for row in rows:
                if row['ref'] == grant['ref']:
                    row['value'] = deepcopy(grant)
    organizations = OrganizationRegistry(context.run_id)
    for organization in snapshot['organizations']:
        organizations.register(Organization.model_validate(organization))
    for grant in snapshot['authorizations']:
        organizations.authorize(Authorization.model_validate(grant))
    for ref in snapshot.get('inactive_authorization_refs', []):
        organizations.revoke(Reference.model_validate(ref))
    registry = register_representative_processors(ActionRegistry())
    store = TaskStore(run_id=context.run_id, organization_ids=[source['source_projection']['organization_id']],
        path=tmp_path / 'journal.sqlite')
    client = SyntheticSelectionClient()
    model_version = 'tender-model:' + task_digest(client.request_policy())
    assembly = SimpleNamespace(client=SimpleNamespace(tasks=store, tender_model_client=client,
        versions={'model': model_version}, organization_roles={source['source_projection']['organization_id']: 'Contractor'}))
    try:
        host = build_model_host(assembly=assembly, registry=registry, organizations=organizations,
            store=store, read_guard=nullcontext, request=None,
            output_directory=tmp_path, settings={'namespace': 'synthetic-tender-options', 'strategy': strategy,
                'host': {'host_id': 'synthetic-host', 'budget_id': 'synthetic-budget', 'max_calls': 8,
                    'action_ids': ['CONTRACTOR-A01', 'CONTRACTOR-A02'], 'max_options': 2,
                    'max_prompt_chars': 300000, 'max_members': 3}})

        class Source:
            def project(self, **kwargs):
                return deepcopy(source['source_projection'])

        assembler = ContractorBidActionAssembler(registry=registry, organizations=organizations,
            provider=Source(), macro_version=source['source_projection']['macro_version'],
            source_mode='formal', policy_version='synthetic-policy', model_host=host)
        action_input = invocation['action_input']
        prepared = assembler.build(context, **{name: action_input[name] for name in
            ('pricing_profile_ref', 'capacity_ref', 'cost_refs', 'allowed_method_refs')})
        return store, client, host, prepared
    except Exception:
        store.close()
        raise


@pytest.mark.parametrize('strategy,calls', [('single_agent', 1), ('organization_discussion', 4)])
def test_original_bid_processor_prices_each_authorized_alternative_before_selection(tmp_path, strategy, calls):
    store, client, host, prepared = build_case(tmp_path, strategy)
    try:
        original = prepared.action_input.model_dump(mode='json')
        prepared.runner.prepare_decision(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading)
        assert not client.calls  # Local capture and current gates make no model request.
        result = prepared.execute()
        assert result.kind == 'completed' and result.payload.choice == 'submit_bid'
        assert result.payload.bid.price.value == '37'  # Quantity 6 * unit rate 5, markup 10%, allowance 4.
        assert len(client.calls) == calls
        assert prepared.action_input.model_dump(mode='json') == original
        execution = prepared.runner.audit_records[-1].decision_evidence['execution']
        assert execution['selected_option_id'].startswith('pricing-profile:')
        assert store._db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
        assert host.evidence()['call_budget']
    finally:
        store.close()


@pytest.mark.parametrize('mutation', ['foreign', 'permission', 'late'])
def test_tender_alternatives_refuse_wrong_organization_choice_or_time_before_model(tmp_path, mutation):
    store, client, _, prepared = build_case(tmp_path, 'single_agent', mutation)
    try:
        with pytest.raises(TaskConflict, match='Tender'):
            prepared.runner.prepare_decision(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading)
        assert not client.calls
    finally:
        store.close()


def test_explicit_run_model_preserves_environment_default_and_bounded_transport(monkeypatch):
    import os
    from src.llm_client import OpenAICompatibleClient
    from integration.model_tender_native import _close_transport
    monkeypatch.setenv('LLM_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'synthetic-not-a-real-api-key')
    monkeypatch.setenv('DEEPSEEK_MODEL', 'synthetic-old-model-name')
    client = OpenAICompatibleClient.from_env(model='deepseek-flash')
    try:
        policy = client.request_policy()
        assert policy['model'] == 'deepseek-flash' and policy['internal_retries'] == 0
        assert os.environ['DEEPSEEK_MODEL'] == 'synthetic-old-model-name'
        assert 'synthetic-not-a-real-api-key' not in json.dumps(policy)
    finally:
        _close_transport(client)
