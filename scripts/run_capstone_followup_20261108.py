"""Bounded confirmation and legacy S/D3 experiments on frozen task inputs.

No automatic resume/replay; no model-built evidence or macro execution. Uses
existing transport, durable task/budget journal, audit and business validators.
"""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from prepare_capstone_followup_20261108 import OUT,BASELINE,legacy_module,read,save,sha
from src.coordination.tasks import TaskStore
from src.coordination.model_budget import ModelCallBudget
from src.run_audit import LLMCallAuditLogger,utc_now
from src.llm_client import OpenAICompatibleClient,extract_json_object
from src.prompt_contracts import require_management_decision,require_bid_document_shape
from src.stages.reconsideration import _require_reconsideration_decision
from src.agent_message_contracts import require_agent_message
from src.verification import require_condition_disposition,_require_no_verified_reopening

CAPS={'confirmation':96,'organization':144}
_legacy=None
_legacy_contract=None


def jid(job):return f'{job["window_id"]}-{job["arm"]}-r{job["repeat"]}'


def frozen_legacy_contract():
    global _legacy_contract
    if _legacy_contract is None:
        spec=importlib.util.spec_from_file_location('followup_original_bid_contract',BASELINE/'src/prompt_contracts.py')
        _legacy_contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(_legacy_contract)
    return _legacy_contract


def evaluate(raw,w,batch,arm,*,comment=False):
    result={'raw_content':raw,'status':'invalid_json'}
    try:
        data=extract_json_object(raw)
        if not isinstance(data,dict):raise ValueError('Expected one JSON object')
        result['parsed']=data
        if comment:
            require_agent_message(data);_require_no_verified_reopening(data,w['conditions'])
        else:
            if w['marker']=='BID_DOCUMENT':
                try:require_bid_document_shape(data);result['common_arithmetic_pass']=True
                except (ValueError,TypeError,KeyError) as exc:
                    result['common_arithmetic_pass']=False;result['common_arithmetic_error']=str(exc)
            old=batch=='confirmation' and arm=='v2_baseline'
            if w['marker']=='BID_DOCUMENT':
                if old:frozen_legacy_contract().require_bid_document_shape(data,enforce_quotation_match=False)
                else:require_bid_document_shape(data)
            else:
                {'MANAGEMENT_DECISION':require_management_decision,
                 'RECONSIDER_AFTER_CONSORTIUM':_require_reconsideration_decision}[w['marker']](data)
            if old:
                global _legacy
                if _legacy is None:_legacy=legacy_module()
                _legacy.require_condition_disposition(data,w['conditions'])
            else:require_condition_disposition(data,w['conditions'],submission=False)
        result['status']='accepted'
    except (ValueError,TypeError,KeyError,RuntimeError) as exc:
        result['status']='validation_failed' if 'parsed' in result else 'invalid_json'
        result['error']=f'{type(exc).__name__}: {exc}'
    return result


def final_messages(w,job,batch,comments=()):
    if batch=='confirmation':return deepcopy(w['confirmation_messages'][job['arm']])
    messages=deepcopy(w['organization_messages'])
    messages[-1]['content']+='\nSame actual archived department roster available in both modes:\n'+json.dumps(
        [r['identity'] for r in w['role_prompts']],ensure_ascii=False)
    if job['arm']=='role_discussion':
        messages[-1]['content']+='\nThree planned sequential department comments (model-generated opinions, not new facts):\n'+json.dumps(comments,ensure_ascii=False)
        messages[-1]['content']+='\nMake your own final decision. Do not resolve an unknown merely because colleagues agree. Failed comment slots provide no evidence.'
    return messages


