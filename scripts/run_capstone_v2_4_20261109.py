"""Bounded real-model entry for frozen V2.3 tasks; preflight is zero-provider.

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
from prepare_capstone_v2_4_20261109 import OUT, REPAIR, GROUPS, baseline_module, read, save, sha
from src.coordination.tasks import TaskStore
from src.coordination.model_budget import ModelCallBudget
from src.run_audit import LLMCallAuditLogger, utc_now
from src.llm_client import OpenAICompatibleClient, extract_json_object, InvalidJSONResponseError
from src.prompt_contracts import require_management_decision, require_bid_document_shape
from src.verification import require_condition_disposition
from src.company_grounding import require_company_assessment
from src.company_narrative import require_company_narrative, NarrativeIssue
from src.response_repair import issue_details, repair_messages, require_targeted_repair, RepairDriftError

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
    if sha(GROUPS)!=p['group_file_sha256'] or any(sha(ROOT/n)!=h for n,h in p['source_sha256'].items()):
        raise ValueError('Frozen source input or grouping mismatch')
    return p


def identity(job):
    return f"{job['window_id']}-{job['arm']}-r{job['repeat']}"


def evaluate(raw, window, arm, previous=None):
    result = {'raw_content': raw, 'status': 'invalid_json'}
    try:
        data = extract_json_object(raw)
        if not isinstance(data, dict):
            raise ValueError('Expected one JSON object')
        result['parsed'] = deepcopy(data)
        if arm == 'v2_4' and previous is not None:
            # No new provider call and no silent substitution for the first.
            error=ValueError(previous.get('error','Unspecified prior validation issue'))
            info=previous.get('issue',{})
            error.repair_details=info
            error.paths=info.get('paths',[])
            if 'findings' in info:
                error.report={'status':info.get('category','blocked'),'findings':info['findings']}
                error.category=info.get('category','blocked')
                error.retryable=info.get('retryable',True)
            result['repair_diff']=require_targeted_repair(previous['raw_content'],data,error)
        if window['marker'] == 'BID_DOCUMENT':
            require_bid_document_shape(data)
        else:
            require_management_decision(data)
        if arm == 'v2_3':
            BASELINE.require_company_assessment(data,window['company_evidence'])
            BASELINE.require_condition_disposition(data, window['conditions'], submission=False)
        else:
            require_company_assessment(data, window['company_evidence'])
            require_condition_disposition(data, window['conditions'], submission=False)
            result['narrative_review']=require_company_narrative(data,window['company_evidence'])
        result['status'] = 'accepted'
        result['content_quality']='pending_common_content_review; reference/limited guards are not semantic correctness'
    except (ValueError, TypeError, KeyError, InvalidJSONResponseError) as exc:
        needs_review=not getattr(exc,'retryable',True)
        result['status'] = 'content_review_required' if needs_review else 'validation_failed' if 'parsed' in result else 'invalid_json'
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['issue']=issue_details(exc)
        if hasattr(exc,'diff'):
            result['repair_diff']=exc.diff
        if hasattr(exc,'report'):
            result['narrative_review']=exc.report
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
        if job['arm']=='v2_4':
            error=ValueError(previous.get('error','Prior contract error'))
            info=previous.get('issue',{})
            error.repair_details=info
            if 'findings' in info:
                error.report={'status':info.get('category','blocked'),'findings':info['findings']}
                error.category=info.get('category','blocked')
                error.paths=info.get('paths',[])
                error.retryable=info.get('retryable',True)
            messages=repair_messages(messages,previous['raw_content'],error)
        else:
            # Frozen V2.3 retry behavior is the comparator, not silently fixed.
            messages.append({'role': 'user', 'content': 'JSON_OR_CONTRACT_REPAIR_REQUIRED\n' + previous.get('error', '')
                             + '\nReturn the complete original answer as one valid JSON object. No facts or sources have changed.'})
    save(folder / f'request-{number}.json', {'messages': messages, 'temperature': .2, 'max_output_tokens': 4096})
    budget.begin_attempt(slot)
    call_id, started = logger.begin(slot, messages, .2)
    try:
        try:
            response = await client.achat_with_metadata(messages, temperature=.2)
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            result = {'status': 'provider_unknown_attempt' if status is None else 'provider_failed',
                      'error_type': type(exc).__name__, 'http_status': status}
            logger.failed(call_id, started, RuntimeError(f'Provider failure {type(exc).__name__}; HTTP={status}'))
            if status is None or status in {401, 402, 403}:
                halt.set()
        else:
            logger.succeeded(call_id, started, response.content, response.metadata)
            try:
                result = evaluate(response.content, window, job['arm'],previous if number>1 else None)
            except Exception as exc:
                result={'status':'evaluation_error','error_type':type(exc).__name__,
                    'raw_content':response.content,'error':'Unexpected local evaluator failure; stop, do not replay provider'}
                halt.set()
            if 'parsed' in result:
                logger.parsed(call_id, result['parsed'])
                if result['status'] == 'accepted':
                    logger.contract_validated(call_id)
                else:
                    logger.contract_failed(call_id, ValueError(result['error']))
            elif result['status']!='evaluation_error':
                logger.parse_failed(call_id, ValueError(result['error']))
            result['metadata'] = response.metadata
        if result['status']=='evaluation_error':
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
        'all_first_slots_accounted': len(results) == len(protocol['jobs']), 'provider_halt': halt.is_set(),
        'calls': budget.usage(), 'quality_review': 'pending; contract acceptance is not quality',
        'macro_execution': False})


def run(authorized_cap):
    # Previous budgets covered completed batches; this new batch has authorized cap0 until independently approved.
    if type(authorized_cap) is not int or authorized_cap != 40:
        raise ValueError('This new frozen batch needs an explicit independent cap of40, including8 retries')
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
        'scope': 'New explicit authorization only; no inherited6 or any earlier balance, paid judge or macro action',
        'protocol_sha256': sha(OUT / 'protocol.json'), 'transport': policy})
    store = TaskStore(run_id='capstone-v24-narrative-repair', organization_ids=['experiment-host'], path=OUT / 'run/budget.sqlite')
    budget = ModelCallBudget(store=store, budget_id='new-explicit-cap40', max_calls=40)
    logger = LLMCallAuditLogger(OUT / 'run', 'CAPSTONE-V24', client)
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
