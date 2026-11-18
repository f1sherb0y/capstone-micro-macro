"""Input-only evidence retrieval. Scores measure text fit, never real capability.

No benchmark, project-enterprise relation or historical award fields are read.
Repeated keyword counts and enterprise-name length do not increase scores.
"""
import hashlib
import math
import re

VERSION = 'public-project-fit.v2'
DOMAINS = {
    'water': ('水库', '水庫', '水利', '供水', '水务', '水務'),
    'marine': ('海事', '港口', '航道', '填海', '堤围', '堤圍', '海堤'),
    'transport': ('交通', '道路', '路桥', '路橋', '公路', '连接线', '連接線', '隧道', '跨海大桥'),
    'drainage': ('污水', '排水', '给排水', '給排水', '排放管', '环保', '環保'),
    'earthworks': ('清拆', '拆除', '土方', '平整', '地基'),
    'building': ('房屋', '楼宇', '樓宇', '住宅', '酒店'),
}
CONTRACTOR_WORDS = ('总承包', '總承包', '承建', '承造', '施工', '土木', '建筑工程', '建築工程',
                    '建设工程', '建設工程', '港口', '航道', '路桥', '路橋', '地基')
STOP = {'工程', '有限', '公司', '项目', '建造', '建设', '建設', '建筑', '建築', '澳门', '澳門', '香港'}


def terms(text):
    return {chunk[i:i+2] for chunk in re.findall(r'[\u4e00-\u9fff]+', text)
            for i in range(len(chunk)-1) if chunk[i:i+2] not in STOP}


def location(value):
    for words, normalized in [(('澳门', '澳門'), 'Macau'), (('香港',), 'Hong Kong'),
                               (('珠海',), 'Zhuhai'), (('广州', '廣州'), 'Guangzhou'),
                               (('深圳',), 'Shenzhen')]:
        if any(w in value for w in words):
            return normalized
    return None


def evidence(project, enterprise):
    # Keep the projection explicit: extra columns (including outcome labels)
    # cannot influence retrieval or its provenance hash.
    fields = {k: enterprise.get(k, '') for k in
              ('company_id', 'company_name', 'business_scope', 'industry', 'office_location', 'certifications')}
    text = ' '.join(fields[k] for k in ('company_name', 'business_scope', 'industry'))
    project_fields = {k: project.get(k, '') for k in
                      ('case_id', 'project_name', 'project_type', 'location', 'scale')}
    project_text = ' '.join(project_fields.values())
    required = {k for k, words in DOMAINS.items() if any(w in project_text for w in words)}
    matched = {k for k in required if any(w in text for w in DOMAINS[k])}
    role_words = [w for w in CONTRACTOR_WORDS if w in text]
    origin, destination = location(fields['office_location']), location(project_fields['location'])
    # This is positive documentary support, not a zero-valued ability estimate.
    # Missing fields remain explicit and never constitute a qualification veto.
    domain_fit = len(matched) / len(required) if required else None
    regional_fit = float(origin == destination) if origin and destination else None
    query_terms = terms(project_text)
    company_terms = terms(fields['business_scope'] + ' ' + fields['industry'])
    overlap = query_terms & company_terms
    similarity = len(overlap) / math.sqrt(len(query_terms) * len(company_terms)) if query_terms and company_terms else None
    score = .45 * (similarity or 0) + .30 * (domain_fit or 0) + .15 * (regional_fit or 0) + .10 * bool(role_words)
    import json
    return {'policy_version': VERSION, 'score': round(score, 6),
            'score_kind': 'public_text_fit_proxy_not_observed_qualification',
            'required_domains': sorted(required), 'matched_domains': sorted(matched),
            'text_similarity': similarity, 'matched_text_terms': sorted(overlap),
            'weights': {'text_similarity': .45, 'domain_fit': .30, 'region_fit': .15, 'role_evidence': .10},
            'contractor_evidence': role_words, 'region_fit': regional_fit,
            'unknown_fields': [k for k in ('business_scope', 'industry', 'office_location', 'certifications') if not fields[k]],
            'qualification_status': 'not_verified',
            'source_sha256': hashlib.sha256(json.dumps(
                {'enterprise': fields, 'project': project_fields}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}


def retrieve(project, enterprises, *, count, seed=42, excluded=()):
    if type(count) is not int or not 2 <= count <= 24:
        raise ValueError('Declare 2 to 24 active contractors')
    candidates = []
    for enterprise in enterprises:
        if enterprise['company_id'] in excluded or enterprise['company_name'] == project.get('owner_name'):
            continue
        basis = evidence(project, enterprise)
        tie = hashlib.sha256(f"{seed}/{project['case_id']}/{enterprise['company_id']}".encode()).hexdigest()
        candidates.append((enterprise, basis, tie))
    candidates.sort(key=lambda item: (-item[1]['score'], item[2]))
    if len(candidates) < count:
        raise ValueError('Insufficient enterprise records')
    selected = candidates[:count]
    ledger = [{**basis, 'company_id': e['company_id'], 'selected': i < count,
               'selection_rank': i + 1, 'tie_break': 'seeded_sha256',
               'reason': 'selected_by_public_fit' if i < count else 'outside_declared_candidate_limit'}
              for i, (e, basis, _) in enumerate(candidates)]
    return [e for e, _, _ in selected], ledger
