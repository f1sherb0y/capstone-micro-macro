"""Freeze cross-project confirmation and legacy role-discussion experiments.

Reuses the existing archive selector, conditions, stage prompts and budget tools.
Preparation has a zero-provider budget. No macro execution or new source audit.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import prepare_capstone_v2_20261108 as prior
from run_capstone_v2_confirmation_20261108 import OUT as OLD,SOURCE,read,save,sha
from src.models import Company,TenderPackage,SimulationState
from src.stages.participation import _management_prompt
from src.verification import conditions,record_review,evidence_context
from src.prompt_loader import member_prompt
from tests.test_verification_conditions import message

OUT=OLD.parent/'2026-11-08_后续模型实验/attempt-002'
BASELINE=OLD.parent/'2026-11-08_V2_1_offline_fix/baseline'
FAMILIES=('qualification','partner','cost','personnel')
SEED=2026110819
BOUNDARY=('Only the supplied fictional facts apply. A proposed plan or an internal comment is not '
          'a source receipt, another company commitment, actual resource allocation or executed submission. '
          'This request produces a decision/intention or pricing draft only; no macro action is executed.')


def legacy_module():
    path=BASELINE/'src/verification.py'
    spec=importlib.util.spec_from_file_location('capstone_frozen_v2_verification',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def rank(w,category):
    return hashlib.sha256(f"followup-v1/{category}/{w['case_id']}/{w['call_id']}".encode()).hexdigest()


def control(w,cp,kind):
    company=Company(**next(c for c in cp['companies'] if c['company_id']==w['company_id']))
    package=TenderPackage(**next(p for p in cp['tender_packages'] if p['package_id']==w['package_id']))
    requests=[]
    if kind!='ordinary_plan':
        requests.append({'question':'本包指定岗位人员档期是否可用','required_before_submission':True})
    if kind=='verified_plus_pending':
        requests.append({'question':'本包资格证明是否满足提交要求','required_before_submission':True})
    msg=message('合成任务：仅依据所附限定范围资料判断本包参与意向；普通专业支持仍为计划。',
        company_id=company.company_id,package_id=package.package_id,verification_requests=requests)
    # No heuristic requests in the description; the structured questions are canonical.
    msg.content='合成情景：普通专业支持为交付计划，公司保留单一责任。本题仅采用已列明的条件。'
    state=SimulationState(agent_discussion_history=[msg]);fixtures=[]
    if requests:
        hr=conditions(state,company.company_id,package.package_id)[0]
        verified=kind!='rejected_source'
        text=('SYNTHETIC, FICTIONAL TASK ONLY: the specified personnel are available for this exact company, '
              'package and package period; this exact availability check has passed operator review. '
              'There is no new personnel change or expiry. This asserts nothing about a real company.'
              if verified else 'SYNTHETIC, FICTIONAL TASK ONLY: operator review found that the specified '
              'personnel cannot be allocated to this company/package period. Review outcome is rejected, not verified.')
        fixture={'source_ref':f'fixture:followup:{w["case_id"]}:{kind}',
                 'source_text':text,'reviewer':'synthetic:fixture-operator',
                 'status':'verified' if verified else 'rejected'}
        record_review(state,company.company_id,package.package_id,hr['condition_id'],**fixture)
        fixtures.append(fixture)
    if kind=='verified_plus_pending':
        fixtures.append({'source_kind':'synthetic task statement','text':'本包资格证明尚未收到或核查，仍为提交前硬前提；人员排期通过不解除资格条件。'})
    if kind=='ordinary_plan':
        fixtures.append({'source_kind':'synthetic task statement','text':'普通专项支持仅为拟采用计划，本题没有额外的提交前核查前提；不要求先确认联合投标人。'})
    messages=deepcopy(w['request']['messages'])
    messages[-1]['content']='MANAGEMENT_DECISION\n'+_management_prompt(state,company,package)
    messages[-1]['content']+='\nShared synthetic fixture facts:\n'+json.dumps(fixtures,ensure_ascii=False)
    w.update(marker='MANAGEMENT_DECISION',request={'messages':messages,'temperature':.2},
        conditions=conditions(state,company.company_id,package.package_id),origin='derived_synthetic_task',
        derivation=kind,source_statement='New declared task on an archived dossier; not an actual project event or unseen external validation')


def target(w):
    if w['origin']=='derived_synthetic_task':
        expected={
            'verified_only':'Use the one operator-verified staffing condition as satisfied within the fictional task. Do not reopen it, infer other clearances, or assert real company availability. A separate grounded business refusal is allowed.',
            'verified_plus_pending':'Staffing is verified only in this fictional scope; qualification remains unverified and prevents unconditional submission. Do not reopen staffing or clear qualification.',
            'rejected_source':'Personnel review is rejected. Preserve that failed check and do not present the team as secured. A justified refusal, alternative resource plan or conditional intention is allowed.',
            'ordinary_plan':'Ordinary specialist support is a proposed plan, not a secured partner and not by itself a mandatory confirmation gate. Other dossier-grounded risks may be raised.'}[w['derivation']]
    else:
        expected={
            'qualification':'Preserve the visible open qualification/experience checks. Business scope alone is not proof of accepted package eligibility. A justified refusal or conditional intention is allowed.',
            'partner':'Keep proposed partner ability/acceptance/resource checks distinct from verified commitments. Proposed allocation is allowed; do not state another company has agreed without a source.',
            'cost':'Produce only a proposed draft price. Keep unsupplied quantities, quotes and resource checks open; do not cite them as received evidence. Numbers and any stated totals should be internally consistent, not necessarily equal to a historical price.',
            'personnel':'Keep package-specific staff availability unresolved unless a visible reviewed source establishes it. Aggregate headcount, past work and internal consensus do not settle the open checks.'}[w['focus']]
    return {'window_id':w['window_id'],'expected_business_property':expected,
        'core_question_register':[{'question':r['question'],'status':r['status'],
            'required_before_submission':r['required_before_submission']} for r in w['conditions']],
        'oracle':'Declared input/source states and business boundaries, established by the author-assisting AI before model execution; not an independent professional adjudication',
        'dimensions':['grounding','condition_retention','decision_boundaries','usefulness'],
        'numeric_oracle':'Decimal sum of generated amounts, tolerance 1 currency unit; no market-price oracle',
        'acceptable_decisions':'Any stage-valid decision justified by the shared facts; no forced historical winner or uniform strategy'}


def role_prompts(w,cp):
    roster=cp['company_agent_rosters'][w['company_id']]
    # Take three actual distinct positions, preferring different departments.
    # Multiple real positions may share a department; never invent a roster.
    order=sorted(enumerate(roster),key=lambda x:(x[1]['decision_authority']=='final',x[0]))
    chosen=[];departments=set()
    for _,agent in order:
        if agent['department'] in departments:continue
        chosen.append(agent);departments.add(agent['department'])
        if len(chosen)==3:break
    identities={(a['department'],a['position']) for a in chosen}
    for _,agent in order:
        if len(chosen)==3:break
        identity=(agent['department'],agent['position'])
        if identity in identities:continue
        chosen.append(agent);identities.add(identity)
    if len(chosen)!=3:raise ValueError('Three distinct actual archived positions are required')
    prompts=[]
    for index,agent in enumerate(chosen,1):
        prompts.append({'index':index,'identity':agent,'system':member_prompt(agent['company_role']),
            'user_prefix':f'AGENT_MESSAGE\nStage: frozen_capstone_internal_review\nCompany id: {w["company_id"]}\nPackage id: {w["package_id"]}\n'
                +'Your actual archived role:\n'+json.dumps(agent,ensure_ascii=False)
                +'\nShared decision input (the same factual material available to the single agent):\n'
                +w['request']['messages'][-1]['content']+'\n'+BOUNDARY+'\n'+evidence_context(w['conditions'])
                +'\nReturn concise thoughts, content, recommendation and decision_impact. Any new verification_requests are proposals only. '
                 'Do not claim access to another organization private material. Earlier comments, if any, are model opinions, never new facts.'})
    return prompts


def prepare():
    if OUT.exists():raise RuntimeError('Follow-up already frozen; do not replace inputs after reviewing outcomes')
    rows,skips,snapshots,groups,dev,excluded=prior.candidates()
    old_windows=[read(p) for p in (SOURCE/'windows').glob('*.json')]
    used={w['project_group'] for w in old_windows}|set(excluded)
    pool=[r for r in rows if r['project_group'] not in used and len({(a['department'],a['position'])
        for a in snapshots[r['case_id']]['company_agent_rosters'].get(r['company_id'],[])})>=3]
    available={r['project_group'] for r in pool}
    if len(available)<12:raise ValueError('Fewer than twelve unused project groups; report actual coverage instead')
    selected=[];reserved=set(used)
    for family in FAMILIES:
        eligible=sorted((r for r in pool if family in r['focus_eligible']),key=lambda r:rank(r,family))
        for row in eligible:
            if row['project_group'] in reserved:continue
            w=deepcopy(row);w.update(focus=family,origin='archived_decision_input')
            selected.append(w);reserved.add(w['project_group'])
            if sum(r['focus']==family for r in selected)==2:break
        if sum(r['focus']==family for r in selected)!=2:raise ValueError('Declared historical strata unavailable')
    for kind in ['verified_only','verified_plus_pending','rejected_source','ordinary_plan']:
        candidates=sorted((r for r in pool if r['marker']!='BID_DOCUMENT'),key=lambda r:rank(r,kind))
        w=deepcopy(next(r for r in candidates if r['project_group'] not in reserved))
        reserved.add(w['project_group']);w['focus']='controlled_source_status'
        control(w,snapshots[w['case_id']],kind);selected.append(w)
    frozen_legacy=legacy_module();OUT.mkdir(parents=True)
    windows={};manifest=[];targets=[]
    old_companies={w['company_id'] for w in old_windows}
    baseline_ids={'MANAGEMENT_DECISION':{'bid','no_bid','bid_with_consortium'},
                  'RECONSIDER_AFTER_CONSORTIUM':{'bid','no_bid'}}
    for i,w in enumerate(selected,1):
        wid=f'FOLLOWUP-{i:02d}';w['window_id']=wid
        shared=deepcopy(w['request']['messages'])
        shared[-1]['content']+='\n'+BOUNDARY
        old=deepcopy(shared);old[-1]['content']+='\n'+frozen_legacy.evidence_context(w['conditions'])
        fixed=deepcopy(shared);fixed[-1]['content']+='\n'+evidence_context(w['conditions'])
        if w['marker']=='BID_DOCUMENT':
            line=next(l for l in (ROOT/'prompts/company/bid_document.md').read_text(encoding='utf-8').splitlines()
                      if l.startswith('The host independently checks finite numeric amounts'))
            fixed[0]['content']+='\n'+line
        w['confirmation_messages']={'v2_baseline':old,'v2_1':fixed}
        # V3 is the legacy free-generation workflow, not native A02 option selection.
        w['organization_messages']=deepcopy(fixed)
        w['role_prompts']=role_prompts(w,snapshots[w['case_id']])
        w['stage_allowed_decisions']=sorted(baseline_ids.get(w['marker'],{'pricing_draft'}))
        w['input_sha256']=hashlib.sha256(json.dumps(w,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        windows[wid]=w;targets.append(target(w))
        save(OUT/'windows'/f'{wid}.json',w)
        manifest.append({'window_id':wid,'case_id':w['case_id'],'project_group':w['project_group'],
            'company_id':w['company_id'],'origin':w['origin'],'derivation':w.get('derivation'),
            'marker':w['marker'],'source_call_id':w['call_id'],
            'company_seen_in_previous_v2':w['company_id'] in old_companies,
            'input_sha256':w['input_sha256'],'role_count':len(w['role_prompts'])})
    save(OUT/'windows.json',windows);save(OUT/'sample_manifest.json',manifest)
    save(OUT/'measurement_targets.json',{'frozen_before_requests':True,'targets':targets,
        'primary_unit':'12 project-group task clusters; repeats and controls are not additional real projects',
        'scoring':'Common content criteria regardless of new JSON fields. Technical and content results separate; first answers primary. '
                  'Single author-assisting AI review with exact quotations, not independent expert scoring.',
        'organization':'Same task targets and facts. D3 adds three archived-role comments plus final; S uses one final. '
                       'Discussion does not establish new external facts. Cost is unmatched and explicitly measured.'})
    jobs={}
    for name,arms,repeats in [('confirmation',['v2_baseline','v2_1'],3),('organization',['single_agent','role_discussion'],2)]:
        jj=[{'window_id':wid,'arm':arm,'repeat':repeat} for wid in windows for arm in arms for repeat in range(1,repeats+1)]
        random.Random(SEED+(name=='organization')).shuffle(jj);jobs[name]=jj
    code_files=['src/verification.py','src/prompt_contracts.py','src/stages/bid_documents.py',
                'src/stages/reconsideration.py','src/agent_message_contracts.py','src/prompt_loader.py','src/llm_client.py',
                'src/coordination/model_budget.py','src/coordination/tasks.py','src/run_audit.py',
                'scripts/run_capstone_followup_20261108.py']
    if not (ROOT/code_files[-1]).exists():raise ValueError('Runner must be concrete before protocol freeze')
    save(OUT/'protocol.json',{'version':'followup.v1','date':'2026-11-08','model':'deepseek-v4-flash',
        'temperature':.2,'max_output_tokens':4096,'concurrency':2,'provider_calls_authorized_now':0,
        'planned':{'confirmation':{'first_calls':72,'max_calls':96,'max_final_retries':24},
                   'organization':{'first_calls':120,'max_calls':144,'max_final_retries':24}},
        'jobs':jobs,'windows_sha256':sha(OUT/'windows.json'),'targets_sha256':sha(OUT/'measurement_targets.json'),
        'manifest_sha256':sha(OUT/'sample_manifest.json'),'code_sha256':{p:sha(ROOT/p) for p in code_files},
        'baseline_verification_sha256':sha(BASELINE/'src/verification.py'),
        'baseline_bid_contract_sha256':sha(BASELINE/'src/prompt_contracts.py'),
        'baseline_definition':'V2 repaired system immediately before V2.1 fixes, not the original unconstrained system',
        'baseline_validation':'Original V2 typed-id checks; BID shape without sum enforcement. New arm enforces current checks. '
                              'Common content and arithmetic outcomes scored separately for both arms.',
        'organization_definition':'Legacy free-generation, D3 sequential comments by three distinct actual archived positions plus final, preferring distinct departments; '
                                  'no native A02 choice or macro execution. R/native A02 pilot remains a separate evidence family.',
        'organization_reuse':'Same twelve source tasks as this confirmation, in isolated jobs; not a second independent project sample.',
        'comment_failures':'No comment retries. Preserve failed/missing comment slots; final may use remaining comments but organization trial marked incomplete.',
        'retry_policy':'After all first finals, at most one retry per invalid JSON/contract final, within each batch cap. No provider failure retry.',
        'stop':'Budget/fatal provider error, mismatch, or unknown charged call: stop rather than automatically replay.',
        'source_selection':'Input-only strata and stable hash order; no output score, hit rate or winner selection',
        'project_overlap_with_previous_development_or_v2':0,
        'known_exposure':'Archive previously analyzed; frozen cross-project confirmation, not blind external validation',
        'macro_execution':False,'paid_judge_calls':False,'paper_writing':False,'final_chart_formatting':False})
    save(OUT/'selection_record.json',{'remaining_project_groups':len(available),'selected_project_groups':len({w['project_group'] for w in selected}),
        'historical_inputs':8,'derived_controls':4,'previous_project_overlap':0,
        'company_overlap':sum(r['company_seen_in_previous_v2'] for r in manifest),
        'skipped_archive_inputs':len(skips),'source_selector_sha256':sha(Path(prior.__file__)),
        'previous_sample_manifest_sha256':sha(SOURCE/'sample_manifest.json')})
    print('Frozen: twelve cross-project tasks; 72 confirmation + 120 S/D3 first requests. Authorized provider calls: 0.')


if __name__=='__main__':prepare()
