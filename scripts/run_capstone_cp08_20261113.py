"""CP08 input verification and isolated bounded runner; no additional retries."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from capstone_cp_common_20261112 import ROOT, CP01, engine_binding, no_provider, read, save, sha, verify_input_protocol
from continue_capstone_cp01_20261112 import assert_transport_open, open_checked_request, process_ancestors

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-13_CP08全量微观扩样'
MASTER = BASE / '实验/2026-11-13_总实验收尾'
GOAL = BASE / '2026-11-13_GOAL_Capstone剩余实验与结果收尾.md'


def verify_frozen():
    p = verify_input_protocol(OUT)
    assert p['first_requests'] == len(p['jobs']) == p['max_calls_proposed'] <= 928
    assert p['max_final_retries'] == 0 and p['paid_ready']
    assert not read(OUT / 'input_leak_review.json')['exact_target_project_hits']
    return p


def check_master():
    auth = read(MASTER / 'authorization.json')
    assert sha(GOAL) == auth['goal_sha256'] and auth['new_attempt_cap'] == 3488
    assert not (MASTER / 'PAID_HALT.json').exists(), 'Master paid stop is active'
    previous = read(CP01 / 'continuation-001/run/execution_status.json')
    assert not previous['provider_halt'] and not previous['stop_records'], 'CP01 must finish without a new stop first'
    assert next(b for b in auth['budgets'] if b['batch'] == 'CP08')['remaining_max'] == 928


def preflight():
    p = verify_frozen()
    from run_capstone_v2_5_20261109 import evaluate
    from tests.test_bid_document_stage import BidLLM
    from src.company_grounding import company_evidence
    fixture = json.loads(asyncio.run(BidLLM().achat([{}, {'content': 'BID_DOCUMENT'}])))
    windows = read(OUT / 'windows.json')
    checks = 0
    with no_provider() as counts:
        for wid, w in windows.items():
            left, right = w['messages']['v2_4'], w['messages']['v2_5']
            assert left[0] == right[0]
            assert left[-1]['content'].split('Evidence and decision conditions:')[0] == right[-1]['content'].split('Evidence and decision conditions:')[0]
            projection = company_evidence(w['facts']['real_input_dossier']['company'])
            assert projection == w['company_evidence']
            data = deepcopy(fixture) if w['marker'] == 'BID_DOCUMENT' else {'thoughts': '', 'decision': 'bid', 'reason': 'Synthetic interface probe.', 'content': 'Proposed work only.'}
            data.update(unresolved_condition_ids=[c['condition_id'] for c in w['conditions']], verified_condition_ids=[],
                bid_assumptions=['Synthetic interface probe, not a model business-quality result.'])
            assessment = {'company_id': projection['company_id'], 'projection_sha256': projection['projection_sha256'], 'topics': {}}
            for topic, spec in projection['topics'].items():
                ref = spec['allowed_source_refs'][0] if spec['allowed_source_refs'] else None
                assessment['topics'][topic] = {'status': spec['status'], 'source_ref': ref,
                    'quote': projection['sources'][ref]['text'] if ref else ''}
            data['company_assessment'] = assessment
            for arm in ['v2_4', 'v2_5']:
                if arm == 'v2_5':
                    data['task_role'] = w['role']
                result = evaluate(json.dumps(data), w, arm)
                assert result['status'] == 'accepted', (wid, arm, result.get('error'))
                checks += 1
        for m in read(OUT / 'sample_manifest.json'):
            full = windows[m['base_unit'] + '-full']
            missing = windows[m['base_unit'] + '-missing_core']
            assert full['conditions'] == missing['conditions']
            assert full['facts']['real_input_dossier']['project'] == missing['facts']['real_input_dossier']['project']
            assert missing['company_evidence']['topics']['scope']['status'] == 'unknown'
        assert checks == len(p['jobs'])
    save(OUT / 'preflight.json', {'passed': True, 'synthetic_interface_probes': checks,
        'actual_model_quality_results': 0, 'groups': len(read(OUT / 'sample_manifest.json')),
        'first_requests': len(p['jobs']), 'max_repairs': 0, 'provider_calls': 0, **counts})
    print(json.dumps({'CP08_preflight': 'PASS', 'interface_probes': checks, 'model_calls': 0}))


def launch(cap):
    p = verify_frozen()
    if type(cap) is not int or cap != p['max_calls_proposed']:
        raise ValueError('Exact eligible CP08 cap must be explicit')
    check_master()
    assert read(OUT / 'preflight.json')['passed']
    if (OUT / 'run').exists() or (OUT / 'authorization.json').exists():
        raise ValueError('Existing CP08, never replay automatically')
    token = uuid.uuid4().hex
    save(OUT / 'authorization.json', {'at_UTC': datetime.now(timezone.utc).isoformat(), 'batch': 'CP08',
        'source': 'Explicitly activated master GOAL', 'max_calls': cap, 'max_repairs': 0,
        'launcher_pid': os.getpid(), 'token': token, 'runner_sha256': sha(Path(__file__)),
        'protocol_sha256': sha(OUT / 'protocol.json'), 'master_authorization_sha256': sha(MASTER / 'authorization.json')})
    result = subprocess.run([sys.executable, str(Path(__file__)), 'worker', '--token', token], cwd=ROOT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('CP08 worker stopped; inspect, never restart')


def worker(token):
    auth = read(OUT / 'authorization.json')
    assert token and token == auth['token']
    assert auth['launcher_pid'] in process_ancestors() and os.getpid() != auth['launcher_pid']
    assert sha(Path(__file__)) == auth['runner_sha256']
    assert sha(OUT / 'protocol.json') == auth['protocol_sha256']
    check_master()
    p = verify_frozen()
    assert not (OUT / 'run').exists()
    from src.coordination.tasks import TaskStore
    from src.coordination.model_budget import ModelCallBudget
    with engine_binding(OUT, verify_frozen) as engine:
        client = engine.OpenAICompatibleClient.from_env(model=p['model'])
        store = None
        failures = []
        try:
            assert_transport_open(client)
            assert client.request_policy() == read(CP01 / 'authorization.json')['transport']
            client._chat_model.max_tokens = p['max_output_tokens']
            assert client._chat_model._default_params.get('max_tokens', client._chat_model._default_params.get('max_completion_tokens')) == 4096
            store = TaskStore(run_id=p['run_id'], organization_ids=['experiment-host'], path=OUT / 'run/budget.sqlite')
            budget = ModelCallBudget(store=store, budget_id=p['budget_id'], max_calls=p['max_calls_proposed'])
            logger = engine.LLMCallAuditLogger(OUT / 'run', 'CP08', client)
            request = open_checked_request(engine.request, failures)
            async def perform():
                halt = asyncio.Event()
                semaphore = asyncio.Semaphore(p['concurrency'])
                windows = read(OUT / 'windows.json')
                async def first(job):
                    async with semaphore:
                        return await request(client, budget, logger, job, windows[job['window_id']], 1, halt)
                try:
                    results = await asyncio.gather(*(first(j) for j in p['jobs']))
                    save(OUT / 'run/first_results_all_slots.json', results)
                    save(OUT / 'run/execution_status.json', {'provider_halt': halt.is_set(), 'stop_records': failures,
                        'calls': budget.usage(), 'all_first_slots_accounted': len(results) == len(p['jobs']), 'scoring': 'pending'})
                    if halt.is_set():
                        save(MASTER / 'PAID_HALT.json', {'batch': 'CP08', 'reason': 'provider_or_local_execution_stop', 'stop_records': failures})
                finally:
                    save(OUT / 'run/budget_usage.json', budget.usage())
                    await client._chat_model.root_async_client.close()
            asyncio.run(perform())
        except Exception as exc:
            if not (MASTER / 'PAID_HALT.json').exists():
                save(MASTER / 'PAID_HALT.json', {'batch': 'CP08', 'reason': 'local_or_transport_exception', 'error_type': type(exc).__name__})
            raise
        finally:
            if store:
                store.close()
            client._chat_model.root_client.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['preflight', 'run', 'worker'])
    p.add_argument('--authorize-max-calls', type=int)
    p.add_argument('--token')
    a = p.parse_args()
    if a.command == 'preflight':
        preflight()
    elif a.command == 'run':
        launch(a.authorize_max_calls)
    else:
        worker(a.token)