async def request(client,budget,logger,folder,job,w,batch,phase,messages,number,halt):
    path=folder/'jobs'/jid(job)/f'{phase}-attempt-{number}.json'
    if path.exists():raise RuntimeError('Refuse to replay an existing model request')
    if halt.is_set():return {'status':'not_started_provider_halt'}
    slot=f'{jid(job)}:{phase}:{number}'
    if not budget.reserve(slot,1):return {'status':'not_started_budget_exhausted'}
    save(path.with_name(f'{phase}-request-{number}.json'),{'messages':messages,'temperature':.2,'max_output_tokens':4096})
    budget.begin_attempt(slot)
    call_id,started=logger.begin(slot,messages,.2)
    try:
        response=await client.achat_with_metadata(messages,temperature=.2)
        logger.succeeded(call_id,started,response.content,response.metadata)
        result=evaluate(response.content,w,batch,job['arm'],comment=phase!='final')
        if 'parsed' in result:
            logger.parsed(call_id,result['parsed'])
            if result['status']=='accepted':logger.contract_validated(call_id)
            else:logger.contract_failed(call_id,ValueError(result['error']))
        else:logger.parse_failed(call_id,ValueError(result['error']))
        result['metadata']=response.metadata
    except Exception as exc:
        status=getattr(exc,'status_code',None)
        result={'status':'provider_failed','error_type':type(exc).__name__,'http_status':status}
        logger.failed(call_id,started,RuntimeError(f'Provider failure {type(exc).__name__}; HTTP status={status}'))
        if status in {401,402,403}:halt.set()
    finally:budget.finish(slot)
    result.update(job=job,phase=phase,attempt=number,call_id=call_id,seconds=time.perf_counter()-started)
    save(path,result);save(folder/'budget_usage.json',budget.usage())
    print(batch,jid(job),phase,number,result['status'],'charged=',budget.usage()['charged_or_reserved_calls'],flush=True)
    return result


async def perform(client,budget,logger,folder,batch,protocol,windows):
    semaphore=asyncio.Semaphore(protocol['concurrency']);halt=asyncio.Event()
    jobs=protocol['jobs'][batch]
    async def first(job):
        async with semaphore:
            w=windows[job['window_id']];comments=[]
            if batch=='organization' and job['arm']=='role_discussion':
                for role in w['role_prompts']:
                    messages=[{'role':'system','content':role['system']},{'role':'user','content':role['user_prefix']
                        +'\nPrior model comments (not sources):\n'+json.dumps(comments,ensure_ascii=False)}]
                    response=await request(client,budget,logger,folder,job,w,batch,f'role-{role["index"]}',messages,1,halt)
                    if response['status']=='accepted':
                        comments.append({'identity':role['identity'],'status':'accepted',
                            'opinion':{k:v for k,v in response['parsed'].items() if k!='thoughts'}})
                    else:comments.append({'identity':role['identity'],'status':response['status'],'opinion':None})
            messages=final_messages(w,job,batch,comments)
            response=await request(client,budget,logger,folder,job,w,batch,'final',messages,1,halt)
            result={'job':job,'first_status':response['status'],'final_status':response['status'],
                'organization_complete':all(r['status']=='accepted' for r in comments),
                'planned_comments':3 if comments else 0,'accepted_comments':sum(r['status']=='accepted' for r in comments)}
            save(folder/'jobs'/jid(job)/'outcome.json',result)
            return result
    initial=await asyncio.gather(*(first(job) for job in jobs))
    save(folder/'initial_status.json',initial)
    # Comments are not regenerated after seeing final decisions. Only invalid
    # final JSON/contract responses may be retried, keeping first responses.
    candidates=[r for r in initial if r['first_status'] in {'invalid_json','validation_failed'}]
    for row in candidates[:protocol['planned'][batch]['max_final_retries']]:
        if halt.is_set():break
        job=row['job'];p=folder/'jobs'/jid(job)
        previous=read(p/'final-attempt-1.json');messages=read(p/'final-request-1.json')['messages']
        messages=messages+[{'role':'assistant','content':previous['raw_content']},
            {'role':'user','content':'SCHEMA_REPAIR_REQUIRED\nRegenerate the complete JSON for the same task. '
             'No new sources have arrived. Preserve source states and correct your own proposed amounts if needed. '
             'Validation error: '+previous.get('error','Invalid JSON')}]
        response=await request(client,budget,logger,folder,job,windows[job['window_id']],batch,'final',messages,2,halt)
        row['final_status']=response['status'];save(p/'outcome.json',row)
    save(folder/'execution_status.json',{'provider_halt':halt.is_set(),'jobs':initial})


def verify_frozen(protocol):
    if sha(OUT/'windows.json')!=protocol['windows_sha256']:raise ValueError('Frozen windows changed')
    if sha(OUT/'measurement_targets.json')!=protocol['targets_sha256']:raise ValueError('Frozen targets changed')
    if sha(OUT/'sample_manifest.json')!=protocol['manifest_sha256']:raise ValueError('Frozen manifest changed')
    if any(sha(ROOT/p)!=h for p,h in protocol['code_sha256'].items()):raise ValueError('Frozen execution code changed')
    if sha(BASELINE/'src/verification.py')!=protocol['baseline_verification_sha256']:raise ValueError('Frozen baseline changed')
    if sha(BASELINE/'src/prompt_contracts.py')!=protocol['baseline_bid_contract_sha256']:raise ValueError('Frozen baseline bid contract changed')


