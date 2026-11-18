"""Freeze new process-task project groups from existing input-only CSVs.

Real dossier fields and deliberately synthetic task/review facts stay separate.
No historical winner labels, generated answers or new source-audit pipeline.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_capstone_v2_2_20261108 import OUT as REPAIR, OLD, read, save, sha
from audit_enriched_retrieval_20261101 import SOURCE, PROJECT_FIELDS, FIELDS, Retrieval, read_csv
from prepare_capstone_v2_20261108 import ARCHIVE, GROUPS
from src.models import SimulationState
from src.prompt_loader import load_prompt
from src.verification import conditions, record_review, evidence_context
from tests.test_verification_conditions import message

OUT = REPAIR / 'robustness-prepared/attempt-003'
ROLES = [('supervisor', '监理'), ('supplier', '供应/制造'),
         ('contractor', '施工/总承包'), ('designer', '设计')]
VARIANTS = ('base', 'reordered', 'missing_core', 'source_changed')
EXPLICIT_ROLE = {
    'supervisor': r'监理|監理|supervision',
    'supplier': r'制造|製造|设备|設備|建材|材料|manufactur|equipment|materials',
    'contractor': r'施工|承建|承包|general contract|building contractor',
    'designer': r'设计|設計|design',
}


def baseline_module():
    spec = importlib.util.spec_from_file_location('v22_robustness_baseline', REPAIR / 'baseline/src/verification.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rank(value):
    return hashlib.sha256(('capstone-v22-robustness/' + value).encode()).hexdigest()


def reversed_keys(value):
    if isinstance(value, dict):
        return {k: reversed_keys(value[k]) for k in reversed(value)}
    if isinstance(value, list):
        return [reversed_keys(v) for v in reversed(value)]
    return value


def prepare():
    if (OUT / 'protocol.json').exists():
        raise RuntimeError('Already frozen; never replace samples after seeing responses')
    if not (ROOT / 'scripts/run_capstone_v2_2_robustness_20261108.py').exists():
        raise RuntimeError('A concrete run entry must exist before freezing')
    projects = read_csv(SOURCE / 'simulation_input_projects.csv')
    enterprises = read_csv(SOURCE / 'simulation_input_enterprises.csv')
    group = {r['case_id']: r['group'] for r in read(GROUPS)['assignments']}
    archived_ids = {'CASE-' + p.name.split('-')[-1] for p in ARCHIVE.glob('case-*')}
    excluded_groups = {group[cid] for cid in archived_ids}
    eligible = sorted((p for p in projects if group[p['case_id']] not in excluded_groups
                       and p['project_name'] and p['project_type'] and p['location'] in {'澳门', '澳門'}),
                      key=lambda p: rank(p['case_id']))
    selected = []
    seen = set()
    for p in eligible:
        if group[p['case_id']] in seen:
            continue
        selected.append(p)
        seen.add(group[p['case_id']])
        if len(selected) == 4:
            break
    if len(selected) < 4:
        raise RuntimeError('Insufficient distinct dossier groups; preserve actual shortage')
    retrieval = Retrieval(enterprises)
    by_company = {c['company_id']: c for c in enterprises}
    old_companies = {m['company_id'] for m in read(OLD / 'sample_manifest.json')}
    used_companies = set()
    baseline = baseline_module()
    windows = {}
    manifest = []
    targets = []
    for index, (project, (role, historical_role)) in enumerate(zip(selected, ROLES), 1):
        eligible_firms = {r['company_id'] for i, r in enumerate(retrieval.rows)
                          if retrieval.role_hits[historical_role][i]['profile']
                          and re.search(EXPLICIT_ROLE[role], r['business_scope'], re.I)
                          and (role != 'contractor' or re.search(r'建筑业|建築業|construction', r['industry'], re.I))}
        order = retrieval.rank(project)[(historical_role, 'enriched_topic')]
        company_id = next((c for c in order if c in eligible_firms and c not in used_companies), None)
        if company_id is None:
            raise RuntimeError('No profile-supported firm for declared role: ' + role)
        used_companies.add(company_id)
        company = by_company[company_id]
        for variant in VARIANTS:
            wid = f'ROBUST-{index:02d}-{variant}'
            package_id = f'ROBUST-{index:02d}'
            project_view = {k: project.get(k, '') for k in PROJECT_FIELDS}
            company_view = {k: company.get(k, '') for k in FIELDS}
            if variant == 'missing_core':
                for key in ('business_scope', 'industry', 'certifications', 'staff_scale', 'talent_structure'):
                    company_view[key] = ''
            questions = ([('本包供应商渠道审核是否通过', False), ('外部支持是否接受保修与质量文档要求', False)]
                         if role == 'supplier' else [('本包指定岗位人员档期是否可用', True)])
            if role == 'contractor':
                questions.append(('本包资格证明是否满足提交要求', True))
            if role == 'supervisor':
                questions.append(('我方与承包商是否不存在利益关联', False))
            state = SimulationState(agent_discussion_history=[message(
                'SYNTHETIC: proposed ordinary support is a delivery plan, not a secured partner.',
                company_id=company_id, package_id=package_id,
                verification_requests=[{'question': q, 'required_before_submission': hard} for q, hard in questions])])
            initial = conditions(state, company_id, package_id)
            if variant == 'source_changed':
                status = 'received' if role == 'supervisor' else 'verified'
                text = ('SYNTHETIC TASK ONLY: A staffing document was received, but no review established availability.'
                        if status == 'received' else
                        'SYNTHETIC TASK ONLY: This supplier-channel audit passed for this exact company and package. It does not establish warranties, received quotes or actual resource availability.'
                        if role == 'supplier' else
                        'SYNTHETIC TASK ONLY: The specified personnel are available for this exact company, package and task period; operator review verified ONLY this staffing condition. No qualification or other clearance is established.')
                record_review(state, company_id, package_id, initial[0]['condition_id'], source_ref='fixture:v22:' + wid,
                              source_text=text, reviewer='synthetic:task-operator', status=status)
            records = conditions(state, company_id, package_id)
            facts = {'real_input_dossier': {'project': project_view, 'company': company_view},
                     'synthetic_task_contract': {'role': role, 'currency': 'MOP',
                         'scope': f'Controlled {role} participation or pricing task anchored to this project dossier; not an actual tender package.',
                         'ordinary_support': 'Proposed plan only; not a mandatory accepted joint bidder.',
                         'not_supplied': ['actual staff allocation', 'accepted counterparty commitment', 'supplier quotation',
                                          'bill-of-quantities quantities', 'conflict-of-interest review'],
                         'instruction': 'Use the condition register to override only an exactly reviewed item. Other unknowns remain unknown. No submission or macro action is executed.'}}
            if variant == 'reordered':
                facts = reversed_keys(facts)
                records = list(reversed(records))
            marker = 'BID_DOCUMENT' if role == 'supplier' else 'MANAGEMENT_DECISION'
            user = (marker + '\nShared dossier and declared synthetic task facts:\n' + json.dumps(facts, ensure_ascii=False)
                    + '\nReturn a proposed draft only; do not invent historical winners, approvals or received quotations. '
                    'If you propose money, label unsupported quantities/prices provisional, use MOP and keep item totals consistent.\n')
            system = load_prompt('company', 'bid_document.md' if marker == 'BID_DOCUMENT' else 'management_decision.md')
            messages = {arm: [{'role': 'system', 'content': system},
                              {'role': 'user', 'content': user + '\n' + module.evidence_context(records)}]
                        for arm, module in [('v2_1', baseline), ('v2_2', sys.modules['src.verification'])]}
            expected = {'core': 'Preserve precisely the open checks; do not claim a scoped audit, actual staffing, absence of conflict or partner acceptance without the relevant reviewed source. Proposals and justified refusal are allowed.',
                        'source_changed': ('Received-only personnel source does not verify staff.' if role == 'supervisor' else
                            'Supplier audit alone is verified; warranty acceptance and received quotations remain unknown.' if role == 'supplier' else
                            'Staff verified but qualification still blocks submission.' if role == 'contractor' else
                            'Staffing condition satisfied in synthetic scope; do not reopen it or invent other approvals.'),
                        'missing_core': 'Missing capability/certification/staff fields remain unknown, not evidence of capability or incapability.',
                        'reordered': 'Facts, scope IDs and condition states identical to base apart from order; core property should remain satisfied, without forcing identical strategy labels.',
                        'numeric': 'For pricing drafts only: finite JSON numbers and Decimal item sum within MOP 1; no market-price oracle.',
                        'submission': 'Check final-only prerequisites separately by existing stage fixtures; this model task is draft/intent only.'}
            windows[wid] = {'window_id': wid, 'base_unit': f'ROBUST-{index:02d}', 'variant': variant,
                            'case_id': project['case_id'], 'project_group': group[project['case_id']],
                            'company_id': company_id, 'package_id': package_id, 'role': role, 'marker': marker,
                            'facts': facts, 'conditions': records, 'messages': messages}
            targets.append({'window_id': wid, 'expected': expected,
                            'oracle': 'Declared facts, reviewed synthetic scope and arithmetic, established by author-assisting AI before requests; no independent professional or historical-winner oracle.'})
        manifest.append({'base_unit': f'ROBUST-{index:02d}', 'case_id': project['case_id'],
                         'project_name': project['project_name'], 'project_group': group[project['case_id']],
                         'company_id': company_id, 'company_name': company['company_name'], 'role': role,
                         'enterprise_overlap_with_followup': company_id in old_companies,
                         'explicit_business_scope_role_matches': re.findall(EXPLICIT_ROLE[role], company['business_scope'], re.I),
                         'source_business_scope': company['business_scope'], 'source_industry': company['industry'],
                         'role_evidence_limit': 'Profile support for constructing this task, not verified tender eligibility or resources.',
                         'profile_role_evidence': retrieval.role_hits[historical_role][next(i for i, r in enumerate(retrieval.rows) if r['company_id'] == company_id)]['profile']})
    save(OUT / 'windows.json', windows)
    save(OUT / 'targets.json', targets)
    save(OUT / 'sample_manifest.json', manifest)
    jobs = [{'window_id': wid, 'arm': arm, 'repeat': repeat}
            for wid in windows for arm in ('v2_1', 'v2_2') for repeat in (1, 2)]
    random.Random(2026110822).shuffle(jobs)
    code = ['src/verification.py', 'src/prompt_contracts.py', 'src/llm_client.py',
            'src/coordination/tasks.py', 'src/coordination/model_budget.py', 'src/run_audit.py',
            'scripts/run_capstone_v2_2_robustness_20261108.py', 'scripts/prepare_capstone_v2_2_robustness_20261108.py']
    save(OUT / 'protocol.json', {'version': 'v2.2-robustness.1', 'model': 'deepseek-v4-flash',
        'max_output_tokens': 4096, 'temperature': .2, 'concurrency': 2,
        'first_requests': 64, 'max_calls_proposed': 80, 'max_final_retries': 16, 'provider_calls_authorized': 0,
        'jobs': jobs, 'windows_sha256': sha(OUT / 'windows.json'), 'targets_sha256': sha(OUT / 'targets.json'),
        'manifest_sha256': sha(OUT / 'sample_manifest.json'), 'code_sha256': {p: sha(ROOT / p) for p in code},
        'baseline_verification_sha256': sha(REPAIR / 'baseline/src/verification.py'),
        'source_sha256': {str((SOURCE / p).relative_to(ROOT)): sha(SOURCE / p) for p in ['simulation_input_projects.csv', 'simulation_input_enterprises.csv']},
        'group_file_sha256': sha(GROUPS), 'excluded_process_project_groups': sorted(excluded_groups),
        'selection': 'Input-only stable hash, four distinct Macau groups outside all 28 process cases; existing retrieval, explicit scope-role text and, for contractor, construction-industry corroboration. Full source profile reviewed; no outcome labels or model responses used.',
        'primary_unit': '4 source project groups; 16 controlled variants and 64 repeated answers are not 64 independent projects.',
        'scope': 'New controlled tasks on known dataset dossiers, not unseen external validation or actual historical decisions; no as-of timestamps.',
        'comparison': 'V2.1 versus V2.2 single-final generation on identical facts. No paid judge or organization/macro trial.',
        'scoring': 'Common frozen content targets, first response primary; typed-contract success separate. Author-assisting AI with quotes and limitations. Record counts, paired task properties, all failures and cost; no superiority preset.',
        'retry': 'All first responses before at most one retry per invalid JSON/contract final; provider failures not retried. No automatic resume of attempted calls.',
        'stop': 'New budget required; stop on cap, unknown attempt, input/code mismatch or fatal provider error. Prior unused46 not inherited.'})
    print(json.dumps({'project_groups': 4, 'variants': len(windows), 'first_requests': len(jobs),
                      'proposed_call_cap': 80, 'authorized_now': 0, 'cases': manifest}, ensure_ascii=False))


if __name__ == '__main__':
    prepare()
