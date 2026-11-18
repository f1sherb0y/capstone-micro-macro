"""Real bounded V2 confirmation on the already frozen twelve windows.

Uses the original transport, durable call budget, audit logger and stage
validators. No macro execution, new source facts or silent response recovery.
"""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from run_capstone_core_validation_20261108 import BASE,read,save,sha
from src.coordination.tasks import TaskStore
from src.coordination.model_budget import ModelCallBudget
from src.run_audit import LLMCallAuditLogger,utc_now
from src.llm_client import OpenAICompatibleClient,extract_json_object
from src.prompt_contracts import require_management_decision
from src.stages.reconsideration import _require_reconsideration_decision
from src.stages.bid_documents import _require_bid_response
from src.verification import require_condition_disposition

SOURCE=BASE/'实验/2026-11-08_微观验证核心批次/v2'
OUT=BASE/'实验/2026-11-08_V2真实模型确认'
CAP=96


def job_id(job):
    return f'{job["window_id"]}-{job["arm"]}-r{job["repeat"]}'


def stage_validate(data,window,arm):
    validator={'MANAGEMENT_DECISION':require_management_decision,
               'RECONSIDER_AFTER_CONSORTIUM':_require_reconsideration_decision,
               'BID_DOCUMENT':_require_bid_response}[window['marker']]
    validator(data)
    if arm=='repaired':
        # Cost windows are draft-only; this does not authorize submission.
        require_condition_disposition(data,window['conditions'],submission=False)


def common_checks(data,window):
    # Old outputs are not penalized for lacking the new protocol fields.
    # This measurement projection never replaces raw or parsed model output.
    projected=deepcopy(data)
    records=window['conditions']
    projected.update(unresolved_condition_ids=[r['condition_id'] for r in records if r['status']!='verified'],
                     verified_condition_ids=[r['condition_id'] for r in records if r['status']=='verified'],
                     bid_assumptions=['Measurement-only placeholder'])
    flags={'known_unsupported_confirmation':False}
    try:
        require_condition_disposition(projected,records)
    except (ValueError,TypeError,KeyError) as exc:
        flags['known_unsupported_confirmation']='Unsupported confirmation' in str(exc)
    if window['marker']=='BID_DOCUMENT':
        try:
            total=sum(Decimal(str(x['amount'])) for x in data['quotation_breakdown'])
            flags['quotation_breakdown_difference']=str(Decimal(str(data['quotation']))-total)
            flags['quotation_breakdown_matches']=abs(Decimal(str(data['quotation']))-total)<=1
        except (ValueError,TypeError,KeyError,ArithmeticError):
            flags['quotation_breakdown_matches']=False
    return flags


def evaluate(raw,window,arm):
    result={'raw_content':raw,'status':'invalid_json'}
    try:
        data=extract_json_object(raw)
        if not isinstance(data,dict):raise ValueError('Expected a JSON object')
        result.update(parsed=data,common_checks=common_checks(data,window))
        stage_validate(data,window,arm)
        result['status']='accepted'
    except (ValueError,TypeError,KeyError,RuntimeError) as exc:
        result['status']='validation_failed' if 'parsed' in result else 'invalid_json'
        result['error']=f'{type(exc).__name__}: {exc}'
    return result