def summarize(batch):
    folder=OUT/batch;protocol=read(OUT/'protocol.json');rows=[]
    for job in protocol['jobs'][batch]:
        p=folder/'jobs'/jid(job)/'outcome.json'
        rows.append(read(p) if p.exists() else {'job':job,'first_status':'not_started_or_unknown','final_status':'not_started_or_unknown'})
    arms={}
    attempts=[read(p) for p in folder.glob('jobs/*/*-attempt-*.json')]
    for arm in sorted({r['job']['arm'] for r in rows}):
        rr=[r for r in rows if r['job']['arm']==arm];aa=[a for a in attempts if a['job']['arm']==arm]
        arms[arm]={'planned_final_tasks':len(rr),'first_accepted':sum(r['first_status']=='accepted' for r in rr),
            'final_accepted':sum(r['final_status']=='accepted' for r in rr),
            'complete_organization_tasks':sum(r.get('organization_complete',False) for r in rr),
            'actual_requests':len(aa),'tokens':{k:sum(a.get('metadata',{}).get('usage_metadata',{}).get(k,0) for a in aa)
                for k in ['input_tokens','output_tokens','total_tokens']},
            'request_seconds_sum':sum(a['seconds'] for a in aa)}
    save(folder/'results.json',rows);save(folder/'summary.json',{'arms':arms,'content_review':'pending common frozen-target review; acceptance is not quality',
        'macro_execution':False,'paper_or_final_charts_created':False})
    print(json.dumps(arms,ensure_ascii=False))


def run(batch,authorized_cap):
    names=list(CAPS) if batch=='all' else [batch]
    expected=sum(CAPS[name] for name in names)
    if type(authorized_cap)is not int or authorized_cap!=expected:
        raise ValueError(f'This concrete batch requires separately authorized maximum {expected} calls')
    protocol=read(OUT/'protocol.json');verify_frozen(protocol)
    for name in names:
        if (OUT/name/'llm_calls.jsonl').exists():raise RuntimeError('Existing/unknown requests; do not automatically resume or replay')
    client=OpenAICompatibleClient.from_env(model=protocol['model'])
    policy=client.request_policy()
    if policy['provider']!='deepseek' or policy['internal_retries']!=0:raise ValueError('Unexpected transport or hidden retries')
    client._chat_model.max_tokens=protocol['max_output_tokens']
    params=client._chat_model._default_params
    if params.get('max_tokens',params.get('max_completion_tokens'))!=4096:raise ValueError('Output token cap not bound')
    save(OUT/f'authorization-{batch}.json',{'at':utc_now(),'max_calls':authorized_cap,'batches':names,
        'scope':'New explicit user authorization only; no inherited balance; no paid judge or macro call',
        'protocol_sha256':sha(OUT/'protocol.json'),'transport':policy,'max_output_tokens':4096})
    async def main():
        try:
            for name in names:
                folder=OUT/name;folder.mkdir(exist_ok=True)
                store=TaskStore(run_id='capstone-followup-20261108-'+name,organization_ids=['experiment-host'],path=folder/'budget.sqlite')
                budget=ModelCallBudget(store=store,budget_id='new-authorization-'+name,max_calls=CAPS[name])
                logger=LLMCallAuditLogger(folder,'CAPSTONE-FOLLOWUP-'+name,client)
                try:await perform(client,budget,logger,folder,name,protocol,read(OUT/'windows.json'))
                finally:save(folder/'budget_usage.json',budget.usage());store.close()
                summarize(name)
                if read(folder/'execution_status.json')['provider_halt']:break
        finally:await client._chat_model.root_async_client.close()
    try:asyncio.run(main())
    finally:client._chat_model.root_client.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','summarize'])
    parser.add_argument('--batch',choices=['all',*CAPS],required=True);parser.add_argument('--authorize-max-calls',type=int)
    args=parser.parse_args()
    if args.action=='run':run(args.batch,args.authorize_max_calls)
    else:
        for name in (list(CAPS) if args.batch=='all' else [args.batch]):summarize(name)
