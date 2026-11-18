"""Isolated, no-replay CP07 runner with per-invocation token limits."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from capstone_cp_common_20261112 import ROOT, CP01, no_provider, read, save, sha, verify_input_protocol
from continue_capstone_cp01_20261112 import assert_transport_open, process_ancestors
from prepare_capstone_cp07_20261113 import OUT, stages, messages_for

BASE = ROOT / 'Capstone报告/验证体系'
MASTER = BASE / '实验/2026-11-13_总实验收尾'
PREVIOUS = BASE / '实验/2026-11-13_CP08全量微观扩样'
GOAL = BASE / '2026-11-13_GOAL_Capstone剩余实验与结果收尾.md'


def identity(job):
    return f"{job['window_id']}-{job['arm']}-r{job['repeat']}"


def verify_frozen():
    p = verify_input_protocol(OUT)
    assert len(p['jobs']) == p['final_answers'] == 288
    assert sum(j['calls'] for j in p['jobs']) == p['max_calls'] == 864
    assert p['calls_per_arm'] == {'S': 1, 'D3': 4, 'S4': 4} and p['max_repairs'] == 0
    for name, digest in p['supplementary_sha256'].items():
        assert sha(OUT / name) == digest, 'CP07 frozen evaluation/prompt artifact changed: ' + name
    return p


def check_master():
    auth = read(MASTER / 'authorization.json')
    assert sha(GOAL) == auth['goal_sha256'] and auth['new_attempt_cap'] == 3488
    assert not (MASTER / 'PAID_HALT.json').exists(), 'Global paid stop is active'
    previous = read(PREVIOUS / 'run/execution_status.json')
    assert not previous['provider_halt'] and not previous['stop_records']
    assert previous['all_first_slots_accounted']
    assert previous['calls']['charged_or_reserved_calls'] == 928
    assert next(b for b in auth['budgets'] if b['batch'] == 'CP07')['remaining_max'] == 864


def paid_stop(reason, **details):
    if not (MASTER / 'PAID_HALT.json').exists():
        save(MASTER / 'PAID_HALT.json', {'batch': 'CP07', 'reason': reason, **details})


def invocation_kwargs(client, cap):
    assert type(cap) is int and cap in {800, 4096}
    # Override the actual request key; never mutate shared ChatOpenAI.max_tokens
    # while two jobs can be active at different stages.
    return {**client._invoke_kwargs(.2), 'max_completion_tokens': cap}


async def invoke(client, messages, cap):
    reply = await client._chat_model.ainvoke(client._lc_messages(messages), **invocation_kwargs(client, cap))
    return client._response(reply)


def public_comment(raw):
    from src.llm_client import extract_json_object
    value = extract_json_object(raw)
    if not isinstance(value, dict) or set(value) != {'comment'} or not isinstance(value['comment'], str) or not value['comment'].strip():
        raise ValueError('Intermediate process requires exactly one public nonempty comment string')
    return value['comment']


async def perform_job(client, budget, logger, job, window, halt, *, invoke_fn=invoke):
    folder = OUT / 'run/jobs' / identity(job)
    if folder.exists():
        halt.set()
        paid_stop('existing_job_no_replay', job=job)
        raise RuntimeError('CP07 job already exists; no replay')
    if halt.is_set():
        return {'job': job, 'state': 'not_started_provider_halt', 'calls': 0}
    assert_transport_open(client)
    reservation = identity(job)
    if not budget.reserve(reservation, job['calls']):
        halt.set()
        paid_stop('budget_reservation_refused', job=job)
        return {'job': job, 'state': 'not_started_budget_exhausted', 'calls': 0}
    history, results = [], []
    step_numbers = [4] if job['arm'] == 'S' else [1, 2, 3, 4]
    try:
        for step in step_numbers:
            if halt.is_set():
                break
            assert_transport_open(client)
            cap = 4096 if step == 4 else 800
            messages = messages_for(window, job['arm'], step, history)
            save(folder / f'request-step-{step}.json', {'messages': messages,
                'temperature': .2, 'max_completion_tokens': cap, 'job': job, 'step': step})
            budget.begin_attempt(reservation)
            call_id, started = logger.begin(reservation + f':step{step}', messages, .2)
            result = {'job': job, 'step': step, 'call_id': call_id, 'max_output_tokens': cap}
            try:
                response = await invoke_fn(client, messages, cap)
            except Exception as exc:
                status = getattr(exc, 'status_code', None)
                result.update(status='provider_unknown_attempt' if status is None else 'provider_failed',
                              error_type=type(exc).__name__, http_status=status)
                logger.failed(call_id, started, RuntimeError(f'Provider failure {type(exc).__name__}; HTTP={status}'))
                halt.set()
                paid_stop(result['status'], job=job, step=step, error_type=type(exc).__name__, http_status=status)
            else:
                logger.succeeded(call_id, started, response.content, response.metadata)
                result.update(raw_content=response.content, metadata=response.metadata)
                try:
                    if step == 4:
                        from run_capstone_v2_5_20261109 import evaluate
                        result.update(evaluate(response.content, window, 'v2_5'))
                    else:
                        comment = public_comment(response.content)
                        position = stages(job['arm'], window['role'])[step - 1]['position']
                        history.append({'step': step, 'position': position, 'comment': comment})
                        result.update(status='process_comment_retained_not_quality_scored', public_comment=comment, position=position)
                except Exception as exc:
                    result.update(status='local_process_or_evaluation_error', error_type=type(exc).__name__)
                    halt.set()
                    paid_stop(result['status'], job=job, step=step, error_type=type(exc).__name__)
            result['seconds'] = time.perf_counter() - started
            save(folder / f'step-{step}.json', result)
            results.append(result)
            save(OUT / 'run/budget_usage.json', budget.usage())
            if halt.is_set():
                break
    except Exception as exc:
        halt.set()
        paid_stop('local_job_exception', job=job, error_type=type(exc).__name__)
        raise
    finally:
        budget.finish(reservation)
    final = next((r for r in results if r['step'] == 4), None)
    row = {'job': job, 'state': 'final_response_retained_scoring_pending' if final and 'raw_content' in final else 'halted_without_readable_final',
           'calls': len(results), 'final_step_status': final['status'] if final else None,
           'process_comments': len(history), 'scoring': 'pending_explicit_content_review'}
    save(folder / 'job_status.json', row)
    return row


def preflight():
    p = verify_frozen()
    windows = read(OUT / 'windows.json')
    with no_provider() as counts:
        for window in windows.values():
            for arm in ['S', 'D3', 'S4']:
                msgs = messages_for(window, arm, 4, [])
                assert msgs[:-1] == window['messages']['v2_5']
            for arm in ['D3', 'S4']:
                assert len(stages(arm, window['role'])) == 3
                for step in [1, 2, 3]:
                    msg = messages_for(window, arm, step, [{'step': 0, 'comment': 'Synthetic, not model output.'}])
                    assert msg[:2] == window['messages']['v2_5']
        from src.llm_client import OpenAICompatibleClient, LLMConfig
        # Dummy credentials, no from_env and no network: inspect the exact SDK
        # payload for conflicting/default token caps before any real call.
        client = OpenAICompatibleClient(LLMConfig('deepseek', p['model'], 'https://cp07-preflight.invalid/v1', 'synthetic-not-a-key'))
        try:
            client._chat_model.max_tokens = 4096
            for cap in [800, 4096]:
                payload = client._chat_model._get_request_payload(
                    client._lc_messages([{'role': 'user', 'content': 'Synthetic interface probe, no request.'}]),
                    **invocation_kwargs(client, cap))
                assert payload['max_completion_tokens'] == cap
                assert 'max_tokens' not in payload and payload['response_format'] == {'type': 'json_object'}
                assert payload['extra_body'] == {'thinking': {'type': 'disabled'}}
            assert client.request_policy()['internal_retries'] == 0
        finally:
            client._chat_model.root_client.close()
    asyncio.run(client._chat_model.root_async_client.close())
    save(OUT / 'preflight.json', {'passed': True, 'same_original_facts_and_final_requirements': True,
        'all_windows_checked': len(windows), 'distinct_role_position_sets': 4,
        'per_invocation_token_payloads_checked': [800, 4096], 'shared_client_cap_mutation': False,
        'planned_calls': p['max_calls'], 'actual_model_calls': 0, **counts})
    print('CP07 preflight PASS: 96 windows, four role position sets, actual SDK payload caps 800/4096; 0 calls')


def launch(cap):
    if type(cap) is not int or cap != 864:
        raise ValueError('CP07 requires exact independent cap864')
    p = verify_frozen()
    check_master()
    assert read(OUT / 'preflight.json')['passed']
    if (OUT / 'run').exists() or (OUT / 'authorization.json').exists():
        raise ValueError('Existing CP07 attempt; do not replay')
    token = uuid.uuid4().hex
    save(OUT / 'authorization.json', {'at_UTC': datetime.now(timezone.utc).isoformat(), 'max_calls': cap,
         'master_authorization_sha256': sha(MASTER / 'authorization.json'), 'source': 'Explicitly activated master GOAL',
         'launcher_pid': os.getpid(), 'token': token, 'runner_sha256': sha(Path(__file__)),
         'protocol_sha256': sha(OUT / 'protocol.json')})
    done = subprocess.run([sys.executable, str(Path(__file__)), 'worker', '--token', token], cwd=ROOT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if done.returncode:
        paid_stop('worker_nonzero_exit', exit_code=done.returncode)
        raise RuntimeError('CP07 child stopped; inspect without restarting')


def worker(token):
    auth = read(OUT / 'authorization.json')
    assert token and token == auth['token']
    assert os.getpid() != auth['launcher_pid'] and auth['launcher_pid'] in process_ancestors()
    assert sha(Path(__file__)) == auth['runner_sha256'] and sha(OUT / 'protocol.json') == auth['protocol_sha256']
    check_master()
    p = verify_frozen()
    assert not (OUT / 'run').exists()
    from src.llm_client import OpenAICompatibleClient
    from src.coordination.tasks import TaskStore
    from src.coordination.model_budget import ModelCallBudget
    from src.run_audit import LLMCallAuditLogger
    client, store = None, None
    try:
        client = OpenAICompatibleClient.from_env(model=p['model'])
        assert_transport_open(client)
        assert client.request_policy() == read(CP01 / 'authorization.json')['transport']
        client._chat_model.max_tokens = 4096
        store = TaskStore(run_id=p['run_id'], organization_ids=['experiment-host'], path=OUT / 'run/budget.sqlite')
        budget = ModelCallBudget(store=store, budget_id=p['budget_id'], max_calls=864)
        logger = LLMCallAuditLogger(OUT / 'run', 'CP07', client)
        async def perform():
            halt = asyncio.Event()
            semaphore = asyncio.Semaphore(p['concurrency'])
            windows = read(OUT / 'windows.json')
            async def job_run(job):
                async with semaphore:
                    return await perform_job(client, budget, logger, job, windows[job['window_id']], halt)
            try:
                results = await asyncio.gather(*(job_run(j) for j in p['jobs']))
                save(OUT / 'run/results_all_slots.json', results)
                save(OUT / 'run/execution_status.json', {'provider_halt': halt.is_set(),
                    'all_final_slots_accounted': len(results) == 288,
                    'calls': budget.usage(), 'stop_records': read(MASTER / 'PAID_HALT.json') if halt.is_set() else [],
                    'scoring': 'pending_explicit_content_review'})
            finally:
                save(OUT / 'run/budget_usage.json', budget.usage())
                await client._chat_model.root_async_client.close()
        asyncio.run(perform())
    except Exception as exc:
        paid_stop('local_worker_exception', error_type=type(exc).__name__)
        raise
    finally:
        if store:
            store.close()
        if client:
            client._chat_model.root_client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['preflight', 'run', 'worker'])
    parser.add_argument('--authorize-max-calls', type=int)
    parser.add_argument('--token')
    args = parser.parse_args()
    if args.command == 'preflight':
        preflight()
    elif args.command == 'run':
        launch(args.authorize_max_calls)
    else:
        worker(args.token)
