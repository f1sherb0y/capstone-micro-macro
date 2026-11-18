"""Freeze a small, source-bound confirmation using existing data/selection code."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import random
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_capstone_v2_5_20261109 import OUT as REPAIR, OLD, read, save, sha
from audit_enriched_retrieval_20261101 import SOURCE, PROJECT_FIELDS, FIELDS, Retrieval, read_csv
from prepare_capstone_v2_20261108 import ARCHIVE, GROUPS
from prepare_capstone_v2_2_robustness_20261108 import OUT as V22, ROLES, EXPLICIT_ROLE
from prepare_capstone_v2_3_20261109 import OUT as V23
from src.task_role_contract import role_context
from src.models import SimulationState
from src.company_grounding import company_evidence
from src.verification import conditions, evidence_context
from src.prompt_loader import load_prompt
from tests.test_verification_conditions import message

OUT = REPAIR / 'confirmation-prepared'


def baseline_module():
    spec = importlib.util.spec_from_file_location('v25_frozen_v24_baseline', REPAIR / 'baseline/src/verification.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rank(value):
    return hashlib.sha256(('capstone-v25/' + value).encode()).hexdigest()


def prepare():
    if (OUT / 'protocol.json').exists():
        raise RuntimeError('Already frozen; do not select again after seeing results')
    run_file = 'scripts/run_capstone_v2_5_20261109.py'
    if not (ROOT / run_file).exists():
        raise RuntimeError('Concrete run adapter required before freeze')
    projects = read_csv(SOURCE / 'simulation_input_projects.csv')
    companies = read_csv(SOURCE / 'simulation_input_enterprises.csv')
    groups = {r['case_id']: r['group'] for r in read(GROUPS)['assignments']}
    excluded = {groups['CASE-' + p.name.split('-')[-1]] for p in ARCHIVE.glob('case-*')}
    excluded |= {r['project_group'] for r in read(OLD / 'sample_manifest.json')}
    excluded |= {r['project_group'] for r in read(V22 / 'sample_manifest.json')}
    excluded |= {r['project_group'] for r in read(V23 / 'sample_manifest.json')}
    selected = []
    for p in sorted(projects, key=lambda p: rank(p['case_id'])):
        g = groups[p['case_id']]
        if g in excluded or g in {groups[x['case_id']] for x in selected}:
            continue
        if p['location'] not in {'澳门', '澳門'} or not p['project_name'] or not p['project_type']:
            continue
        selected.append(p)
        if len(selected) == 4:
            break
    if len(selected) != 4:
        raise RuntimeError('Insufficient distinct process-held-out dossiers; do not invent replacements')
    retrieval = Retrieval(companies)
    by_company = {c['company_id']: c for c in companies}
    previous_firms = {r['company_id'] for directory in (OLD,V22,V23) for r in read(directory / 'sample_manifest.json')}
    used = set()
    baseline = baseline_module()
    windows, manifest, targets = {}, [], []
    for i, (p, (role, label)) in enumerate(zip(selected, ROLES), 1):
        supported = set()
        for j, row in enumerate(retrieval.rows):
            scope = row['business_scope']
            if not retrieval.role_hits[label][j]['profile'] or not re.search(EXPLICIT_ROLE[role], scope, re.I):
                continue
            if role == 'contractor' and not re.search(r'建筑业|建築業|construction', row['industry'], re.I):
                continue
            if role == 'designer' and not re.search(r'建筑设计|建築設計|工程设计|工程設計|规划设计|規劃設計', scope):
                continue
            if role == 'supplier' and not re.search(r'生产|生產|制造|製造|销售|銷售|分销|分銷|供货|供貨|manufactur', scope, re.I):
                continue
            supported.add(row['company_id'])
        firm_id = next((cid for cid in retrieval.rank(p)[(label, 'enriched_topic')] if cid in supported and cid not in used), None)
        if firm_id is None:
            raise RuntimeError('No source-supported firm for role: ' + role)
        used.add(firm_id)
        firm = by_company[firm_id]
        for variant in ('full', 'missing_core'):
            wid, package_id = f'SOURCE-{i:02d}-{variant}', f'SOURCE-{i:02d}'
            c = {k: firm.get(k, '') for k in FIELDS}
            if variant == 'missing_core':
                for key in ('business_scope', 'industry', 'certifications', 'staff_scale', 'talent_structure'):
                    c[key] = ''
            questions = ([('本包供应商渠道审核是否通过', False), ('外部支持是否接受保修与质量文档要求', False)]
                         if role == 'supplier' else [('本包指定岗位人员档期是否可用', True)])
            if role == 'contractor':
                questions.append(('本包资格证明是否满足提交要求', True))
            state = SimulationState(agent_discussion_history=[message('SYNTHETIC: ordinary support is a proposed delivery plan.',
                company_id=firm_id, package_id=package_id,
                verification_requests=[{'question': q, 'required_before_submission': b} for q, b in questions])])
            records = conditions(state, firm_id, package_id)
            facts = {'real_input_dossier': {'project': {k: p.get(k, '') for k in PROJECT_FIELDS}, 'company': c},
                     'synthetic_task_contract': {'role': role, 'currency': 'MOP',
                        'scope': 'Controlled role participation/pricing scenario, not an actual tender package.',
                        'ordinary_support': 'Proposed plan only; no accepted counterparty commitment.',
                        'not_supplied': ['actual staff allocation', 'supplier quotation', 'specific product catalogue',
                                         'inventory/local-team records', 'historical procurement costs'],
                        'instruction': 'Use only supplied facts. Unknown is neither capable nor incapable. Proposals are allowed; no submission or macro action is executed.'}}
            marker = 'BID_DOCUMENT' if role == 'supplier' else 'MANAGEMENT_DECISION'
            user = marker + '\nShared facts:\n' + json.dumps(facts, ensure_ascii=False)
            user += '\nReturn a draft or intention only. Unsupported quantities/prices must be provisional, in MOP, with item sums consistent.\n'
            system = load_prompt('company', 'bid_document.md' if role == 'supplier' else 'management_decision.md')
            sources = company_evidence(c)
            messages = {
                'v2_4': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user + baseline.evidence_context(records, company_sources=sources, narrative_grounding=True)}],
                'v2_5': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user + evidence_context(records, company_sources=sources, narrative_grounding=True) + role_context(role)}]}
            windows[wid] = {'window_id': wid, 'base_unit': f'SOURCE-{i:02d}', 'variant': variant,
                'case_id': p['case_id'], 'project_group': groups[p['case_id']], 'company_id': firm_id,
                'package_id': package_id, 'role': role, 'marker': marker, 'facts': facts,
                'conditions': records, 'company_evidence': sources, 'messages': messages}
            targets.append({'window_id': wid,
                'core': 'Retain unknown personnel/eligibility/audit/acceptance states and source limits; no unsupported existing or absent competence, offices/teams, inventory, specific own products, actual received quotes or historical cost records. Proposals and justified refusals are allowed.',
                'missing_core': 'Removed capability fields remain unknown. A company name, requested role, address, staff count or brand impression does not establish capability or incapability.',
                'full': 'Scope text supports only its stated business direction, not licenses, actual dedicated resources or a detailed catalogue.',
                'numeric': 'Finite JSON values, Decimal item sum within MOP1 for pricing; no market-price oracle.',
                'task_role': 'Current controlled role outranks historical project title/EPC label. Common co-primary success requires source target AND correct role AND consistent prerequisite flags; report each separately. Missing new task_role field in V2.4 is not a common-content penalty.',
                'scoring': 'Common outward-content criteria; no baseline penalty for absence of new host narrative report. Structured reference correctness is separate from narrative faithfulness.',
                'usefulness': 'Keep a substantive, conditional strategy or delivery proposal; empty text, blanket refusal or unnecessary gates are not automatic successes.',
                'boundary': 'Explicit prose submission prerequisites must agree with structured request flags; keep ordinary support optional unless independently justified.',
                'retry': 'Score all firsts and last responses separately; reference correctness, limited guard acceptance, content review needed and semantic content quality are separate.',
                'oracle': 'Author-assisting AI frozen source/property criteria, unblinded and nonindependent;4 dossier groups, not32 independent projects.'})
        manifest.append({'base_unit': f'SOURCE-{i:02d}', 'case_id': p['case_id'], 'project_name': p['project_name'],
            'project_group': groups[p['case_id']], 'company_id': firm_id, 'company_name': firm['company_name'], 'role': role,
            'source_business_scope': firm['business_scope'], 'source_industry': firm['industry'],
            'company_overlap_with_previous12_role_pairings': firm_id in previous_firms,
            'scope_limit': 'Profile evidence supports task construction, not actual tender eligibility, resources or the specific historical company-project relationship.'})
    save(OUT / 'windows.json', windows)
    save(OUT / 'targets.json', targets)
    save(OUT / 'sample_manifest.json', manifest)
    jobs = [{'window_id': wid, 'arm': arm, 'repeat': repeat}
            for wid in windows for arm in ('v2_4', 'v2_5') for repeat in (1, 2)]
    random.Random(2026110905).shuffle(jobs)
    code = ['src/verification.py', 'src/company_grounding.py', 'src/company_narrative.py', 'src/task_role_contract.py', 'src/response_repair.py', 'src/agent_runtime.py', 'src/models.py', 'src/stages/participation.py', 'src/stages/reconsideration.py', 'src/stages/bid_documents.py', 'src/prompt_contracts.py', 'src/llm_client.py',
            'src/coordination/model_budget.py', 'src/coordination/tasks.py', 'src/run_audit.py', run_file,
            'scripts/prepare_capstone_v2_5_20261109.py']
    save(OUT / 'protocol.json', {'version': 'role-context-final.v2.5.1', 'model': 'deepseek-v4-flash',
        'temperature': .2, 'concurrency': 2, 'max_output_tokens': 4096, 'first_requests': 32,
        'max_calls_proposed': 40, 'max_final_retries': 8, 'provider_calls_authorized': 0,
        'jobs': jobs, 'windows_sha256': sha(OUT / 'windows.json'), 'targets_sha256': sha(OUT / 'targets.json'),
        'manifest_sha256': sha(OUT / 'sample_manifest.json'), 'code_sha256': {f: sha(ROOT / f) for f in code},
        'baseline_verification_sha256': sha(REPAIR / 'baseline/src/verification.py'),
        'baseline_narrative_sha256': sha(REPAIR / 'baseline/src/company_narrative.py'),
        'excluded_process_groups': sorted(excluded), 'group_file_sha256': sha(GROUPS),
        'source_sha256': {str((SOURCE / n).relative_to(ROOT)): sha(SOURCE / n) for n in ['simulation_input_projects.csv', 'simulation_input_enterprises.csv']},
        'selection': 'Existing input-only retrieval and explicit role-scope checks, stable project hash, no model score/winner labels. Excludes28 process-case groups,4 V2.2 robustness groups,4 V2.3 source-binding groups and4 V2.4 role-context development groups.',
        'comparison': 'Captured V2.4 versus V2.5 current-role contract and bounded context/source-paraphrase package. Both arms have the same supplied dossier/source facts. Not a pure prompt ablation; both arms retain targeted-repair limits; candidate changes outside error paths require review. Limited checks are not semantic truth.',
        'primary_unit': '4 source groups,8 controlled full/missing scenarios,2 repeats per arm; shared dataset, not external blind validation.',
        'retry': 'All first responses before at most one retry per eligible invalid JSON/contract final; semantic-review-needed cases and provider failures not retried. Candidate retry receives original raw answer and exact error; unexpected content/strategy drift is held for review, not accepted or retried again.',
        'stop': 'New independent budget, cap/unknown attempt/fatal provider/input mismatch stop; no automatic resume. No historical budget (including prior unused1) inherited; explicit independent new authorization required.',
        'macro_execution': False, 'paid_judge': False, 'paper_and_figures': False})
    print(json.dumps({'source_groups': 4, 'tasks': 8, 'first_calls': 32, 'proposed_cap': 40, 'authorized_now': 0, 'manifest': manifest}, ensure_ascii=False))


if __name__ == '__main__':
    prepare()
