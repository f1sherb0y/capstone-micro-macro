"""Bounded real-model entry for frozen V2.2 tasks; preflight is zero-provider.

Uses existing transport, durable budget, JSON parsing and audit modules. Does not
execute tender submission, construct external receipts or automatically resume.
"""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_capstone_v2_2_robustness_20261108 import OUT, REPAIR, baseline_module, read, save, sha
from src.coordination.tasks import TaskStore
from src.coordination.model_budget import ModelCallBudget
from src.run_audit import LLMCallAuditLogger, utc_now
from src.llm_client import OpenAICompatibleClient, extract_json_object, InvalidJSONResponseError
from src.prompt_contracts import require_management_decision, require_bid_document_shape
from src.verification import require_condition_disposition

BASELINE = baseline_module()


def verify_frozen():
    p = read(OUT / 'protocol.json')
    for name, key in [('windows.json', 'windows_sha256'), ('targets.json', 'targets_sha256'),
                      ('sample_manifest.json', 'manifest_sha256')]:
        if sha(OUT / name) != p[key]:
            raise ValueError('Frozen input mismatch: ' + name)
    for name, digest in p['code_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('Frozen code mismatch: ' + name)
    if sha(REPAIR / 'baseline/src/verification.py') != p['baseline_verification_sha256']:
        raise ValueError('Baseline mismatch')
    return p


def identity(job):
    return f"{job['window_id']}-{job['arm']}-r{job['repeat']}"


def evaluate(raw, window, arm):
    result = {'raw_content': raw, 'status': 'invalid_json'}
    try:
        data = extract_json_object(raw)
        if not isinstance(data, dict):
            raise ValueError('Expected one JSON object')
        result['parsed'] = data
        if window['marker'] == 'BID_DOCUMENT':
            require_bid_document_shape(data)
        else:
            require_management_decision(data)
        validator = BASELINE.require_condition_disposition if arm == 'v2_1' else require_condition_disposition
        validator(data, window['conditions'], submission=False)
        result['status'] = 'accepted'
    except (ValueError, TypeError, KeyError, InvalidJSONResponseError) as exc:
        result['status'] = 'validation_failed' if 'parsed' in result else 'invalid_json'
        result['error'] = f'{type(exc).__name__}: {exc}'
    return result


async def request(client, budget, logger, job, window, number, halt):
    folder = OUT / 'run/jobs' / identity(job)
    path = folder / f'attempt-{number}.json'
    if path.exists():
        raise RuntimeError('Refuse to replay attempted request')
    if halt.is_set():
        return {'job': job, 'status': 'not_started_provider_halt'}
    slot = identity(job) + ':' + str(number)
    if not budget.reserve(slot, 1):
        return {'job': job, 'status': 'not_started_budget_exhausted'}
    messages = deepcopy(window['messages'][job['arm']])
    if number > 1:
        previous = read(folder / 'attempt-1.json')
        messages.append({'role': 'user', 'content': 'JSON_OR_CONTRACT_REPAIR_REQUIRED\n' + previous.get('error', '')
                         + '\nReturn the complete original answer as one valid JSON object. No facts or sources have changed.'})
    save(folder / f'request-{number}.json', {'messages': messages, 'temperature': .2, 'max_output_tokens': 4096})
    budget.begin_attempt(slot)
    call_id, started = logger.begin(slot, messages, .2)
    try:
        response = await client.achat_with_metadata(messages, temperature=.2)
        logger.succeeded(call_id, started, response.content, response.metadata)
        result = evaluate(response.content, window, job['arm'])
        if 'parsed' in result:
            logger.parsed(call_id, result['parsed'])
            if result['status'] == 'accepted':
                logger.contract_validated(call_id)
            else:
                logger.contract_failed(call_id, ValueError(result['error']))
        else:
            logger.parse_failed(call_id, ValueError(result['error']))
        result['metadata'] = response.metadata
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        result = {'status': 'provider_failed', 'error_type': type(exc).__name__, 'http_status': status}
        logger.failed(call_id, started, RuntimeError(f'Provider failure {type(exc).__name__}; HTTP={status}'))
        if status in {401, 402, 403}:
            halt.set()
    finally:
        budget.finish(slot)
    result.update(job=job, attempt=number, call_id=call_id, seconds=time.perf_counter()-started)
    save(path, result)
    save(OUT / 'run/budget_usage.json', budget.usage())
    print(identity(job), number, result['status'], flush=True)
    return result


async def perform(client, budget, logger, protocol, windows):
    semaphore = asyncio.Semaphore(protocol['concurrency'])
    halt = asyncio.Event()
    async def first(job):
        async with semaphore:
            return await request(client, budget, logger, job, windows[job['window_id']], 1, halt)
    results = await asyncio.gather(*(first(j) for j in protocol['jobs']))
    save(OUT / 'run/first_results.json', results)
    retry_candidates = [r for r in results if r['status'] in {'invalid_json', 'validation_failed'}]
    for row in retry_candidates[:protocol['max_final_retries']]:
        job = row['job']
        await request(client, budget, logger, job, windows[job['window_id']], 2, halt)
    save(OUT / 'run/execution_status.json', {
        'all_first_slots_accounted': len(results) == 64, 'provider_halt': halt.is_set(),
        'calls': budget.usage(), 'quality_review': 'pending; contract acceptance is not quality',
        'macro_execution': False})


def run(authorized_cap):
    # The old240 authorization covered two completed batches, not this one.
    if type(authorized_cap) is not int or authorized_cap != 80:
        raise ValueError('This new frozen batch needs an explicit independent cap of80, including16 retries')
    protocol = verify_frozen()
    if (OUT / 'run').exists():
        raise RuntimeError('Existing or unknown attempt; no automatic resume/replay')
    client = OpenAICompatibleClient.from_env(model=protocol['model'])
    policy = client.request_policy()
    if policy['provider'] != 'deepseek' or policy['internal_retries'] != 0:
        raise ValueError('Unexpected transport or hidden retries')
    client._chat_model.max_tokens = protocol['max_output_tokens']
    params = client._chat_model._default_params
    if params.get('max_tokens', params.get('max_completion_tokens')) != 4096:
        raise ValueError('Output cap not bound')
    save(OUT / 'authorization.json', {'at': utc_now(), 'max_calls': authorized_cap,
        'scope': 'New explicit authorization only; no inherited46, paid judge or macro action',
        'protocol_sha256': sha(OUT / 'protocol.json'), 'transport': policy})
    store = TaskStore(run_id='capstone-v22-robustness', organization_ids=['experiment-host'], path=OUT / 'run/budget.sqlite')
    budget = ModelCallBudget(store=store, budget_id='new-explicit-cap80', max_calls=80)
    logger = LLMCallAuditLogger(OUT / 'run', 'CAPSTONE-V22', client)
    async def main():
        try:
            await perform(client, budget, logger, protocol, read(OUT / 'windows.json'))
        finally:
            save(OUT / 'run/budget_usage.json', budget.usage())
            await client._chat_model.root_async_client.close()
    try:
        asyncio.run(main())
    finally:
        store.close()
        client._chat_model.root_client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-max-calls', type=int)
    args = parser.parse_args()
    run(args.authorize_max_calls)
