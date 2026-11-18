"""Actual native A02 option/processor gates; synthetic clients only."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from integration.capstone_mechanism_controls import RuleOriginalOptionStrategy, SameRoleRevisionStrategy
from tests.test_tender_model_options import build_case


class RevisionFixtureClient:
    def __init__(self, fail_at=None, invalid_final=False):
        self.calls = []
        self.fail_at, self.invalid_final = fail_at, invalid_final

    def request_policy(self):
        return {'schema_version': 'model-request-policy.v1', 'max_requests_per_call': 1,
                'internal_retries': 0, 'provider': 'synthetic', 'model': 'synthetic-selection'}

    def chat_with_metadata(self, messages, *, temperature):
        self.calls.append(deepcopy(messages))
        if len(self.calls) == self.fail_at:
            raise ConnectionError('Synthetic unknown request')
        tag, text = messages[-1]['content'].split('\n', 1)
        request = json.loads(text)
        selected = request['options'][1]['option_id']
        value = {'option_id': 'not-a-legal-option' if self.invalid_final and tag.endswith('FINAL') else selected}
        if tag.endswith('REVIEW'):
            value['reason'] = 'Synthetic same-role review, no new business facts.'
        return SimpleNamespace(content=json.dumps(value), metadata={'usage_metadata': {'total_tokens': 15}})


def prepare(tmp_path, cls, client):
    import integration.action_model_host as host_module
    import tests.test_tender_model_options as fixture_module
    with patch.object(host_module, 'SingleAgentActionStrategy', cls), \
         patch.object(fixture_module, 'SyntheticSelectionClient', lambda: client):
        store, _, host, prepared = build_case(tmp_path, 'single_agent')
    prepared.runner.prepare_decision(context=prepared.context, action_input=prepared.action_input,
                                     reading=prepared.reading)
    return store, client, host, prepared


def test_s4_uses_four_charged_calls_and_original_priced_result(tmp_path):
    client = RevisionFixtureClient()
    store, _, host, prepared = prepare(tmp_path, SameRoleRevisionStrategy, client)
    try:
        original = prepared.action_input.model_dump(mode='json')
        result = prepared.execute()
        assert result.kind == 'completed' and result.payload.bid.price.value == '37'
        assert len(client.calls) == 4
        assert prepared.action_input.model_dump(mode='json') == original
        assert host.budget.usage()['charged_or_reserved_calls'] == 4
        assert host.evidence()['bindings'][0]['component_id'] == SameRoleRevisionStrategy.COMPONENT
        requests = [json.loads(m[-1]['content'].split('\n', 1)[1]) for m in client.calls]
        assert [r['revision_step'] for r in requests] == list(SameRoleRevisionStrategy.STEPS)
        assert [len(r['own_previous_revisions']) for r in requests] == [0, 1, 2, 3]
        assert all('member' not in r for r in requests)
    finally:
        store.close()


@pytest.mark.parametrize('fail_at,invalid_final,charged', [(2, False, 2), (None, True, 4)])
def test_s4_failure_preserves_attempts_no_fallback_or_retry(tmp_path, fail_at, invalid_final, charged):
    client = RevisionFixtureClient(fail_at=fail_at, invalid_final=invalid_final)
    store, _, host, prepared = prepare(tmp_path, SameRoleRevisionStrategy, client)
    try:
        result = prepared.execute()
        assert result.kind == 'technical_error'
        assert len(client.calls) == charged
        assert host.budget.usage()['charged_or_reserved_calls'] == charged
    finally:
        store.close()


def test_s4_rejects_insufficient_call_budget_before_first_request(tmp_path):
    client = RevisionFixtureClient()
    store, _, host, prepared = prepare(tmp_path, SameRoleRevisionStrategy, client)
    try:
        assert host.budget.reserve('other-unrelated-budget-reservation', 5)
        result = prepared.execute()
        assert result.kind == 'unsupported'
        assert client.calls == []
    finally:
        store.close()


def test_rule_prices_same_options_without_request(tmp_path):
    client = RevisionFixtureClient()
    store, _, host, prepared = prepare(tmp_path, RuleOriginalOptionStrategy, client)
    try:
        result = prepared.execute()
        assert result.kind == 'completed'
        assert client.calls == [] and host.budget.usage()['charged_or_reserved_calls'] == 0
        record = prepared.runner.audit_records[-1].decision_evidence['execution']
        assert record['selected_option_id'] == 'original-input' and record['option_count'] == 2
    finally:
        store.close()


def test_explicit_s4_factory_preserves_native_host_binding(tmp_path):
    import tests.test_tender_model_options as fixture_module
    from integration.capstone_mechanism_controls import build_model_host
    client = RevisionFixtureClient()

    def factory(*, settings, **kwargs):
        return build_model_host(settings={**settings, 'research_control_arm': 'S4'}, **kwargs)

    with patch.object(fixture_module, 'build_model_host', factory), \
         patch.object(fixture_module, 'SyntheticSelectionClient', lambda: client):
        store, _, host, prepared = build_case(tmp_path, 'single_agent')
    try:
        prepared.runner.prepare_decision(context=prepared.context, action_input=prepared.action_input, reading=prepared.reading)
        assert prepared.execute().kind == 'completed'
        assert len(client.calls) == 4
        assert all(isinstance(c, SameRoleRevisionStrategy) for c in host.components)
        host.evidence()  # Original immutable host checks remain enabled.
    finally:
        store.close()
