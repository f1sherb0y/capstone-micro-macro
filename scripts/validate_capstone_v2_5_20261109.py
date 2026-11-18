"""Final scoped role/context repair: offline fixtures and seen-response replay."""
from pathlib import Path
import sys
import json
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from prepare_capstone_v2_4_20261109 import OUT as OLD, REPAIR as PREVIOUS,read,save,sha
OUT=PREVIOUS.parent/'2026-11-09_V2_5_角色与语境最终确认'
FILES=['src/company_narrative.py','src/verification.py','src/agent_runtime.py','src/models.py',
 'src/response_repair.py','src/stages/participation.py','src/stages/reconsideration.py','src/stages/bid_documents.py',
 'scripts/run_capstone_v2_4_20261109.py','scripts/prepare_capstone_v2_4_20261109.py']

def initialize():
    assert not (OUT/'baseline.json').exists()
    old=read(OLD/'live_release_manifest.json');offline=read(PREVIOUS/'release_manifest.json')
    assert all(sha(OLD/n)==h for n,h in old['files'].items())
    assert all(sha(PREVIOUS/n)==h for n,h in offline['files'].items())
    for n in FILES:
        p=OUT/'baseline'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
    save(OUT/'baseline.json',{'source':{n:sha(ROOT/n) for n in FILES},'prior_live_manifest_sha256':sha(OLD/'live_release_manifest.json'),
      'prior_live_files':old['files'],'prior_offline_files':offline['files'],'provider_calls_authorized':0,
      'scope':'Final role-contract/context repair, offline checks, one proposed fixed confirmation. No macro/Top5/paper changes; no inherited1.'})
    print('V2.4 baseline captured; historical archives intact; current paid authorization0.')

