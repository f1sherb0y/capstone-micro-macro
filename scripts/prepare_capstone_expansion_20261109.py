"""Prepare a stratified24-project expansion without running any model.

Reuse existing retrieval, grouping, prompts, conditions and source contracts.
Keep the released V2.4/V2.5 code fixed; selection never reads response scores.
"""
from collections import Counter,defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from prepare_capstone_v2_5_20261109 import OUT as PREVIOUS,REPAIR,GROUPS,SOURCE,ROLES,EXPLICIT_ROLE,read,save,sha,read_csv,Retrieval,FIELDS,PROJECT_FIELDS,baseline_module
from prepare_capstone_v2_2_robustness_20261108 import OUT as V22
from prepare_capstone_v2_3_20261109 import OUT as V23
from validate_capstone_v2_5_20261109 import OLD as V24
from src.company_grounding import company_evidence
from src.models import SimulationState
from src.verification import conditions,evidence_context
from src.task_role_contract import role_context
from src.prompt_loader import load_prompt
from tests.test_verification_conditions import message

OUT=ROOT/'Capstone报告/验证体系/实验/2026-11-09_24项目扩样验证'
CAP=240


def rank(value):return hashlib.sha256(('capstone-expansion-24/20261109/'+value).encode()).hexdigest()


def prepare():
    assert not OUT.exists(),'Do not replace frozen expansion selection'
    runner='scripts/run_capstone_expansion_20261109.py'
    assert (ROOT/runner).exists(),'Concrete runner required before freeze'
    oldp=read(PREVIOUS/'protocol.json');groups={r['case_id']:r['group'] for r in read(GROUPS)['assignments']}
    projects=read_csv(SOURCE/'simulation_input_projects.csv');firms=read_csv(SOURCE/'simulation_input_enterprises.csv')
    excluded=set(oldp['excluded_process_groups'])|{r['project_group'] for r in read(PREVIOUS/'sample_manifest.json')}
    eligible=[p for p in projects if groups[p['case_id']] not in excluded and p['project_name'] and p['project_type'] and p['location'] in {'澳门','澳門'}]
    buckets=defaultdict(list)
    for p in sorted(eligible,key=lambda x:rank(x['case_id'])):buckets[p['project_type']].append(p)
    eligible_groups={groups[p['case_id']] for p in eligible}
    selected=[];used_groups=set();types=sorted(buckets,key=rank)
    while len(selected)<24:
        progress=False
        for typ in types:
            while buckets[typ] and groups[buckets[typ][0]['case_id']] in used_groups:buckets[typ].pop(0)
            if buckets[typ]:
                p=buckets[typ].pop(0);selected.append(p);used_groups.add(groups[p['case_id']]);progress=True
                if len(selected)==24:break
        if not progress:break
    assert len(selected)==24,'Insufficient distinct supported groups; do not rename projects'
    retrieval=Retrieval(firms);by_id={c['company_id']:c for c in firms};supported={}
    for role,label in ROLES:
        pool=set()
        for j,c in enumerate(retrieval.rows):
            scope=c['business_scope']
            if not retrieval.role_hits[label][j]['profile'] or not re.search(EXPLICIT_ROLE[role],scope,re.I):continue
            if role=='contractor' and not re.search(r'建筑业|建築業|construction',c['industry'],re.I):continue
            if role=='designer' and not re.search(r'建筑设计|建築設計|工程设计|工程設計|规划设计|規劃設計',scope):continue
            if role=='supplier' and not re.search(r'生产|生產|制造|製造|销售|銷售|分销|分銷|供货|供貨|manufactur',scope,re.I):continue
            pool.add(c['company_id'])
        supported[role]=pool
    seen_firms={r['company_id'] for directory in (V22,V23,V24,PREVIOUS) for r in read(directory/'sample_manifest.json')}
    baseline=baseline_module();roles=Counter();type_roles=Counter();used_firms=set();windows={};manifest=[];targets=[]
    common=deepcopy(read(PREVIOUS/'targets.json')[0]);common.pop('window_id')
    for index,p in enumerate(selected,1):
        available=[r for r in ROLES if roles[r[0]]<6]
        role,label=min(available,key=lambda r:(roles[r[0]],type_roles[(p['project_type'],r[0])],rank(p['case_id']+'/'+r[0])))
        role_ranking=retrieval.rank(p)[(label,'enriched_topic')]
        cid=next((c for c in role_ranking if c in supported[role] and c not in used_firms),None)
        assert cid is not None,('No role-supported unused enterprise',p['case_id'],role)
        company=by_id[cid];used_firms.add(cid);roles[role]+=1;type_roles[(p['project_type'],role)]+=1
        unit=f'EXPAND-{index:02d}'
        for variant in ('full','missing_core'):
            wid=unit+'-'+variant;c={k:company.get(k,'') for k in FIELDS}
            if variant=='missing_core':
                for k in ('business_scope','industry','certifications','staff_scale','talent_structure'):c[k]=''
            questions=([('本包供应商渠道审核是否通过',False),('外部支持是否接受保修与质量文档要求',False)] if role=='supplier' else [('本包指定岗位人员档期是否可用',True)])
            if role=='contractor':questions.append(('本包资格证明是否满足提交要求',True))
            state=SimulationState(agent_discussion_history=[message('SYNTHETIC: ordinary support is a proposed delivery plan.',company_id=cid,package_id=unit,
              verification_requests=[{'question':q,'required_before_submission':b} for q,b in questions])])
            records=conditions(state,cid,unit)
            facts={'real_input_dossier':{'project':{k:p.get(k,'') for k in PROJECT_FIELDS},'company':c},
              'synthetic_task_contract':{'role':role,'currency':'MOP','scope':'Controlled role participation/pricing scenario, not an actual tender package.',
                'ordinary_support':'Proposed plan only; no accepted counterparty commitment.',
                'not_supplied':['actual staff allocation','supplier quotation','specific product catalogue','inventory/local-team records','historical procurement costs'],
                'instruction':'Use only supplied facts. Unknown is neither capable nor incapable. Proposals are allowed; no submission or macro action is executed.'}}
            marker='BID_DOCUMENT' if role=='supplier' else 'MANAGEMENT_DECISION'
            user=marker+'\nShared facts:\n'+json.dumps(facts,ensure_ascii=False)+'\nReturn a draft or intention only. Unsupported quantities/prices must be provisional, in MOP, with item sums consistent.\n'
            system=load_prompt('company','bid_document.md' if role=='supplier' else 'management_decision.md');sources=company_evidence(c)
            messages={'v2_4':[{'role':'system','content':system},{'role':'user','content':user+baseline.evidence_context(records,company_sources=sources,narrative_grounding=True)}],
              'v2_5':[{'role':'system','content':system},{'role':'user','content':user+evidence_context(records,company_sources=sources,narrative_grounding=True)+role_context(role)}]}
            windows[wid]={'window_id':wid,'base_unit':unit,'variant':variant,'case_id':p['case_id'],'project_group':groups[p['case_id']],
              'company_id':cid,'package_id':unit,'role':role,'marker':marker,'facts':facts,'conditions':records,'company_evidence':sources,'messages':messages}
            target={'window_id':wid,**deepcopy(common)}
            target['oracle']='Author-assisting AI frozen source/property criteria, unblinded and nonindependent;24 source project groups, not192 independent projects.'
            target['additional_annotation_plan']={
              'M02':'List outward capability/status assertions, quotes, supplied source or unknown. Classify supported, unsupported-positive, unsupported-negative, explicit-proposal, or ambiguous; response-level source target is not a claim-level hallucination rate.',
              'M07':'Enumerate distinct explicit pre-submission prerequisites in outward text, compare semantic request/flag matches, separately original conditions and newly introduced conditions. No prerequisite means N/A for new-prerequisite coverage, not100%.',
              'M09':'Record concrete duty/steps/quality-control and conditional resources, or evidence-based refusal. Length and disclaimers are not a quality score.',
              'sensitivity':'Primary strict and predeclared ambiguous readings both retained. Registration-address relabeling versus office field and shorthand existing specialization flagged explicitly; role-name shorthand treated leniently only in sensitivity. Same rule for both arms.',
              'exclusions':'No organizational discussion contribution, actual resource verification, formal submission/macro effect, market-price accuracy, or numeric probability calibration in these draft tasks.'}
            targets.append(target)
        manifest.append({'base_unit':unit,'case_id':p['case_id'],'project_group':groups[p['case_id']],'project_name':p['project_name'],'project_type':p['project_type'],
          'location':p['location'],'role':role,'company_id':cid,'company_name':company['company_name'],'company_overlap_with_previous16_role_pairings':cid in seen_firms,
          'source_business_scope':company['business_scope'],'source_industry':company['industry'],
          'scope_limit':'Input-supported controlled role, not proof of historical collaboration, current eligibility, allocation or actual project tender.'})
    assert set(roles.values())=={6} and len(used_groups)==24 and len(used_firms)==24
    jobs=[{'window_id':wid,'arm':arm,'repeat':rep} for wid in windows for arm in ('v2_4','v2_5') for rep in (1,2)]
    random.Random(2026110924).shuffle(jobs)
    save(OUT/'windows.json',windows);save(OUT/'targets.json',targets);save(OUT/'sample_manifest.json',manifest)
    code={**oldp['code_sha256'],runner:sha(ROOT/runner),'scripts/prepare_capstone_expansion_20261109.py':sha(Path(__file__))}
    save(OUT/'protocol.json',{'version':'capstone-fixed-v24-v25-expanded24.v1','model':oldp['model'],'temperature':oldp['temperature'],
      'concurrency':2,'max_output_tokens':4096,'first_requests':192,'max_calls_proposed':CAP,'max_final_retries':48,'provider_calls_authorized':0,
      'jobs':jobs,'windows_sha256':sha(OUT/'windows.json'),'targets_sha256':sha(OUT/'targets.json'),'manifest_sha256':sha(OUT/'sample_manifest.json'),
      'code_sha256':code,'baseline_verification_sha256':oldp['baseline_verification_sha256'],'baseline_narrative_sha256':oldp['baseline_narrative_sha256'],
      'group_file_sha256':sha(GROUPS),'source_sha256':oldp['source_sha256'],'prior_release_manifest_sha256':sha(PREVIOUS/'live_release_manifest.json'),
      'excluded_process_groups':sorted(excluded),'selection':'Input-only, balanced project-type cycling over eligible Macau groups; deterministic role quotas6 each, role-scope support,24 distinct companies. No outcome-score selection.',
      'comparison':'Same released V2.4 versus V2.5 mechanisms and same external facts per task; no new production repair. Confirmation expansion, not a V2.6 version.',
      'primary_unit':'24 project groups,48 controlled full/missing tasks,2 repeats per arm. One role per source project,6 projects per role; not24 full-project simulations.',
      'scope':'Micro draft/participation/pricing validation only. No formal macro submission, full lifecycle, paid judge or thesis/chart generation.',
      'retry':'All192 firsts before at most48 single retries,1 per eligible task. No retries for review_required or provider failure; preserve firsts, originals and path-drift review.',
      'stop':'Independent240 cap only after new explicit user authorization. Unknown/fatal provider/evaluator state halts, no automatic replay/resume. No prior budget inherited.',
      'macro_execution':False,'paid_judge':False,'paper_and_figures':False})
    save(OUT/'selection_summary.json',{'all_project_rows':len(projects),'all_enterprises':len(firms),'all_project_groups':len(set(groups.values())),
      'excluded_groups':len(excluded),'remaining_eligible_macau_groups':len(eligible_groups),'remaining_macau_rows':len(eligible),
      'eligible_types':dict(Counter(p['project_type'] for p in eligible)),'selected_types':dict(Counter(m['project_type'] for m in manifest)),
      'roles':dict(roles),'distinct_selected_companies':24,'supported_company_pool':{k:len(v) for k,v in supported.items()},
      'company_overlap_with_previous16_role_pairings':sum(m['company_overlap_with_previous16_role_pairings'] for m in manifest),
      'new_project_group_overlap':len(used_groups&excluded),'provider_requests':0,
      'known_dataset_limit':'Existing352-project corpus has already been analysed; isolated from recorded development groups, not externally unseen or blind.'})
    print(json.dumps({'groups':24,'tasks':48,'first_calls':192,'proposed_cap':CAP,'roles':dict(roles),
      'types':dict(Counter(m['project_type'] for m in manifest)),'calls_now':0},ensure_ascii=False))


if __name__=='__main__':prepare()
