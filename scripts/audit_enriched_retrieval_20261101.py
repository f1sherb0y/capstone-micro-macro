"""Exploratory input-only ablations and richer evidence packs, outside live pins.

Does not alter live scenarios, make model calls, or read labels until predictions
for every project and role have been written. No policy is auto-promoted.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integration.candidate_policy_v3 import normalize, EXPANSIONS
from integration.full_case_retrieval_audit import ROLES

SOURCE = ROOT / 'data/test_sources/casebank_enterprise_matched'
FIELDS = ('company_id', 'company_name', 'business_scope', 'industry', 'certifications',
          'office_location', 'office_location_detail', 'enterprise_type',
          'established_time', 'registered_capital', 'paid_in_capital', 'staff_scale',
          'talent_structure', 'insured_staff_count', 'compliance', 'website')
PROJECT_FIELDS = ('case_id', 'project_name', 'project_type', 'location', 'scale',
                  'delivery_mode', 'owner_name')
POLICIES = ('enriched_topic', 'regional_pool', 'dual_pool_6plus6')
KS = (1, 3, 5, 12, 24)
MISSING = {'', '-', '—', '无', '未知', '暂无', '不详', '无法获取', '未披露', 'n/a', 'na', 'none', 'null'}
EXTRA_ROLE = {
    '施工/总承包': ('construction', 'contractor', 'civil engineering', '建筑承造'),
    '设计': ('architect', 'architectural', 'design consultant', '设计及研究'),
    '检测/质量控制': ('testing', 'inspection', 'laboratory'),
    '咨询/顾问': ('consultant', 'consultancy', 'consulting'),
    '造价/工料测量': ('quantity survey', 'cost consult'),
    '监理': ('supervision',), '勘察/测绘': ('geotechnical', 'surveying'),
    '供应/制造': ('manufacturer', 'supplier', 'materials'),
    '专业分包': ('subcontract',), '代建/项目管理': ('project management',),
    '研究': ('university', 'research',),
}
REGIONS = {
    '澳门': ('澳门', '澳門', 'macau', 'macao'),
    '香港': ('香港', 'hong kong', 'hongkong'),
    '深圳': ('深圳', 'shenzhen'), '珠海': ('珠海', 'zhuhai'),
    '广州': ('广州', '廣州', 'guangzhou'), '佛山': ('佛山', 'foshan'),
    '东莞': ('东莞', '東莞', 'dongguan'), '惠州': ('惠州', 'huizhou'),
    '江门': ('江门', '江門', 'jiangmen'), '中山': ('中山', 'zhongshan'),
    '肇庆': ('肇庆', '肇慶', 'zhaoqing'),
}
STOP = {'工程', '有限', '公司', '项目', '建设', '建筑', '建造'}


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def useful(value):
    return str(value or '').strip().casefold() not in MISSING


def regions(value):
    text = normalize(value).casefold()
    return {city for city, names in REGIONS.items() if any(normalize(n).casefold() in text for n in names)}


def tokens(value):
    value = normalize(value).casefold()
    result = set(re.findall(r'[a-z]{3,}', value))
    for chunk in re.findall(r'[\u4e00-\u9fff]+', value):
        result.update(chunk[i:i+2] for i in range(len(chunk)-1) if chunk[i:i+2] not in STOP)
    return result


class Retrieval:
    def __init__(self, rows):
        # Explicit safe projection; extra source fields cannot affect ranking.
        self.rows = [{k: r.get(k, '') for k in FIELDS} for r in rows]
        self.docs = [tokens(' '.join(r[k] for k in ('business_scope', 'industry', 'certifications')))
                     for r in self.rows]
        df = Counter(t for doc in self.docs for t in doc)
        self.idf = {t: math.log(1 + (len(rows)-n+.5)/(n+.5)) for t, n in df.items()}
        self.avg = sum(map(len, self.docs))/len(self.docs)
        self.locations = [regions(r['office_location']+' '+r['office_location_detail']) for r in self.rows]
        self.role_hits = {}
        for role, words in ROLES.items():
            terms = tuple(normalize(w).casefold() for w in (*words, *EXTRA_ROLE[role]))
            hits = []
            for r in self.rows:
                text = normalize(' '.join(r[k] for k in ('business_scope', 'industry', 'certifications'))).casefold()
                name = normalize(r['company_name']).casefold()
                strong = [w for w in terms if w in text]
                weak = [w for w in terms if w in name]
                hits.append({'profile': strong, 'name_only': weak if not strong else []})
            self.role_hits[role] = hits

    def rank(self, project):
        project = {k: project.get(k, '') for k in PROJECT_FIELDS}
        query = normalize(' '.join(project[k] for k in ('project_name', 'project_type', 'scale')))
        expansion = set()
        for triggers, synonyms in EXPANSIONS.values():
            if any(t in query for t in triggers):
                expansion.update(synonyms)
        q = tokens(query)
        expanded = tokens(' '.join(sorted(expansion))) - q
        lexical = []
        for doc in self.docs:
            # Query expansion has lower weight than observed project text.
            weighted = sum(self.idf[t] * (1 if t in q else .25) for t in doc & (q | expanded))
            lexical.append(weighted / (.25 + .75 * len(doc)/max(self.avg, 1)))
        peak = max(lexical, default=0) or 1
        dest = regions(project['location'])
        local = [bool(dest & city) for city in self.locations]
        result = {}
        for role in ROLES:
            def order(i):
                hit = self.role_hits[role][i]
                support = 1 if hit['profile'] else .25 if hit['name_only'] else 0
                score = .65*lexical[i]/peak + .20*support + .15*local[i]
                tie = hashlib.sha256(f"42/{project['case_id']}/{self.rows[i]['company_id']}".encode()).hexdigest()
                return -score, tie
            indices = [i for i, r in enumerate(self.rows) if r['company_name'] != project['owner_name']]
            global_rank = sorted(indices, key=order)
            # Separate geographic evidence from topic relevance; no branch/parent merges.
            local_rank = sorted(indices, key=lambda i: (not local[i], *order(i)))
            local_supported = [i for i in local_rank if local[i] and self.role_hits[role][i]['profile']]
            dual = []
            # Fixed six+six design, at each prefix alternate pools. Fill duplicates
            # from the same pool; backfill global only if the local pool runs out.
            a, b = iter(global_rank), iter(local_supported)
            for slot in range(12):
                pool = a if slot % 2 == 0 else b
                selected = next((i for i in pool if i not in dual), None)
                if selected is None:
                    selected = next((i for i in a if i not in dual), None)
                if selected is not None:
                    dual.append(selected)
            dual.extend(i for i in global_rank if i not in dual)
            for policy, rank in zip(POLICIES, (global_rank, local_rank, dual)):
                result[(role, policy)] = [self.rows[i]['company_id'] for i in rank]
        return result


def metrics(predictions, truth, subset):
    result = []
    for policy in POLICIES:
        entries = [(cid, role, ranks) for (cid, role, p), ranks in predictions.items()
                   if p == policy and cid in subset and truth[(cid, role)]]
        projects = sorted({cid for cid, _, _ in entries})
        row = {'policy': policy, 'project_n': len(projects), 'role_n': len(entries)}
        row['project_hits'] = {str(k): sum(any(truth[(cid, role)] & set(ranks[:k])
                    for c, role, ranks in entries if c == cid) for cid in projects) for k in KS}
        row['role_hits'] = {str(k): sum(bool(truth[(cid, role)] & set(ranks[:k]))
                    for cid, role, ranks in entries) for k in KS}
        result.append(row)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, required=True)
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    projects = read_csv(SOURCE/'simulation_input_projects.csv')
    raw_companies = read_csv(SOURCE/'simulation_input_enterprises.csv')
    index = Retrieval(raw_companies)
    predictions = {}
    for project in projects:
        for (role, policy), rank in index.rank(project).items():
            predictions[(project['case_id'], role, policy)] = rank[:24]
    authored = [{'case_id': c, 'role': r, 'policy': p, 'ranked_company_ids': rank}
                for (c, r, p), rank in predictions.items()]
    write(args.directory/'predictions_before_labels.json', authored)
    manifest = {'policy_version': 'enriched-public-retrieval.exploratory-20261101',
        'company_fields': FIELDS, 'project_fields': PROJECT_FIELDS, 'policies': POLICIES,
        'source_hashes': {f: hashlib.sha256((SOURCE/f).read_bytes()).hexdigest() for f in
            ('simulation_input_enterprises.csv', 'simulation_input_projects.csv')},
        'prediction_sha256': hashlib.sha256((args.directory/'predictions_before_labels.json').read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_calls': 0, 'live_inputs_modified': False,
        'limits': ['All comparisons exploratory; previous results have already been inspected.',
                   'Profiles lack verified pre-award dates; no prospective accuracy claim.',
                   'Past projects, partners, benchmark labels and current project outcomes excluded.',
                   'Capital and staffing retained as context, never guessed as ability scores.',
                   'More top-k coverage is not a top-1 award improvement.']}
    write(args.directory/'manifest.json', manifest)
    # Evaluation boundary: every ranking and hash already exist on disk.
    labels = read_csv(SOURCE/'hidden_benchmark_project_enterprises.csv')
    truth = defaultdict(set)
    for r in labels:
        if r['company_role_original'] in ROLES and r['company_id']:
            truth[(r['case_id'], r['company_role_original'])].add(r['company_id'])
    ids = {p['case_id'] for p in projects}
    dev = {'CASE-0001','CASE-0003','CASE-0005','CASE-0006','CASE-0007','CASE-0010','CASE-0012','CASE-0014','CASE-0019'}
    groups = {'all_projects': ids, 'nine_demonstration_cases': dev,
              'other_DBB': {p['case_id'] for p in projects if p['delivery_mode']=='DBB'}-dev}
    summary = {g: metrics(predictions, truth, subset) for g, subset in groups.items()}
    write(args.directory/'summary.json', summary)
    availability = {k: sum(useful(c[k]) for c in index.rows) for k in FIELDS}
    write(args.directory/'profile_availability.json', availability)
    pilot = next(p for p in projects if p['case_id']=='CASE-0001')
    # Evidence packs deliberately contain no truth or historical ranking diagnostics.
    by_id = {c['company_id']: c for c in index.rows}
    packs = {}
    for policy in POLICIES:
        rank = predictions[('CASE-0001', '施工/总承包', policy)]
        packs[policy] = {'project': {k: pilot[k] for k in PROJECT_FIELDS},
            'status': 'offline_candidate_context_not_live_model_input',
            'qualification_status': 'unverified',
            'companies': [{**by_id[cid], 'unknown_fields': [k for k in FIELDS if not useful(by_id[cid][k])],
                'regional_evidence': sorted(regions(by_id[cid]['office_location']+' '+by_id[cid]['office_location_detail'])),
                'source_csv_row': next(i+2 for i, c in enumerate(index.rows) if c['company_id']==cid)} for cid in rank[:12]]}
    write(args.directory/'CASE-0001_evidence_packs.json', packs)
    lines = ['# 微宏观实验：信息补充与候选检索对照', '',
        '本次仅做离线检索，模型调用为0；正在运行的CASE-0001保持原输入。所有方案均保留12家候选，另列Top1/3/5/24。', '',
        '新增企业注册、资本、人员、详细地址和资质等上下文；缺失保留未知。资本和人数没有转换为能力分。排除历史项目、客户关系及本项目结果，未把历史中标企业放回推荐输入。', '',
        '三种固定方案：信息增强的主题检索；地域优先检索；主题与本地角色证据交替取候选。没有根据标签反复调权，也不自动替换正在运行的版本。', '',
        '**本轮是探索性对照：此前已经查看过数据表现，不能称为独立测试集或论文最终泛化结果。**', '']
    for group, rows in summary.items():
        lines += [f'## {group}', '', '|方案|项目数|Top1|Top3|Top5|前12|前24|', '|---|---:|---:|---:|---:|---:|---:|']
        for row in rows:
            lines.append('|'+ '|'.join([row['policy'],str(row['project_n'])]+[f"{row['project_hits'][str(k)]}/{row['project_n']}" for k in KS])+'|')
        lines.append('')
    lines += ['## 可用企业信息', '', '|字段|有内容企业数/904|', '|---|---:|']
    lines += [f'|{k}|{n}|' for k, n in availability.items()]
    lines += ['', '有内容不等于已核验或在投标前已存在。企业资质、跨区域准入与业绩仍需带时间和来源的证明。', '',
        '后续实跑应先冻结改进版输入，再与基线比较候选覆盖、实际投标覆盖及最终中标一致率；不能只选最好的一组报告。']
    (args.directory/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'summary': summary, 'directory': str(args.directory)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
