"""Corpus retrieval with script normalization and declared engineering synonyms.

All query expansion is domain-wide. Hidden project-enterprise links are never
read here. Company branches and consortiums remain distinct legal identities.
"""
from collections import Counter
import hashlib
import json
import math
import re
import unicodedata

from integration.candidate_policy import evidence, location, terms

VERSION = 'public-project-fit.v3'
TRANSLATION = str.maketrans(dict(zip(
    '築總門鐵華灣擴設測橋樁圍體國際團務營業場廠綠環護維裝飾標險資質諮詢顧問劃電機專濬運輸區線堅澳',
    '筑总门铁华湾扩设测桥桩围体国际团务营业场厂绿环护维装饰标险资质咨询顾问划电机专浚运输区线坚澳')))
TRANSLATION.update(str.maketrans({
    '價':'价', '計':'计', '監':'监', '檢':'检', '驗':'验', '繪':'绘', '產':'产', '應':'应',
    '會':'会', '與':'与', '鋼':'钢', '預':'预', '製':'制', '測':'测', '學':'学', '術':'术',
    '員':'员', '開':'开', '發':'发', '樓':'楼', '綜':'综', '備':'备', '級':'级', '師':'师',
    '環':'环', '認':'认', '證':'证', '標':'标', '實':'实', '體':'体', '長':'长', '陸':'陆',
    '順':'顺', '達':'达', '寶':'宝', '創':'创', '聯':'联', '數':'数', '據':'据', '動':'动',
}))
EXPANSIONS = {
    'water': (('水库', '水利', '供水'), ('水利', '水务', '水工', '土木', '市政')),
    'marine': (('堤围', '海堤', '海事', '港口', '填海'), ('海事', '海湾', '港口', '航道', '土木', '地基', '水利')),
    'transport': (('路网', '连接', '交通', '公路', '大桥', '隧道'), ('市政', '路桥', '道路', '桥梁', '土木', '基础设施', '地下')),
    'environment': (('生态', '污水', '排水', '排放', '保护区'), ('环保', '环境', '水务', '排水', '市政', '土木', '园林')),
    'earthworks': (('清拆', '拆除', '平整', '地库', '基础', '桩'), ('地基', '基础', '土方', '拆除', '桩基', '土木', '地下')),
    'building': (('房屋', '建筑', '大楼', '医院', '酒店', '学校'), ('房屋', '楼宇', '建筑', '总承包', '地基')),
    'fitout': (('装修', '卷闸', '防火', '修复'), ('装修', '装饰', '机电', '消防', '维修', '建筑')),
}
POSITIVE_ROLE = ('总承包', '承建', '承造', '工程施工', '建筑业', '建筑工程', '土木工程建筑',
                 '房屋建筑', '海事工程', '港口工程', '地基工程', '路桥', '建筑商', '建造商')


def normalize(text):
    return unicodedata.normalize('NFKC', text or '').translate(TRANSLATION)


def canonical_name(text):
    # Do not remove subsidiary, branch or consortium suffixes.
    return re.sub(r'[\W_]+', '', normalize(text)).casefold()


def retrieve(project, enterprises, *, count, seed=42, excluded=()):
    if type(count) is not int or not 2 <= count <= 24:
        raise ValueError('Declare 2 to 24 active contractors')
    rows = [e for e in enterprises if e['company_id'] not in excluded
            and e['company_name'] != project.get('owner_name')]
    query = normalize(' '.join(project.get(k, '') for k in ('project_name', 'project_type', 'scale')))
    expanded = set()
    for triggers, synonyms in EXPANSIONS.values():
        if any(word in query for word in triggers):
            expanded.update(synonyms)
    query_tokens = terms(query) | terms(' '.join(expanded))
    documents = []
    for enterprise in rows:
        text = normalize(' '.join(enterprise.get(k, '') for k in ('business_scope', 'industry')))
        documents.append((text, Counter(terms(text))))
    df = Counter(token for _, counts in documents for token in counts)
    avg_length = sum(sum(c.values()) for _, c in documents) / max(1, len(documents))
    items = []
    for enterprise, (text, counts) in zip(rows, documents):
        bm25 = 0.
        length = sum(counts.values())
        for token in query_tokens & counts.keys():
            freq = counts[token]
            idf = math.log(1 + (len(rows) - df[token] + .5) / (df[token] + .5))
            bm25 += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * length / max(avg_length, 1)))
        role_text = text + ' ' + normalize(enterprise.get('certifications', ''))
        supported = any(word in role_text for word in POSITIVE_ROLE)
        origin, destination = location(enterprise.get('office_location', '')), location(project.get('location', ''))
        local = bool(origin and destination and origin == destination)
        basis = evidence(project, enterprise)
        basis.update(policy_version=VERSION, canonical_company_name=canonical_name(enterprise['company_name']),
            expanded_query_terms=sorted(expanded), matched_expanded_terms=sorted(query_tokens & counts.keys()),
            bm25=bm25, role_support='documented_business_scope' if supported else 'not_established',
            weights={'corpus_text_match': .65, 'documented_contractor_scope': .20, 'region_match': .15})
        tie = hashlib.sha256(f"{seed}/{project['case_id']}/{enterprise['company_id']}".encode()).hexdigest()
        items.append([enterprise, basis, supported, bool(local), tie])
    peak = max((i[1]['bm25'] for i in items), default=0)
    for enterprise, basis, supported, local, tie in items:
        basis['score'] = round(.65 * basis['bm25'] / peak + .20 * supported + .15 * local, 6) if peak else round(.20 * supported + .15 * local, 6)
        basis['source_sha256'] = hashlib.sha256(json.dumps({
            'public_projection_hash': basis['source_sha256'], 'certifications': enterprise.get('certifications', ''),
            'policy_version': VERSION, 'expanded_query_terms': basis['expanded_query_terms']},
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    items.sort(key=lambda row: (-row[1]['score'], row[4]))
    audit = [{**basis, 'company_id': enterprise['company_id'], 'selected': i < count, 'selection_rank': i+1,
              'tie_break': 'seeded_sha256', 'reason': 'selected_by_public_fit' if i < count else 'outside_declared_candidate_limit'}
             for i, (enterprise, basis, _, _, _) in enumerate(items)]
    return [i[0] for i in items[:count]], audit
