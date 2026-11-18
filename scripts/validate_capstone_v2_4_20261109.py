"""Scoped offline development replay/fixtures; never a repository source audit."""
from pathlib import Path
import argparse
import asyncio
from copy import deepcopy
import importlib.util
import json
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))
from prepare_capstone_v2_3_20261109 import OUT as OLD, REPAIR as PREVIOUS, read, save, sha

OUT = PREVIOUS.parent / '2026-11-09_V2_4_正文来源一致性与安全重试'
FILES = ['src/company_grounding.py','src/verification.py','src/agent_runtime.py','src/models.py',
 'src/stages/participation.py','src/stages/reconsideration.py','src/stages/bid_documents.py',
 'src/llm_client.py','scripts/run_capstone_v2_3_20261109.py',
 'scripts/prepare_capstone_v2_3_20261109.py','scripts/preflight_capstone_v2_3_20261109.py']

def initialize():
    assert not (OUT/'baseline.json').exists(), 'Keep captured baseline'
    manifest=read(OLD/'release_manifest.json')
    assert all(sha(OLD/n)==h for n,h in manifest['files'].items())
    for n in FILES:
        dest=OUT/'baseline'/n
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes((ROOT/n).read_bytes())
    goal=ROOT/'Capstone报告/验证体系/2026-11-09_GOAL_V2_4正文来源一致性与安全重试.md'
    (OUT/'goal_at_start.md').write_bytes(goal.read_bytes())
    save(OUT/'baseline.json',{'source':{n:sha(ROOT/n) for n in FILES},
       'prior_release_manifest_sha256':sha(OLD/'release_manifest.json'),
       'prior_release_files':manifest['files'],'provider_calls_authorized':0,
       'development_records':34,'prior_first_reviews':32,
       'goal_sha256':sha(goal),'macro_frozen':True})
    print('Captured V2.3 source/config baseline;34 saved responses and previous release intact; calls0.')

def fixture_plan():
    from tests.test_capstone_v2_4_repairs import CASES
    path=OUT/'fixture_plan.json'
    assert not path.exists(),'Preserve declared expectations'
    save(path,{'origin':'Author-declared synthetic property oracle; not model-derived gold or real company records',
       'source_cases':[{'id':i,'company':{'company_id':'SYNTHETIC-c',**f},'content':t,'expected':s}
           for i,f,t,s in CASES],
       'other_required_properties':['Two observed negation/future-plan contexts preserve unresolved conditions',
         'Independent affirmative/adversative/double-negative confirmations still rejected',
         'Same company/version/field source binding from V2.3 remains enforced',
         'Real participation/reconsideration/bid paths persist unchanged accepted text or explicit pending failure; no forced no_bid',
         'Retry sees original answer+exact issue; changes outside issue and decision changes require review',
         'Verified-only condition closure does not clear other hard prerequisites; ordinary support can continue'],
       'declared_before_execution_test_sha256':sha(ROOT/'tests/test_capstone_v2_4_repairs.py'),
       'provider_call_cap':0})
    (OUT/'declared_test_fixtures.py').write_bytes((ROOT/'tests/test_capstone_v2_4_repairs.py').read_bytes())
    print('Saved synthetic fixture expectations before execution; calls0.')