def prepare():
    config=read(SOURCE/'config.json');manifest=read(SOURCE/'sample_manifest.json')
    if len(manifest)!=12 or len(config['jobs'])!=72:raise ValueError('Unexpected frozen sample/job count')
    if (OUT/'protocol.json').exists():
        protocol=read(OUT/'protocol.json')
        if protocol['runner_sha256']!=sha(Path(__file__)):raise RuntimeError('Frozen experiment runner changed')
        return
    OUT.mkdir(parents=True,exist_ok=False)
    windows={}
    for item in manifest:
        path=SOURCE/item['window_file'];w=read(path)
        if hashlib.sha256(json.dumps(w['messages'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()!=w['input_sha256']:
            raise ValueError('Frozen input digest mismatch')
        windows[w['window_id']]=w
    save(OUT/'frozen_windows.json',windows)
    files=['src/verification.py','src/llm_client.py','src/prompt_contracts.py','src/stages/reconsideration.py','src/stages/bid_documents.py']
    save(OUT/'protocol.json',{'version':'v2-confirmation.v1','prepared_at':utc_now(),'runner_sha256':sha(Path(__file__)),
        'source_config_sha256':sha(SOURCE/'config.json'),'source_manifest_sha256':sha(SOURCE/'sample_manifest.json'),
        'source_targets_sha256':sha(SOURCE/'measurement_targets.json'),'windows_sha256':sha(OUT/'frozen_windows.json'),
        'business_code':{p:sha(ROOT/p) for p in files},'model':config['model'],'temperature':config['temperature'],
        'max_output_tokens':config['max_output_tokens_per_attempt'],'max_calls':CAP,'initial_calls':72,
        'maximum_extra_validation_attempts':24,'maximum_extra_attempts_per_job':1,'concurrency':2,
        'authorization':'User explicitly selected maximum 96 calls including retries in this conversation',
        'jobs':config['jobs'],'source_config_authorization_was_zero':'Preserved as planning record; this protocol records the new authorization',
        'same_input_scope':'Original/fixed arms share frozen external facts; repaired includes the prior own-company condition register. Context length is not matched.',
        'primary':'All first responses evaluated by the common frozen material targets; schema acceptance is secondary and arm-specific',
        'sampling':'10 archived decision inputs plus 2 derived synthetic tasks; not blind external validation',
        'draft_and_intent_only':True,'macro_execution':False,'provider_failure_retry':False,
        'stop':'Cap, unknown prior attempt, code/input mismatch, or fatal provider authorization/balance error; no automatic replay'})
    print('V2 protocol frozen; no provider call during prepare.',flush=True)


async def attempt(client,budget,logger,job,window,number,halt):
    identity=job_id(job);folder=OUT/'jobs'/identity
    result_path=folder/f'attempt-{number}.json'
    if result_path.exists():raise RuntimeError('Cannot replay an existing independent model attempt')
    if halt.is_set():return {'status':'not_started_provider_halt'}
    slot=f'{identity}:{number}'
    if not budget.reserve(slot,1):return {'status':'not_started_budget_exhausted'}
    messages=deepcopy(window['messages'][job['arm']])
    if number==2:
        previous=read(folder/'attempt-1.json')
        messages += [{'role':'assistant','content':previous.get('raw_content','')},
                     {'role':'user','content':'Regenerate the complete JSON for the same task. Prior validation error: '
                      +previous.get('error','Invalid JSON')+'. Keep text concise, include every required id, and do not invent verified sources.'}]
    save(folder/f'request-{number}.json',{'messages':messages,'temperature':0.2,'max_output_tokens':4096})
    budget.begin_attempt(slot)
    call_id,started=logger.begin(identity+f'/attempt-{number}',messages,0.2)
    try:
        response=await client.achat_with_metadata(messages,temperature=0.2)
        logger.succeeded(call_id,started,response.content,response.metadata)
        result=evaluate(response.content,window,job['arm'])
        if 'parsed' in result:
            logger.parsed(call_id,result['parsed'])
            if result['status']=='accepted':logger.contract_validated(call_id)
            else:logger.contract_failed(call_id,ValueError(result['error']))
        else:
            logger.parse_failed(call_id,ValueError(result['error']))
        result.update(metadata=response.metadata,seconds=time.perf_counter()-started)
    except Exception as exc:
        status=getattr(exc,'status_code',None)
        # Do not serialize raw provider errors, headers or credentials.
        logger.failed(call_id,started,RuntimeError(f'Provider failure {type(exc).__name__}; HTTP status={status}'))
        result={'status':'provider_failed','error_type':type(exc).__name__,'http_status':status,'seconds':time.perf_counter()-started}
        if status in {401,402,403}:halt.set()
    finally:
        budget.finish(slot)
    result.update(job=job,attempt=number,call_id=call_id,origin=window['origin'],focus=window['focus'])
    save(result_path,result)
    save(OUT/'budget_usage.json',budget.usage())
    print(identity,f'attempt={number}',result['status'],'charged=',budget.usage()['charged_or_reserved_calls'],flush=True)
    return result


async def perform(client,budget,logger,protocol,windows):
    semaphore=asyncio.Semaphore(protocol['concurrency']);halt=asyncio.Event()
    async def limited(job,number):
        async with semaphore:
            return await attempt(client,budget,logger,job,windows[job['window_id']],number,halt)
    initial=await asyncio.gather(*(limited(job,1) for job in protocol['jobs']))
    save(OUT/'execution_status.json',{'initial':{job_id(j):r['status'] for j,r in zip(protocol['jobs'],initial)},
                                    'provider_halt':halt.is_set()})
    retries=[job for job,result in zip(protocol['jobs'],initial) if result['status'] in {'invalid_json','validation_failed'}]
    for start in range(0,min(24,len(retries)),protocol['concurrency']):
        if halt.is_set():break
        await asyncio.gather(*(limited(job,2) for job in retries[start:start+protocol['concurrency']]))
    save(OUT/'budget_usage.json',budget.usage())


def run(cap):
    if type(cap)is not int or cap!=CAP:raise ValueError('Explicit newly authorized --max-calls 96 is required')
    prepare();protocol=read(OUT/'protocol.json')
    if (OUT/'llm_calls.jsonl').exists():raise RuntimeError('Existing model attempts: inspect their status, never automatically restart')
    if protocol['windows_sha256']!=sha(OUT/'frozen_windows.json'):raise RuntimeError('Frozen inputs changed')
    for p,d in protocol['business_code'].items():
        if sha(ROOT/p)!=d:raise RuntimeError('Frozen business code changed')
    client=OpenAICompatibleClient.from_env(model=protocol['model'])
    policy=client.request_policy()
    if policy['provider']!='deepseek' or policy['internal_retries']!=0:raise RuntimeError('Unexpected provider/retry policy')
    client._chat_model.max_tokens=protocol['max_output_tokens']
    params=client._chat_model._default_params
    if params.get('max_tokens',params.get('max_completion_tokens'))!=4096:raise RuntimeError('Output cap not bound to transport')
    save(OUT/'transport.json',{**policy,'max_calls':cap,'max_output_tokens':4096})
    store=TaskStore(run_id='capstone-v2-confirmation-20261108',organization_ids=['experiment-host'],path=OUT/'budget.sqlite')
    budget=ModelCallBudget(store=store,budget_id='new-user-authorized-96',max_calls=cap)
    logger=LLMCallAuditLogger(OUT,'V2-CONFIRMATION-20261108',client)
    async def main_async():
        try:await perform(client,budget,logger,protocol,read(OUT/'frozen_windows.json'))
        finally:await client._chat_model.root_async_client.close()
    try:asyncio.run(main_async())
    finally:
        save(OUT/'budget_usage.json',budget.usage());store.close();client._chat_model.root_client.close()
    report()


def report():
    protocol=read(OUT/'protocol.json');windows=read(OUT/'frozen_windows.json');rows=[]
    started=set()
    if (OUT/'llm_calls.jsonl').exists():
        for line in (OUT/'llm_calls.jsonl').read_text(encoding='utf-8').splitlines():
            event=json.loads(line)
            if event['event_type']=='request_started':started.add(event['marker'].split('/attempt-')[0])
    status=read(OUT/'execution_status.json')['initial'] if (OUT/'execution_status.json').exists() else {}
    for job in protocol['jobs']:
        results=[read(p) for p in sorted((OUT/'jobs'/job_id(job)).glob('attempt-*.json'))]
        rows.append({**job,'job_id':job_id(job),'origin':windows[job['window_id']]['origin'],
            'focus':windows[job['window_id']]['focus'],'attempts':len(results),
            'first':results[0] if results else {'status':'unknown_attempt' if job_id(job) in started else status.get(job_id(job),'not_started')},
            'final':results[-1] if results else {'status':'unknown_attempt' if job_id(job) in started else status.get(job_id(job),'not_started')}})
    save(OUT/'results.json',rows)
    arms={}
    for arm in ['original','repaired']:
        rs=[r for r in rows if r['arm']==arm]
        usage={k:0 for k in ['input_tokens','output_tokens','total_tokens']};seconds=0
        for p in (OUT/'jobs').glob('*/attempt-*.json'):
            a=read(p)
            if a['job']['arm']!=arm:continue
            seconds+=a.get('seconds',0)
            for k in usage:usage[k]+=a.get('metadata',{}).get('usage_metadata',{}).get(k,0)
        arms[arm]={'planned':len(rs),'initial_accepted':sum(r['first']['status']=='accepted' for r in rs),
            'final_accepted':sum(r['final']['status']=='accepted' for r in rs),'attempts':sum(r['attempts'] for r in rs),
            'known_phrase_flags':sum(r['first'].get('common_checks',{}).get('known_unsupported_confirmation',False) for r in rs),
            'initial_provider_or_json_failures':sum(r['first']['status'] in {'provider_failed','invalid_json','not_started'} for r in rs),
            'provider_reported_usage':usage,'request_seconds_sum':seconds,
            'historical_planned':sum(r['origin']=='archived_decision_input' for r in rs),
            'synthetic_planned':sum(r['origin']=='derived_synthetic_question' for r in rs)}
    save(OUT/'summary.json',{'at':utc_now(),'arms':arms,'money':None,'warning':'Arm-specific schema acceptance is not an independent content quality score',
        'first_responses_primary':True,'scoring_status':'common material targets still require formative review',
        'macro_execution':False,'comparison_scope':'10 historical plus 2 derived tasks, three repeats; same project/condition repetitions are dependent'})
    print(json.dumps(arms,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','report'])
    parser.add_argument('--max-calls',type=int)
    args=parser.parse_args()
    run(args.max_calls) if args.action=='run' else globals()[args.action]()
