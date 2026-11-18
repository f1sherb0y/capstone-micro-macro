"""Zero-provider preflight; reference/schema probes are not business answers."""
from copy import deepcopy
import asyncio
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_capstone_v2_3_20261109 import OUT, GROUPS, read, save, sha
from run_capstone_v2_3_20261109 import verify_frozen, evaluate, run
from src.company_grounding import company_evidence
from src.coordination.tasks import TaskStore
from src.coordination.model_budget import ModelCallBudget
from run_capstone_core_validation_20261108 import NoProviderNetwork
from tests.test_bid_document_stage import BidLLM


def main():
    protocol = verify_frozen()
    windows, manifest = read(OUT / 'windows.json'), read(OUT / 'sample_manifest.json')
    fixture_bid = json.loads(asyncio.run(BidLLM().achat([{}, {'content': 'BID_DOCUMENT'}])))
    guard, constructors = NoProviderNetwork(), []
    def deny(*args, **kwargs):
        constructors.append(True)
        raise AssertionError('Preflight must not construct a paid client')
    rows = []
    with patch.object(socket.socket, 'connect', guard.block), patch.object(socket.socket, 'connect_ex', guard.block), \
         patch('src.llm_client.OpenAICompatibleClient.from_env', side_effect=deny):
        for cap in (None, 0, 13, 80):
            try:
                run(cap)
            except ValueError:
                pass
            else:
                raise AssertionError('Old/missing authorization was accepted')
        for wid, w in windows.items():
            left, right = w['messages']['v2_2'], w['messages']['v2_3']
            assert left[0] == right[0]
            assert left[-1]['content'].split('Evidence and decision conditions:')[0] == right[-1]['content'].split('Evidence and decision conditions:')[0]
            for messages in (left, right):
                records, _ = json.JSONDecoder().raw_decode(messages[-1]['content'].rsplit('Complete condition register (not truncated):\n', 1)[1])
                assert records == w['conditions']
            projection, _ = json.JSONDecoder().raw_decode(right[-1]['content'].split('Company evidence projection (host, not model-invented facts):\n', 1)[1])
            assert projection == w['company_evidence'] == company_evidence(w['facts']['real_input_dossier']['company'])
            data = deepcopy(fixture_bid) if w['marker'] == 'BID_DOCUMENT' else {
                'thoughts': '', 'decision': 'bid', 'reason': 'Synthetic interface probe.', 'content': 'Proposed work only.'}
            data.update(unresolved_condition_ids=[r['condition_id'] for r in w['conditions']], verified_condition_ids=[],
                        bid_assumptions=['Synthetic probe, not a model answer.'])
            baseline = evaluate(json.dumps(data), w, 'v2_2')
            assert baseline['status'] == 'accepted'
            # This directly tests only reference/status wiring. It is explicitly
            # not the task's correct business answer, nor a generated decision.
            assessment = {'company_id': projection['company_id'], 'projection_sha256': projection['projection_sha256'], 'topics': {}}
            for topic, spec in projection['topics'].items():
                ref = spec['allowed_source_refs'][0] if spec['allowed_source_refs'] else None
                assessment['topics'][topic] = {'status': spec['status'], 'source_ref': ref,
                                              'quote': projection['sources'][ref]['text'] if ref else ''}
            data['company_assessment'] = assessment
            current = evaluate(json.dumps(data), w, 'v2_3')
            assert current['status'] == 'accepted'
            rows.append({'window_id': wid, 'same_facts': True, 'baseline_probe': baseline['status'],
                         'current_probe': current['status'], 'reference_statuses': projection['topics'], 'provider_requests': 0})
        for index in range(1, 5):
            full, missing = [windows[f'SOURCE-{index:02d}-{v}'] for v in ('full', 'missing_core')]
            assert full['conditions'] == missing['conditions']
            assert full['facts']['real_input_dossier']['project'] == missing['facts']['real_input_dossier']['project']
            removed = {'business_scope', 'industry', 'certifications', 'staff_scale', 'talent_structure'}
            assert all(missing['facts']['real_input_dossier']['company'][k] == ('' if k in removed else value)
                       for k, value in full['facts']['real_input_dossier']['company'].items())
            assert missing['company_evidence']['topics']['scope']['status'] == 'unknown'
            assert all(missing['company_evidence']['topics'][t]['status'] == 'unknown' for t in
                       ('experience', 'product_range', 'delivery_assets', 'historical_cost_basis'))
        with tempfile.TemporaryDirectory(prefix='source-binding-preflight-') as tmp:
            store = TaskStore(run_id='offline-v23', organization_ids=['host'], path=Path(tmp) / 'budget.sqlite')
            try:
                budget = ModelCallBudget(store=store, budget_id='planning-only', max_calls=40)
                assert budget.reserve('first', 32) and budget.reserve('retry', 8)
                assert not budget.reserve('over', 1)
                budget.finish('first')
                budget.finish('retry')
                assert budget.usage()['charged_or_reserved_calls'] == 0
            finally:
                store.close()
    assert len(windows) == 8 and len(protocol['jobs']) == 32
    assert len({m['project_group'] for m in manifest}) == 4
    assert not {m['project_group'] for m in manifest} & set(protocol['excluded_process_groups'])
    assert sha(GROUPS) == protocol['group_file_sha256']
    assert all(sha(ROOT / f) == h for f, h in protocol['source_sha256'].items())
    assert not constructors and guard.attempts == 0 and not (OUT / 'run').exists()
    save(OUT / 'preflight.json', {'passed': True, 'source_groups': 4, 'controlled_tasks': 8, 'first_jobs': 32,
        'interface_probes': rows, 'budget_preflight_passed': True, 'group_overlap_with_prior_process_trials': 0,
        'company_overlap_with_previous4': sum(m['company_overlap_with_previous4'] for m in manifest),
        'provider_requests': 0, 'client_constructions': 0, 'network_attempts': 0,
        'authorized_cap_now': 0, 'proposed_independent_cap': 40,
        'status': 'prepared and frozen; real model confirmation pending independent authorization',
        'limits': 'Exact reference/status checks are not semantic entailment or proof of improved narrative grounding.'})
    print('PASS:4 source groups,8 tasks,32 first jobs,16 interface probes; independent cap40 proposed, actual calls0.')


if __name__ == '__main__':
    main()
