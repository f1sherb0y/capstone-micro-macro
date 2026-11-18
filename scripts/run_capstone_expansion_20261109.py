"""Reuse released V2.5 transport/evaluator for an independently budgeted batch.

This adapter only redirects the isolated output and frozen protocol in memory;
it does not edit the previous runner or any released production source.
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from prepare_capstone_expansion_20261109 import OUT,CAP,PREVIOUS,REPAIR,GROUPS,read,save,sha
import run_capstone_v2_5_20261109 as engine


def verify_frozen():
    p=read(OUT/'protocol.json')
    for name,key in (('windows.json','windows_sha256'),('targets.json','targets_sha256'),('sample_manifest.json','manifest_sha256')):
        if sha(OUT/name)!=p[key]:raise ValueError('Frozen input changed: '+name)
    for name,h in p['code_sha256'].items():
        if sha(ROOT/name)!=h:raise ValueError('Frozen code changed: '+name)
    for name,key in (('verification.py','baseline_verification_sha256'),('company_narrative.py','baseline_narrative_sha256')):
        if sha(REPAIR/'baseline/src'/name)!=p[key]:raise ValueError('Captured V2.4 baseline changed')
    if sha(GROUPS)!=p['group_file_sha256'] or any(sha(ROOT/n)!=h for n,h in p['source_sha256'].items()):raise ValueError('Source/grouping changed')
    if sha(PREVIOUS/'live_release_manifest.json')!=p['prior_release_manifest_sha256']:raise ValueError('Previous release changed')
    return p


# The engine's original request/perform functions resolve these module globals.
engine.OUT=OUT
engine.verify_frozen=verify_frozen
evaluate=engine.evaluate


def run(authorized_cap):
    if type(authorized_cap) is not int or authorized_cap!=CAP:
        raise ValueError('This frozen expansion requires new explicit authorization of240 including retries; no previous balance applies')
    protocol=verify_frozen()
    if not read(OUT/'preflight.json')['passed']:raise ValueError('Completed preflight required')
    if (OUT/'run').exists() or (OUT/'authorization.json').exists():raise RuntimeError('Existing/unknown attempt; do not automatically replay')
    client=engine.OpenAICompatibleClient.from_env(model=protocol['model'])
    policy=client.request_policy()
    if policy['provider']!='deepseek' or policy['internal_retries']!=0:raise ValueError('Unexpected provider or hidden retry policy')
    client._chat_model.max_tokens=protocol['max_output_tokens']
    params=client._chat_model._default_params
    if params.get('max_tokens',params.get('max_completion_tokens'))!=4096:raise ValueError('Output cap not bound')
    save(OUT/'authorization.json',{'at':engine.utc_now(),'max_calls':CAP,'protocol_sha256':sha(OUT/'protocol.json'),
      'scope':'New independently authorized24-project expansion only; no inherited budget, paid judge or macro lifecycle.','transport':policy})
    store=engine.TaskStore(run_id='capstone-expanded24-20261109',organization_ids=['experiment-host'],path=OUT/'run/budget.sqlite')
    budget=engine.ModelCallBudget(store=store,budget_id='new-explicit-cap240',max_calls=CAP)
    logger=engine.LLMCallAuditLogger(OUT/'run','CAPSTONE-EXPANDED24',client)
    async def main():
        try:await engine.perform(client,budget,logger,protocol,read(OUT/'windows.json'))
        finally:
            save(OUT/'run/budget_usage.json',budget.usage())
            await client._chat_model.root_async_client.close()
    try:asyncio.run(main())
    finally:
        store.close();client._chat_model.root_client.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--authorize-max-calls',type=int)
    run(parser.parse_args().authorize_max_calls)
