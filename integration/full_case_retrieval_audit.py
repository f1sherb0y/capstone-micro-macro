"""Use all project rows for input-only role retrieval, separate from simulation.

Every project gets the same predefined role queries before any label is read.
Delivery mode is retained; unsupported modes are never converted to DBB.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from integration.candidate_policy_v3 import normalize, retrieve
from integration.benchmark_lifecycle_batch import supported

ROLES = {
    '施工/总承包': ('总承包', '承建', '承造', '施工', '土木工程建筑', '建筑工程'),
    '设计': ('建筑设计', '工程设计', '设计院', '规划设计', '设计咨询', '设计顾问'),
    '检测/质量控制': ('检测', '试验', '质量控制', '检验', '测试'),
    '研究': ('研究', '科研', '大学', '学院'),
    '代建/项目管理': ('代建', '项目管理', '工程管理'),
    '造价/工料测量': ('造价', '工料测量', '测量师', '成本咨询'),
    '咨询/顾问': ('咨询', '顾问', '顾问服务'),
    '供应/制造': ('制造', '生产', '供应', '建材', '钢材', '混凝土', '预制'),
    '专业分包': ('专业承包', '分包', '机电', '消防', '装修', '地基'),
    '勘察/测绘': ('勘察', '勘测', '测绘', '岩土'),
    '监理': ('监理', '工程监督'),
}
KS = (5, 10, 12, 20, 50)
ROOT = Path(__file__).resolve().parents[1]


def load_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, required=True)
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'data/test_sources/casebank_enterprise_matched'
    projects = load_rows(source / 'simulation_input_projects.csv')
    # Keep the same public projection as the production candidate catalogue.
    fields = ('company_id', 'company_name', 'business_scope', 'industry', 'certifications', 'office_location')
    companies = [{k: row[k] for k in fields} for row in load_rows(source / 'simulation_input_enterprises.csv')]
    by_id = {c['company_id']: c for c in companies}
    role_support = {role: {c['company_id']: [word for word in words if word in normalize(' '.join(
        c[k] for k in ('company_name', 'business_scope', 'industry', 'certifications')))] for c in companies}
        for role, words in ROLES.items()}
    manifest = {'status': 'frozen_before_labels', 'case_count': len(projects), 'company_count': len(companies),
        'roles': ROLES, 'coverage_k': KS, 'seed': 42,
        'policy': 'documented-role-first-then-corpus-topic.v2',
        'note': 'Broad role retrieval diagnostic; not the production Contractor-only policy or a full simulation.',
        'source_sha256': {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in
            ('simulation_input_projects.csv', 'simulation_input_enterprises.csv')},
        'code_sha256': {name: hashlib.sha256((ROOT / 'integration' / name).read_bytes()).hexdigest() for name in
            ('candidate_policy.py', 'candidate_policy_v3.py', 'full_case_retrieval_audit.py')}}
    (args.directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    authored = []
    for i, project in enumerate(projects):
        # v3 base score consists of .65 text + .15 regional + .20 role support.
        # Remove the Contractor-specific role term and use each declared role.
        _, audit = retrieve(project, companies, count=12)
        base = {r['company_id']: r['score'] - .20 * (r['role_support'] == 'documented_business_scope') for r in audit}
        for role in ROLES:
            rank = sorted(base, key=lambda key: (
                not bool(role_support[role][key]), -base[key],
                hashlib.sha256(f"42/{project['case_id']}/{key}".encode()).hexdigest()))
            authored.append({'case_id': project['case_id'], 'role': role, 'ranked_company_ids': rank[:max(KS)],
                'documented_role_pool_size': sum(bool(role_support[role][key]) for key in base),
                'top12_role_support_count': sum(bool(role_support[role][key]) for key in rank[:12]),
                'top12_unverified_count': sum(not bool(role_support[role][key]) for key in rank[:12])})
        if (i + 1) % 50 == 0:
            print(json.dumps({'authored_projects': i+1, 'total': len(projects)}), flush=True)
    (args.directory / 'authored_rankings.json').write_text(json.dumps(authored, ensure_ascii=False), encoding='utf-8')
    # Hidden role membership is used for evaluation only, after every role query
    # has already run on every project and all rankings have been persisted.
    labels = load_rows(source / 'hidden_benchmark_project_enterprises.csv')
    truth = defaultdict(set)
    for row in labels:
        if row['company_role_original'] in ROLES and row['company_id']:
            truth[(row['case_id'], row['company_role_original'])].add(row['company_id'])
    scored = []
    for row in authored:
        target = truth[(row['case_id'], row['role'])]
        if not target:
            continue
        rank = row['ranked_company_ids']
        scored.append({**row, 'historical_ids': sorted(target),
            'source_has_historical_company': bool(target & by_id.keys()),
            'coverage_at_k': {str(k): bool(target & set(rank[:k])) for k in KS},
            'historical_relation_recall_at_12': len(target & set(rank[:12])) / len(target)})
    role_summary = []
    for role in ROLES:
        rows = [r for r in scored if r['role'] == role]
        role_summary.append({'role': role, 'scored_cases': len(rows),
            'covered_at_k': {str(k): sum(r['coverage_at_k'][str(k)] for r in rows) for k in KS}})
    mode_counts = dict(Counter(p['delivery_mode'] or '模式缺失' for p in projects))
    cases = []
    for project in projects:
        mode = project['delivery_mode']
        rows = [r for r in scored if r['case_id'] == project['case_id']]
        reason = ('current_full_lifecycle_supported' if supported(project) else
            'DBB_region_or_project_type_adapter_required' if mode == 'DBB' else
            'delivery_mode_information_required' if not mode else
            'EPC_design_construction_workflow_required' if mode == 'EPC' else 'original_mode_or_contract_scope_review_required')
        cases.append({k: project[k] for k in ('case_id', 'project_name', 'project_type', 'location', 'delivery_mode')} |
            {'input_retrieval_complete': True, 'full_lifecycle_supported': supported(project),
             'full_lifecycle_boundary': reason, 'scorable_roles': [r['role'] for r in rows],
             'construction_benchmark_available': bool(truth[(project['case_id'], '施工/总承包')]),
             'unlabeled_role_queries_not_scored': len(ROLES)-len(rows)})
    summary = {'status': 'all_project_role_retrieval_complete_not_full_simulation',
        'projects_used': len(projects), 'companies_used': len(companies), 'role_queries_authored': len(authored),
        'scored_project_role_pairs': len(scored), 'mode_counts': mode_counts,
        'current_full_lifecycle_supported': sum(supported(p) for p in projects),
        'construction_benchmark_cases': sum(c['construction_benchmark_available'] for c in cases),
        'role_summary': role_summary, 'model_calls': 0,
        'limits': ['Coverage measures input retrieval only, not actual bids, awards, qualifications or lifecycle success.',
            'Every role was queried uniformly; missing historical roles are not scored as failures.',
            'No verified pre-award timestamps; no causal or out-of-time validity claim.',
            'EPC, missing modes and other modes retain their original values and are not run as DBB.']}
    for name, value in [('summary.json', summary), ('inventory.json', cases), ('role_scores.json', scored)]:
        (args.directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    with (args.directory / 'inventory.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(cases[0])); writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in c.items()} for c in cases)
    print(json.dumps({k: summary[k] for k in ('projects_used', 'role_queries_authored', 'scored_project_role_pairs',
        'current_full_lifecycle_supported', 'construction_benchmark_cases', 'model_calls')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
