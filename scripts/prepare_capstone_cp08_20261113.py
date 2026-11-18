"""Materialize every input-eligible CP08 candidate before any CP08 model output."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import random
import re

from capstone_cp_common_20261112 import ROOT, CP01, no_provider, read, save, sha
from prepare_capstone_expansion_20261109 import SOURCE, ROLES, EXPLICIT_ROLE, read_csv, Retrieval, FIELDS, PROJECT_FIELDS, baseline_module
from prepare_capstone_business_metrics_20261112 import task_card
from src.models import SimulationState
from src.company_grounding import company_evidence
from src.verification import conditions, evidence_context
from src.task_role_contract import role_context
from src.prompt_loader import load_prompt
from tests.test_verification_conditions import message

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-13_CP08全量微观扩样'
SCOPE = BASE / '指标补充/2026-11-12_完整方案_v4/scope.json'


def rank(value):
    return hashlib.sha256(('CP08-fixed-input-20261113|' + value).encode()).hexdigest()


def prepare():
    if (OUT / 'protocol.json').exists():
        raise ValueError('CP08 already fixed; verify rather than reselect')
    with no_provider() as counts:
        candidates = read(SCOPE)['CP08_candidate_groups']
        projects = {p['case_id']: p for p in read_csv(SOURCE / 'simulation_input_projects.csv')}
        firms = read_csv(SOURCE / 'simulation_input_enterprises.csv')
        retrieval = Retrieval(firms)
        by_firm = {c['company_id']: c for c in retrieval.rows}
        supported = {}
        for role, label in ROLES:
            pool = set()
            for i, c in enumerate(retrieval.rows):
                scope = c['business_scope']
                if not retrieval.role_hits[label][i]['profile'] or not re.search(EXPLICIT_ROLE[role], scope, re.I):
                    continue
                if role == 'contractor' and not re.search(r'建筑业|建築業|construction', c['industry'], re.I):
                    continue
                if role == 'designer' and not re.search(r'建筑设计|建築設計|工程设计|工程設計|规划设计|規劃設計', scope):
                    continue
                if role == 'supplier' and not re.search(r'生产|生產|制造|製造|销售|銷售|分销|分銷|供货|供貨|manufactur', scope, re.I):
                    continue
                pool.add(c['company_id'])
            supported[role] = pool
        role_counts = Counter()
        selection, disposition, windows, cards, ratings = [], [], {}, [], []
        baseline = baseline_module()
        targets = []
        common = deepcopy(read(CP01 / 'targets.json')[0])
        common.pop('window_id')
        leak_hits = []
        for candidate in sorted(candidates, key=lambda c: c['representative_case_id']):
            project = projects[candidate['representative_case_id']]
            rankings = retrieval.rank(project)
            choices = []
            for role, label in ROLES:
                cid = next((x for x in rankings[(label, 'enriched_topic')] if x in supported[role]), None)
                if cid:
                    choices.append((role_counts[role], rank(project['case_id'] + '|' + role), role, cid))
            if not choices:
                disposition.append({'project_group': candidate['project_group'], 'case_id': project['case_id'],
                    'state': 'input_ineligible', 'reason': 'No enterprise supported by frozen role/business-scope criteria.'})
                continue
            _, _, role, cid = min(choices)
            company = by_firm[cid]
            role_counts[role] += 1
            unit = f'CP08-{len(selection)+1:03d}'
            normalized_name = re.sub(r'\s+', '', project['project_name'])
            for field in FIELDS:
                if field in {'company_name', 'company_id'}:
                    continue
                normalized = re.sub(r'\s+', '', company.get(field, ''))
                if len(normalized_name) >= 6 and normalized_name in normalized:
                    leak_hits.append({'case_id': project['case_id'], 'company_id': cid, 'field': field,
                                      'state': 'requires_input_review_before_any_CP08_output'})
            for variant in ['full', 'missing_core']:
                wid = unit + '-' + variant
                dossier = {k: company.get(k, '') for k in FIELDS}
                if variant == 'missing_core':
                    for k in ['business_scope', 'industry', 'certifications', 'staff_scale', 'talent_structure']:
                        dossier[k] = ''
                qs = [('本包供应商渠道审核是否通过', False), ('外部支持是否接受保修与质量文档要求', False)] if role == 'supplier' else [('本包指定岗位人员档期是否可用', True)]
                if role == 'contractor':
                    qs.append(('本包资格证明是否满足提交要求', True))
                state = SimulationState(agent_discussion_history=[message(
                    'SYNTHETIC: ordinary support is a proposed delivery plan.', company_id=cid, package_id=unit,
                    verification_requests=[{'question': q, 'required_before_submission': required} for q, required in qs])])
                records = conditions(state, cid, unit)
                facts = {'real_input_dossier': {'project': {k: project.get(k, '') for k in PROJECT_FIELDS}, 'company': dossier},
                    'synthetic_task_contract': {'role': role, 'currency': 'MOP',
                        'scope': 'Controlled role participation/pricing draft, not an actual tender package or a reconstruction of local procurement.',
                        'ordinary_support': 'Proposed plan only; no accepted counterparty commitment.',
                        'not_supplied': ['actual staff allocation', 'supplier quotation', 'specific product catalogue', 'inventory/local-team records', 'historical procurement costs'],
                        'instruction': 'Use only supplied facts. Unknown is neither capable nor incapable. Proposed role-specific arrangements are allowed; no formal submission or macro action is executed.',
                        'regional_boundary': 'Keep the source project region and delivery mode. MOP is a controlled task accounting unit, not observed local tender currency or an FX conversion. No local legal qualification is presumed from region or company name.'}}
                marker = 'BID_DOCUMENT' if role == 'supplier' else 'MANAGEMENT_DECISION'
                system = load_prompt('company', 'bid_document.md' if role == 'supplier' else 'management_decision.md').replace('Macau compliance', 'applicable local compliance')
                user = marker + '\nShared facts:\n' + json.dumps(facts, ensure_ascii=False) + '\nReturn a draft or intention only. Unsupported quantities/prices must be provisional, in MOP, with item sums consistent.\n'
                evidence = company_evidence(dossier)
                messages = {
                    'v2_4': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user + baseline.evidence_context(records, company_sources=evidence, narrative_grounding=True)}],
                    'v2_5': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user + evidence_context(records, company_sources=evidence, narrative_grounding=True) + role_context(role)}]}
                window = {'window_id': wid, 'base_unit': unit, 'variant': variant, 'case_id': project['case_id'],
                    'project_group': candidate['project_group'], 'company_id': cid, 'package_id': unit, 'role': role,
                    'marker': marker, 'facts': facts, 'conditions': records, 'company_evidence': evidence, 'messages': messages}
                windows[wid] = window
                cards.append(dict(task_card(window), cohort='CP08'))
                targets.append({'window_id': wid, **deepcopy(common)})
            selection.append({'base_unit': unit, 'case_id': project['case_id'], 'project_group': candidate['project_group'],
                'project_name': project['project_name'], 'project_type': project['project_type'], 'location': project['location'],
                'role': role, 'company_id': cid, 'company_name': company['company_name'],
                'source_business_scope': company['business_scope'], 'source_industry': company['industry'],
                'scope_limit': 'One controlled role draft; not historical partnership or verified enterprise eligibility.'})
            disposition.append({'project_group': candidate['project_group'], 'case_id': project['case_id'], 'state': 'input_eligible', 'role': role, 'company_id': cid})
        by_window = {c['window_id']: c for c in cards}
        jobs = [{'window_id': wid, 'arm': arm, 'repeat': 1} for wid in windows for arm in ['v2_4', 'v2_5']]
        random.Random(2026111308).shuffle(jobs)
        for job in jobs:
            card = by_window[job['window_id']]
            ratings.append({'cohort': 'CP08', 'job': job, 'state': 'awaiting_real_response', 'D1_appropriateness': None,
                'factor_ratings': [{'factor_id': f['factor_id'], 'rating': None, 'response_quotes': [], 'source_locators': [], 'reason': None} for f in card['factors']],
                'D3_feasibility': None, 'D4_tradeoff': None, 'initial_rating': None, 'evidence_recheck': None})
        detailed = []
        for role, _ in ROLES:
            pool = sorted((m for m in selection if m['role'] == role), key=lambda m: rank('detailed|' + m['project_group']))
            detailed.extend(m['project_group'] for m in pool[:12])
        if len(detailed) < min(48, len(selection)):
            fill = sorted((m for m in selection if m['project_group'] not in detailed), key=lambda m: rank('fill|' + m['project_group']))
            detailed += [m['project_group'] for m in fill[:48-len(detailed)]]
        for name, value in [('windows.json', windows), ('targets.json', targets), ('sample_manifest.json', selection),
                            ('task_cards.json', cards), ('ratings_template.json', ratings), ('candidate_disposition.json', disposition),
                            ('detailed_score_groups.json', detailed), ('input_leak_review.json', {'exact_target_project_hits': leak_hits,
                                'field_whitelist': list(FIELDS), 'project_fields': list(PROJECT_FIELDS),
                                'asof_boundary': 'No consistent pre-tender timestamps; controlled present-dossier judgment, not historical forecasting.'})]:
            save(OUT / name, value)
        parent = read(CP01 / 'protocol.json')
        code = dict(parent['code_sha256'])
        for name in ['scripts/prepare_capstone_cp08_20261113.py', 'scripts/run_capstone_cp08_20261113.py']:
            code[name] = sha(ROOT / name)
        protocol = {**deepcopy(parent), 'version': 'CP08-cross-region-fixed-v24-v25.v1',
            'run_id': 'capstone-CP08-all-20261113', 'budget_id': 'CP08-independent-input-eligible-cap',
            'first_requests': len(jobs), 'max_calls_proposed': len(jobs), 'max_final_retries': 0,
            'provider_calls_authorized': 0, 'jobs': jobs, 'code_sha256': code,
            'windows_sha256': sha(OUT / 'windows.json'), 'targets_sha256': sha(OUT / 'targets.json'),
            'manifest_sha256': sha(OUT / 'sample_manifest.json'),
            'fixed_scope_sha256': sha(SCOPE), 'parent_CP01_protocol_sha256': sha(CP01 / 'protocol.json'),
            'regional_input_revision': 'Same paired facts; source geography retained, neutral local-compliance example, explicit task MOP rather than historical currency.',
            'primary_unit': 'Project group; two information conditions and paired versions, one repeat.',
            'selection': 'All232 input candidates in source-case order; least-used applicable role then fixed hash; first role-supported enriched retrieval company; reuse disclosed.',
            'paid_ready': not leak_hits, 'stop': 'Any provider failure/unknown or frozen mismatch stops all new paid work. No automatic replay or repair.'}
        save(OUT / 'protocol.json', protocol)
        summary = {'candidate_groups': len(candidates), 'eligible_groups': len(selection), 'excluded': len(candidates)-len(selection),
            'roles': dict(role_counts), 'distinct_firms': len({m['company_id'] for m in selection}),
            'most_projects_per_firm': max(Counter(m['company_id'] for m in selection).values(), default=0),
            'windows': len(windows), 'first_calls': len(jobs), 'detailed_groups': len(detailed),
            'target_text_hits_requiring_review': len(leak_hits), 'new_model_calls': 0, **counts}
        assert len(candidates) == 232 and len(jobs) <= 928
        assert len({m['project_group'] for m in selection}) == len(selection)
        save(OUT / 'preparation.json', summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    prepare()