def run_offline(attempt):
    from src.agent_runtime import AgentRuntime
    from src.company_grounding import company_evidence,require_company_assessment
    from src.company_narrative import review_company_narrative
    from src.models import ParticipationDecision,dump
    from src.stages.participation import run_bid_participation
    from src.stages.reconsideration import reconsider_after_failed_consortiums
    from src.stages.bid_documents import generate_bid_documents
    from src.verification import require_condition_disposition,guarded_validator
    from src.prompt_contracts import require_management_decision
    from run_capstone_core_validation_20261108 import NoProviderNetwork,v0
    from tests.test_verification_conditions import solo_state
    from tests.test_capstone_v2_4_repairs import SourceFixtureClient,BadSourceClient,RepairClient,data_for
    dest=OUT/attempt
    assert not dest.exists(),'Preserve completed offline attempt'
    windows=read(OLD/'windows.json')
    reviews=read(OLD/'ai_review_annotations.json')['ratings']
    secondary=read(OLD/'content_review_summary.json')['secondary_retry_review']
    spec=importlib.util.spec_from_file_location('v24_captured_v23_guard',OUT/'baseline/src/verification.py')
    baseline=importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
    guard=NoProviderNetwork()
    replay,fixtures,stages,repairs=[],[],[],[]
    with asyncio.Runner() as runner:
        runner.get_loop()
        with patch.object(socket.socket,'connect',guard.block),patch.object(socket.socket,'connect_ex',guard.block),patch(
            'src.llm_client.OpenAICompatibleClient.from_env',side_effect=RuntimeError('V2.4 provider cap0')):
            for path in sorted((OLD/'run/jobs').glob('*/attempt-*.json')):
                raw=read(path); data=raw['parsed']; job=path.parent.name
                w=windows[raw['job']['window_id']]
                errors={}
                for name,fn in [('v2_3',baseline.require_condition_disposition),('v2_4',require_condition_disposition)]:
                    try:
                        fn(deepcopy(data),w['conditions'])
                        errors[name]=None
                    except (ValueError,TypeError,KeyError) as exc:
                        errors[name]=str(exc)
                reference_valid=None
                if raw['job']['arm']=='v2_3':
                    require_company_assessment(data,w['company_evidence'])
                    reference_valid=True
                report=review_company_narrative(data,w['company_evidence'])
                score=next(x for x in reviews if x['job_id']==job) if raw['attempt']==1 else next(x for x in secondary if x['job_id']==job)
                oldmet=score['core_property_met'] if raw['attempt']==1 else score['core_property_met_secondary']
                save(dest/'narrative_reports'/f'{job}-attempt{raw["attempt"]}.json',report)
                replay.append({'job_id':job,'attempt':raw['attempt'],'source_sha256':sha(path),
                  'source_path':str(path.relative_to(ROOT)),'saved_status':raw['status'],
                  'old_core_property_met_retained':oldmet,'old_review_reason':score.get('reason',score.get('note')),
                  'condition_guard_errors':errors,'reference_contract_valid':reference_valid,
                  'narrative_status':report['status'],'findings':report['findings'],
                  'unresolved_semantic_gap':not oldmet and report['status']=='limited_checks_passed',
                  'possible_overrestriction':oldmet and report['status']!='limited_checks_passed',
                  'raw_parsed_unchanged':data==read(path)['parsed']})
            planned=read(OUT/'fixture_plan.json')['source_cases']
            for extra in sorted(OUT.glob('fixture_plan_supplement_*.json')):
                planned+=read(extra)['source_cases']
            for case in planned:
                e=company_evidence(case['company'])
                report=review_company_narrative({'content':case['content']},e)
                fixtures.append({'id':case['id'],'declared_expected':case['expected'],'actual':report['status'],
                    'passed':case['expected']==report['status'],'report':report})
            for stage in ('management','reconsideration','bid'):
                for invalid in (False,True):
                    state=solo_state()
                    client=BadSourceClient() if invalid else SourceFixtureClient()
                    runtime=AgentRuntime(client,profile='smoke',company_grounding=True,company_narrative_grounding=True)
                    if stage=='management':
                        runner.run(run_bid_participation(state,runtime))
                    elif stage=='reconsideration':
                        state.participation_decisions=[ParticipationDecision('designer_001','design_package','bid_with_consortium','unformed')]
                        runner.run(reconsider_after_failed_consortiums(state,runtime))
                    else:
                        state.participation_decisions=[ParticipationDecision('designer_001','design_package','bid','proposal')]
                        runner.run(generate_bid_documents(state,runtime))
                    label=stage+('-blocked' if invalid else '-valid-proposal')
                    save(dest/'stages'/f'{label}.json',{'state':dump(state),'response_attempts':runtime.response_attempts,
                      'recovery_events':runtime.recovery_events,'source_kind':'synthetic fixture, not actual company decisions'})
                    pending=bool(state.validation_context.get('micro_output_pending'))
                    assert pending==invalid
                    assert not state.verification_reviews
                    assert all(x.decision!='no_bid' for x in state.participation_decisions)
                    stages.append({'id':label,'passed':True,'pending':pending,'accepted_not_forced_no_bid':not invalid,
                       'evidence':f'stages/{label}.json'})
            evidence=company_evidence({'company_id':'SYNTHETIC-c'})
            good=data_for(evidence); bad=deepcopy(good); bad['company_assessment']['company_id']='foreign'
            drift=deepcopy(good); drift['content']='本公司具备专业能力。'
            for label,answers,expected in [('reference-only',[json.dumps(bad),json.dumps(good)],'limited_checks_passed'),
                ('unrelated-drift',[json.dumps(bad),json.dumps(drift)],'RepairDriftError'),
                ('invalid-json',['{broken JSON',json.dumps(good)],'RepairDriftError')]:
                client=RepairClient(answers)
                runtime=AgentRuntime(client,company_grounding=True,company_narrative_grounding=True)
                result=None
                try:
                    result=runner.run(runtime.ask_json_async('SYNTHETIC fixture','MANAGEMENT_DECISION','No real company sources.',
                       validator=guarded_validator(require_management_decision,[],company_sources=evidence,narrative_grounding=True)))
                    status='limited_checks_passed'
                except (ValueError,TypeError,KeyError) as exc:
                    status=type(exc).__name__
                assert status==expected and len(client.messages)==2
                save(dest/'repairs'/f'{label}.json',{'expected':expected,'actual':status,'messages':client.messages,
                    'attempts':runtime.response_attempts,'returned_data':result,'source_kind':'synthetic, no provider'})
                repairs.append({'id':label,'passed':True,'evidence':f'repairs/{label}.json'})
            closures=v0(dest/'legacy_condition_closure',runner)
    assert len(replay)==34 and len([r for r in replay if r['attempt']==1])==32
    observed=[r for r in replay if r['saved_status']=='validation_failed']
    assert len(observed)==2 and all(r['condition_guard_errors']['v2_4'] is None for r in observed)
    assert all(c['passed'] for c in fixtures) and guard.attempts==0
    manifest=read(OLD/'release_manifest.json')
    assert all(sha(OLD/n)==h for n,h in manifest['files'].items())
    save(dest/'development_replay.json',replay)
    save(dest/'source_fixture_results.json',fixtures)
    from collections import Counter
    result={'provider_requests':0,'network_attempts':guard.attempts,'saved_answers_replayed':34,
      'firsts':32,'retries':2,'known_false_positives_released':2,
      'narrative_statuses':dict(Counter(r['narrative_status'] for r in replay)),
      'remaining_semantic_gaps':[{'job_id':r['job_id'],'attempt':r['attempt'],'old_reason':r['old_review_reason']} for r in replay if r['unresolved_semantic_gap']],
      'possible_overrestrictions':[{'job_id':r['job_id'],'attempt':r['attempt'],'findings':r['findings']} for r in replay if r['possible_overrestriction']],
      'source_fixture_n':len(fixtures),'stages':stages,'repair_cases':repairs,'condition_closure':closures,
      'prior_release_unchanged':True,'source_sha256':{n:sha(ROOT/n) for n in FILES if (ROOT/n).exists()},
      'added_source_sha256':{n:sha(ROOT/n) for n in ('src/company_narrative.py','src/response_repair.py')},
      'limits':'Development replay only; saved answers unchanged, prior scores retained. New format requirements not retroactively scored. Limited checks are not semantic correctness; review-required cases are not passed. No live-model effect established.'}
    save(dest/'offline_result.json',result)
    print(json.dumps({k:result[k] for k in ('provider_requests','saved_answers_replayed','known_false_positives_released','narrative_statuses','source_fixture_n')}))
    print('Remaining semantic gaps:',len(result['remaining_semantic_gaps']),'possible overrestrictions:',len(result['possible_overrestrictions']))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['init','plan','run'])
    parser.add_argument('--attempt',default='offline-attempt-001')
    args=parser.parse_args()
    if args.action=='init': initialize()
    elif args.action=='plan': fixture_plan()
    else: run_offline(args.attempt)
