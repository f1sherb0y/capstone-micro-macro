"""Freeze selected confirmation windows and preflight them without network/model calls.

Targets the existing 28-case archive only; uses prior project-group assignments.
This is experiment assembly, not a repository-wide source audit.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import socket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))
from run_capstone_core_validation_20261108 import BASE, OUT, read, save, sha, NoProviderNetwork
from src.models import Company, TenderPackage, SimulationState, load_simulation_state
from src.stages.participation import _management_prompt
from src.verification import conditions, evidence_context, record_review, require_condition_disposition
from src.coordination.tasks import TaskStore
from src.coordination.model_budget import ModelCallBudget
from src.run_audit import LLMCallAuditLogger
from src.prompt_contracts import require_management_decision
from src.stages.reconsideration import _require_reconsideration_decision
from src.stages.bid_documents import _require_bid_response
from tests.test_verification_conditions import message

ARCHIVE = ROOT/'validation/benchmark_ge3_compact/results/final_28_20260817/cases'
GROUPS = ROOT/'output/integration/capstone_retrieval_improvement_20261106/split_before_labels.json'
DEVELOPMENT = BASE/'实验/2026-11-08_条件传递修复对照/frozen_windows.json'
TARGET = OUT/'v2'
PATTERNS = {'personnel':r'档期|人员|团队可用|人力', 'qualification':r'资质|资格|业绩',
            'partner':r'伙伴|分包|顾问|联合体|组合体', 'cost':r'价格|成本|报价|利润'}


def text_field(text, label):
    match = re.search(r'^'+re.escape(label)+r':\s*([^\n]+)', text, re.M)
    return match.group(1).strip() if match else None


def rank(candidate, family):
    return hashlib.sha256((family+'/'+candidate['case_id']+'/'+candidate['call_id']).encode()).hexdigest()


def candidates():
    assignments=read(GROUPS)['assignments']
    group={r['case_id']:r['group'] for r in assignments}
    dev=read(DEVELOPMENT)
    dev_ids={'CASE-'+w['case'].split('-')[-1] for w in dev}
    excluded_groups={group[x] for x in dev_ids}
    rows=[];skips=[];snapshots={}
    for folder in sorted(ARCHIVE.glob('case-*')):
        case_id='CASE-'+folder.name.split('-')[-1]
        if group[case_id] in excluded_groups:
            skips.append({'case_id':case_id,'reason':'development or near-duplicate development group'})
            continue
        cp=read(folder/'workflow_checkpoint.json')['state'];snapshots[case_id]=cp
        companies={r['company_id']:r for r in cp['companies']}
        packages={r['package_id']:r for r in cp['tender_packages']}
        request_map={}
        # Match the source response solely for exact decision-time linkage;
        # selection ranks inputs, never historical correctness or winning choice.
        final_messages={m['content']:m for m in cp['agent_discussion_history'] if m['message_type']=='decision'}
        with (folder/'llm_calls.jsonl').open(encoding='utf-8-sig') as handle:
            for line in handle:
                event=json.loads(line);key=event.get('call_id');kind=event['event_type']
                if kind=='request_started' and event.get('marker') in {'MANAGEMENT_DECISION','RECONSIDER_AFTER_CONSORTIUM','BID_DOCUMENT'}:
                    request_map[key]=event
                elif kind=='request_succeeded' and key in request_map:
                    req=request_map.pop(key);messages=req['request']['messages']
                    text='\n'.join(m['content'] for m in messages if m['role']=='user')
                    company_id=text_field(text,'Company id') or text_field(text,'Bidder id')
                    package_id=text_field(text,'Package id')
                    if company_id not in companies or package_id not in packages or not 500 <= len(text) <= 70000:
                        skips.append({'case_id':case_id,'call_id':key,'reason':'not one exact company/package or prompt size outside declared bounds'})
                        continue
                    marker=req['marker']
                    if marker!='BID_DOCUMENT':
                        try:
                            reply=json.loads(event['response']['content'])
                            target=final_messages[reply['content']]
                        except (KeyError,ValueError,TypeError):
                            skips.append({'case_id':case_id,'call_id':key,'reason':'no exact decision message linkage'})
                            continue
                        if target['company_id']!=company_id or target['package_id']!=package_id:
                            continue
                        prior=[m for m in cp['agent_discussion_history'] if m['company_id']==company_id and m['package_id']==package_id
                               and m['message_id']<target['message_id']]
                        cutoff=target['message_id']
                    else:
                        prior=[m for m in cp['agent_discussion_history'] if m['company_id']==company_id and m['package_id']==package_id
                               and m['stage'] in {'bid_participation_decision','consortium_formation','consortium_failure_reconsideration','bid_document_generation'}]
                        cutoff='own completed drafting context; no owner evaluation/award or later outcomes'
                    state=load_simulation_state({'agent_discussion_history':prior})
                    records=conditions(state,company_id,package_id)
                    focus=[family for family,pattern in PATTERNS.items() if
                           (marker=='BID_DOCUMENT' if family=='cost' else marker!='BID_DOCUMENT')
                           and re.search(pattern,text) and (family=='cost' or any(re.search(pattern,r['question']) for r in records))]
                    rows.append({'case_id':case_id,'case_folder':folder.name,'project_group':group[case_id],
                         'company_id':company_id,'package_id':package_id,'marker':marker,'call_id':key,
                         'request':req['request'],'conditions':records,'source_message_cutoff':cutoff,
                         'focus_eligible':focus,'project_name':cp['project_idea']['project_name'],
                         'source_case_status':'historical archive includes degradation; not a fresh successful project'})
    return rows,skips,snapshots,group,dev,excluded_groups


def derived(window, cp, kind):
    """New synthetic test question, not a claim that the archived unknown closed."""
    company=Company(**next(c for c in cp['companies'] if c['company_id']==window['company_id']))
    package=TenderPackage(**next(p for p in cp['tender_packages'] if p['package_id']==window['package_id']))
    if kind=='verified_source_positive':
        msg=message('合成验证任务：请依据所附本包人员排期核查资料作出参与意向。',company_id=company.company_id,package_id=package.package_id,
                    verification_requests=[{'question':'本包指定岗位人员档期是否可用','required_before_submission':True}])
        # Avoid the extra prose heuristic request duplicating the explicit item.
        msg.content='合成验证任务：本包只讨论指定岗位的排期资料。'
        state=SimulationState(agent_discussion_history=[msg])
        records=conditions(state,company.company_id,package.package_id)
        assert len(records)==1
        fixture={'source_ref':'fixture:hr-schedule:'+window['case_id'],
                 'source_text':'SYNTHETIC scoped HR schedule: specified package personnel are allocated for the package period; no actual company availability is claimed.',
                 'reviewer':'synthetic:fixture-operator', 'status':'verified'}
        record_review(state,company.company_id,package.package_id,records[0]['condition_id'],**fixture)
        shared='\nAdditional synthetic fixture facts shared identically by both arms:\n'+json.dumps(fixture,ensure_ascii=False)
        oracle='The supplied synthetic HR review supports this one package-availability condition; do not invent any additional qualification, partner or financial clearance.'
    else:
        msg=message('拟以普通专项分包补充专业工作，公司保留单一责任；本任务未设置额外提交前核查条件。',
                    company_id=company.company_id,package_id=package.package_id)
        state=SimulationState(agent_discussion_history=[msg]);shared=''
        oracle='Ordinary proposed support is a plan, not an already-secured partner or automatic mandatory procurement confirmation.'
    records=conditions(state,company.company_id,package.package_id)
    original=deepcopy(window['request']['messages'])
    original[-1]['content']='MANAGEMENT_DECISION\n'+_management_prompt(state,company,package)+shared
    window.update(marker='MANAGEMENT_DECISION',request={'messages':original,'temperature':0.2},conditions=records,
                  origin='derived_synthetic_question',derivation=kind,expected_business_property=oracle,
                  derivation_note='Retains original company/package dossier; replaces historical discussion with a declared synthetic task. It does not resolve or rewrite the old run.')


def prepare():
    if TARGET.exists():
        raise RuntimeError('V2 directory already frozen; use preflight, do not replace selection after seeing results')
    TARGET.mkdir(parents=True)
    all_rows,skips,snapshots,group,dev,excluded=candidates()
    save(TARGET/'selection_protocol.json',{'at':'2026-11-08','api_request_cap_current_batch':0,
         'selection':'input-only keyword strata and SHA256 order, one window per project group; no score/rank/choice criterion',
         'focus_order':['qualification','partner','cost','personnel'],'quota_per_focus':3,
         'dev_groups':sorted(excluded),'groups_file_sha256':sha(GROUPS),'development_file_sha256':sha(DEVELOPMENT),
         'known_prior_exposure':'same archive already analyzed and partially AI-reviewed; this is confirmation after freezing, not blind external validation',
         'synthetic_supplements':'third personnel window becomes a scoped verified-source fixture; third partner window becomes ordinary-plan fixture; remain distinct original project groups',
         'visibility_scope':'Legacy recorded prompt visibility only; no claim of current native multi-organization authorization validation'})
    chosen=[];used=set(excluded)
    for family in ['qualification','partner','cost','personnel']:
        eligible=sorted([r for r in all_rows if family in r['focus_eligible']],key=lambda r:rank(r,family))
        picked=0
        for item in eligible:
            if item['project_group'] in used:
                continue
            item=deepcopy(item);item['focus']=family;picked+=1
            item['origin']='archived_decision_input'
            item['expected_business_property']={
                'qualification':'Preserve uncertainty on bidder qualifications and admissibility of borrowed experience; ordinary subcontracting does not itself establish qualification acceptance.',
                'partner':'Distinguish proposed support from counterpart acceptance/available resources; preserve accountability and open checks.',
                'cost':'Draft pricing and cost rationale must follow the declared scope/method; do not invent verified prices, approved budgets or closed resource checks.',
                'personnel':'Distinguish aggregate staff/capability from package-specific allocation and availability; retain open checks.'}[family]
            if family=='partner' and picked==3:
                derived(item,snapshots[item['case_id']],'ordinary_plan')
            if family=='personnel' and picked==3:
                derived(item,snapshots[item['case_id']],'verified_source_positive')
            item['window_id']=f'CONFIRM-{len(chosen)+1:02d}'
            original=deepcopy(item['request']['messages']);repaired=deepcopy(original)
            repaired[-1]['content']+='\n\n'+evidence_context(item['conditions'])
            item['messages']={'original':original,'repaired':repaired}
            item['input_sha256']=hashlib.sha256(json.dumps(item['messages'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            item['source_audit_sha256']=sha(ARCHIVE/item['case_folder']/'llm_calls.jsonl')
            item['purpose']='document_draft_only_no_submission' if item['marker']=='BID_DOCUMENT' else 'participation_intent_only_no_submission'
            save(TARGET/'windows'/f'{item["window_id"]}.json',item)
            chosen.append(item);used.add(item['project_group'])
            if picked==3:
                break
    save(TARGET/'candidate_index.json',[{k:r[k] for k in ('case_id','company_id','package_id','marker','call_id','project_group','focus_eligible')} for r in all_rows])
    save(TARGET/'exclusions.json',skips)
    dev_companies={w['company_id'] for w in dev}
    save(TARGET/'sample_manifest.json',[{k:w[k] for k in ('window_id','case_id','project_name','company_id','package_id','project_group',
          'focus','origin','marker','purpose','expected_business_property','input_sha256')} |
          {'company_seen_in_development':w['company_id'] in dev_companies,'window_file':f'windows/{w["window_id"]}.json'} for w in chosen])
    jobs=[{'window_id':w['window_id'],'arm':a,'repeat':r} for w in chosen for a in ['original','repaired'] for r in [1,2,3]]
    random.Random(20261108).shuffle(jobs)
    prior=read(BASE/'实验/2026-11-08_条件传递修复对照/summary.json')['provider_reported_usage']
    save(TARGET/'config.json',{'status':'frozen_inputs_and_offline_preflight_only; real calls require a separately authorized run',
         'model':'deepseek-v4-flash','temperature':0.2,'max_output_tokens_per_attempt':4096,'transport_internal_retries':0,
         'repeats_per_arm':3,'planned_first_requests':len(jobs),'planned_max_validation_retries_per_job':1,
         'proposed_total_attempt_cap':len(jobs)+24,'authorized_provider_cap':0,'authorization_required_for_future_run':True,
         'jobs':jobs,'isolation':'new run/task/cache/checkpoint per job; no original database writes or paid response reuse',
         'cost_estimate':{'basis':'prior four-window pilot, not a guarantee or billing quote',
              'estimated_total_tokens_first_pass_using_old_average':round(prior['total_tokens']/16*len(jobs)),
              'output_token_upper_bound_first_pass':len(jobs)*4096,'money':None},
         'stopping':'No requests at zero authorization; future stop at cap, code/input mismatch, unknown attempt or repeat identity; no automatic replay of unknown attempts',
         'retry_policy':'Finish all first attempts before at most 24 schema/JSON retries; preserve all first responses and all failures',
         'primary_measurement':'Common material-condition handling based on frozen case property; original schema is not penalized for absent new fields',
         'reliability':'API, JSON, validation, business refusal, conditional intent and deferred submission separate',
         'reviews':'same author-assisting AI rubric with response quotes; not independent human or blind judgments',
         'claim_scope':'10 historical decision inputs plus 2 derived synthetic questions if all quotas filled; no new full macro runs'})
    preflight()


def preflight():
    manifest=read(TARGET/'sample_manifest.json');protocol=read(TARGET/'selection_protocol.json');config=read(TARGET/'config.json')
    groups=[];checks=[]
    for row in manifest:
        w=read(TARGET/row['window_file']);groups.append(w['project_group'])
        assert w['project_group'] not in protocol['dev_groups']
        assert w['input_sha256']==hashlib.sha256(json.dumps(w['messages'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        assert w['source_audit_sha256']==sha(ARCHIVE/w['case_folder']/'llm_calls.jsonl')
        assert w['messages']['repaired'][:-1]==w['messages']['original'][:-1]
        assert w['messages']['repaired'][-1]['content'].startswith(w['messages']['original'][-1]['content'])
        records=w['conditions']
        placeholder={'decision':'bid','thoughts':'Offline shape probe only','reason':'Synthetic contract preflight',
             'content':'拟按已提供资料形成附条件意向。',
             'unresolved_condition_ids':[r['condition_id'] for r in records if r['status']!='verified'],
             'verified_condition_ids':[r['condition_id'] for r in records if r['status']=='verified'],
             'bid_assumptions':['Offline preflight placeholder, not a model decision']}
        if w['marker']=='BID_DOCUMENT':
            placeholder.update(technical_proposal='Synthetic draft',implementation_plan='Planned',quotation=100,
                schedule_commitment='Proposed',owner_control_response='Review',risk_response='Pending evidence retained',
                submission_summary='Draft only',quotation_breakdown=[{'item':'fixture','amount':100,'basis':'Declared synthetic probe'}])
            _require_bid_response(placeholder)
        elif w['marker']=='RECONSIDER_AFTER_CONSORTIUM':
            _require_reconsideration_decision(placeholder)
        else:
            require_management_decision(placeholder)
        require_condition_disposition(placeholder,records)
        checks.append({'window_id':w['window_id'],'company_id':w['company_id'],'conditions':len(records),
                       'verified_fixture_conditions':sum(r['status']=='verified' for r in records),
                       'origin':w['origin'],'passed':True})
    assert len(groups)==len(set(groups))
    assert config['authorized_provider_cap']==0 and len(config['jobs'])==len(manifest)*6
    # Reuse the durable budget and audit implementations without a transport or
    # attempted call. This planning reservation grants no model authorization.
    with tempfile.TemporaryDirectory(prefix='capstone-budget-preflight-') as td:
        store=TaskStore(run_id='planning-only',organization_ids=['host'],path=Path(td)/'budget.sqlite')
        budget=ModelCallBudget(store=store,budget_id='not-provider-authorization',max_calls=config['proposed_total_attempt_cap'])
        assert budget.reserve('proposed-first-pass',len(config['jobs']))
        assert not budget.reserve('over-limit',config['proposed_total_attempt_cap'])
        budget.finish('proposed-first-pass')
        assert budget.usage()['charged_or_reserved_calls']==0
        logger=LLMCallAuditLogger(Path(td),'OFFLINE-PREFLIGHT',SimpleNamespace())
        assert logger.path.read_text()==''
        store.close()
    save(TARGET/'preflight.json',{'window_count':len(checks),'target_count':12,'passed':len(checks),
         'project_groups_unique':True,'development_group_overlap':0,'api_calls':0,
         'ready_for_budgeted_confirmation_input':len(checks)==12,
         'company_overlap_with_development':sum(r['company_seen_in_development'] for r in manifest),
         'existing_budget_and_audit_preflight':'reservation/release, overspend rejected, no begin_attempt or request event; planning only',
         'stage_output_contract_probe':'all stage validators checked with synthetic placeholders, not model responses',
         'fixtures_and_historical_windows_not_independent_real_projects':True,'rows':checks,
         'not_validated':'No new model quality, budgeted real execution or full macro consequence tested; document windows are draft only'})
    print('V2 preflight:',len(checks),'windows, no model calls.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','preflight'])
    args=parser.parse_args()
    guard=NoProviderNetwork()
    with patch.object(socket.socket,'connect',guard.block),patch.object(socket.socket,'connect_ex',guard.block):
        globals()[args.action]()
    assert guard.attempts==0