def run_offline():
    import asyncio,socket
    from copy import deepcopy
    from unittest.mock import patch
    from collections import Counter
    from run_capstone_core_validation_20261108 import NoProviderNetwork
    from src.company_narrative import review_company_narrative
    from src.company_grounding import company_evidence
    from src.task_role_contract import require_task_role
    from src.verification import require_condition_disposition
    from src.agent_runtime import AgentRuntime
    from src.models import ParticipationDecision,dump
    from src.stages.participation import run_bid_participation
    from src.stages.reconsideration import reconsider_after_failed_consortiums
    from src.stages.bid_documents import generate_bid_documents
    from tests.test_capstone_v2_5_repairs import CASES,RoleClient
    from tests.test_verification_conditions import solo_state
    dest=OUT/'offline';assert not dest.exists(),'Keep the completed offline evidence'
    save(OUT/'fixture_plan.json',{'origin':'Synthetic expectations authored in test source before execution; this JSON export follows the tests, not an unseen oracle',
      'cases':[{'id':i,'company':f,'text':t,'expected':s} for i,f,t,s in CASES],
      'test_source_sha256':sha(ROOT/'tests/test_capstone_v2_5_repairs.py')})
    windows=read(OLD/'windows.json');ann=read(OLD/'ai_review_annotations.json')['ratings'];secondary=read(OLD/'content_review_summary.json')['secondary_retry_review']
    rows,fixtures,stages=[],[],[];guard=NoProviderNetwork()
    class WrongRoleClient(RoleClient):
        async def achat(self,messages,temperature=.2):
            raw=await super().achat(messages,temperature)
            if messages[1]['content'].startswith('AGENT_MESSAGE'):return raw
            data=json.loads(raw);data['task_role']='contractor';return json.dumps(data,ensure_ascii=False)
    with asyncio.Runner() as runner:
        runner.get_loop()
        with patch.object(socket.socket,'connect',guard.block),patch.object(socket.socket,'connect_ex',guard.block),patch(
            'src.llm_client.OpenAICompatibleClient.from_env',side_effect=RuntimeError('V2.5 offline cap0')):
            for path in sorted((OLD/'run/jobs').glob('*/attempt-*.json')):
                r=read(path);w=windows[r['job']['window_id']];jid=path.parent.name
                probe=deepcopy(r['parsed']);probe['task_role']=w['role']
                source_report=review_company_narrative(probe,w['company_evidence'],contextual=True)
                save(dest/'narrative_reports'/f'{jid}-{r["attempt"]}.json',source_report)
                try:role_report=require_task_role(probe,w['role'])
                except ValueError as exc:role_report={'status':'role_conflict','error':str(exc)}
                try:require_condition_disposition(r['parsed'],w['conditions']);condition_error=None
                except ValueError as exc:condition_error=str(exc)
                score=next(x for x in (ann if r['attempt']==1 else secondary) if x['job_id']==jid)
                rows.append({'job_id':jid,'attempt':r['attempt'],'source_sha256':sha(path),'old_status':r['status'],
                  'old_source_score_unchanged':score['core_property_met'] if r['attempt']==1 else score['core_property_met_secondary'],
                  'new_bounded_source_status':source_report['status'],'new_role_prose_probe':role_report,
                  'new_condition_error':condition_error,'original_new_role_field':r['parsed'].get('task_role'),
                  'probe_note':'Host task_role added ONLY to a separate interface probe; not a model-authored field or retroactive old-format score. Raw answer and old scores unchanged.'})
            for ident,fields,text,expected in CASES:
                report=review_company_narrative({'content':text,'task_role':'supervisor'},company_evidence({'company_id':'SYNTHETIC-c',**fields}),contextual=True)
                fixtures.append({'id':ident,'expected':expected,'actual':report['status'],'passed':expected==report['status'],'report':report})
            for stage in ('management','reconsideration','bid'):
                for wrong in (False,True):
                    state=solo_state();runtime=AgentRuntime(WrongRoleClient() if wrong else RoleClient(),profile='smoke',
                      company_grounding=True,company_narrative_grounding=True,task_role_grounding=True)
                    if stage=='management':runner.run(run_bid_participation(state,runtime))
                    elif stage=='reconsideration':
                        state.participation_decisions=[ParticipationDecision('designer_001','design_package','bid_with_consortium','unformed')]
                        runner.run(reconsider_after_failed_consortiums(state,runtime))
                    else:
                        state.participation_decisions=[ParticipationDecision('designer_001','design_package','bid','proposal')]
                        runner.run(generate_bid_documents(state,runtime))
                    label=stage+('-wrong-role' if wrong else '-valid')
                    save(dest/'stages'/f'{label}.json',{'state':dump(state),'attempts':runtime.response_attempts,'source_kind':'SYNTHETIC, not actual companies or tenders'})
                    assert bool(state.validation_context.get('micro_output_pending'))==wrong
                    assert not state.verification_reviews and all(p.decision!='no_bid' for p in state.participation_decisions)
                    stages.append({'id':label,'passed':True,'evidence':f'stages/{label}.json'})
    assert len(rows)==39 and len([x for x in rows if x['attempt']==1])==32
    assert all(x['passed'] for x in fixtures) and guard.attempts==0
    old=read(OLD/'live_release_manifest.json')
    assert all(sha(OLD/n)==h for n,h in old['files'].items())
    save(dest/'development_replay.json',rows);save(dest/'source_fixture_results.json',fixtures)
    result={'provider_requests':0,'network_attempts':guard.attempts,'saved_answers_replayed':39,'firsts':32,'retries':7,
      'source_probe_statuses':dict(Counter(x['new_bounded_source_status'] for x in rows)),
      'role_probe_statuses':dict(Counter(x['new_role_prose_probe']['status'] for x in rows)),
      'condition_guard_errors':sum(x['new_condition_error'] is not None for x in rows),
      'fixtures_passed':len(fixtures),'stages':stages,'prior_live_archive_unchanged':True,
      'remaining_false_score_limited_passes':[{'job_id':x['job_id'],'attempt':x['attempt']} for x in rows if not x['old_source_score_unchanged'] and x['new_bounded_source_status']=='limited_checks_passed'],
      'note':'Seen development replay only; no old raw answer repaired/regraded. Remaining misses and review-needed cases are not hidden; no claim of universal semantics or improved new-model output.'}
    save(dest/'offline_result.json',result)
    print(json.dumps({k:result[k] for k in ('provider_requests','saved_answers_replayed','source_probe_statuses','role_probe_statuses','condition_guard_errors','fixtures_passed')}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','run'],default='init',nargs='?');args=p.parse_args()
    initialize() if args.action=='init' else run_offline()
