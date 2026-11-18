"""Bounded outward company-claim checks against the supplied dossier.

Hard conflicts with unknown topics are blocked. Paraphrased claims whose
entailment cannot be mechanically established require review, never a pass.
This is not a language-complete entailment or source-authenticity checker.
"""
from copy import deepcopy
import hashlib
import json
import re

VERSION = 'company-narrative.v2.4.1'
EXCLUDED = {'thoughts','company_assessment','company_narrative_review',
            'verification_requests','verified_condition_ids','unresolved_condition_ids',
            'repair_explanation'}
TRAD = str.maketrans(dict(zip(
    '範圍經務產業稱質證實備無專適屬於礎體歷價團儲倉員項與對應營歸據擬許計劃確認並檔見過試單開當類內線為設織',
    '范围经务产业称质证实备无专适属于础体历价团储仓员项与对应营归据拟许计划确认并档见过试单开当类内线为设织')))
TRAD.update(str.maketrans({'疇':'畴','驗':'验','顧':'顾','問':'问'}))
OWN = r'(?:我(?:司|方|们)|本(?:公司|集团|企业)|公司|集团|企业|our company|we|our firm)'
# Each family has an independently meaningful failure mode; no company names,
# task IDs, case scores or whole saved sentences are in the recognizer.
RULES = [
 ('scope', 'business_direction', rf'{OWN}.{{0,18}}(?:主业|核心业务|业务方向|业务定位|业务范围|经营范围|专业背景|顾问背景|设计业务|以设计为主导|能力集中|核心能力|专长)'),
 ('scope', 'scope_alignment', rf'(?:与|属|属于|符合|匹配).{{0,15}}{OWN}.{{0,22}}(?:业务|主业|定位|背景|承接的范畴)'),
 ('scope', 'actual_competence', rf'{OWN}.{{0,18}}(?:具备|有能力|可独立承担|能够独立承担|可以独立承担|有成熟|has expertise|has the capability)'),
 ('scope', 'unsupported_incapacity', rf'{OWN}.{{0,15}}(?:不具备|缺乏|没有|缺少).{{0,18}}(?:能力|专业|团队|经验|资质|资格)'),
 ('scope', 'assumed_background', r'(?:仅凭|凭借|基于).{1,18}背景'),
 ('experience', 'experience_claim', rf'{OWN}.{{0,22}}(?:熟悉|擅长|长期从事|经验丰富|具有.{{0,8}}经验|具备.{{0,12}}经验|既有.{{0,8}}经验|现有.{{0,8}}经验|过往.{{0,8}}业绩)'),
 ('experience', 'unprovided_experience', r'(?:按|基于|凭借|利用).{0,20}(?:公司|集团|我方|我司|机构建筑与商业开发).{0,15}(?:经验|业绩)'),
 ('certifications', 'certification_claim', rf'{OWN}.{{0,18}}(?:持有|拥有|具备|缺乏|不具备).{{0,14}}(?:资质|资格|认证|牌照|执照)'),
 ('delivery_assets', 'existing_assets', r'(?:现有|既有|自有|已落实|已经落实).{0,18}(?:仓储|仓库|库存|车队|物流(?:资源|网络|资产)|运营网络|配送(?:资源|网络|资产)|本地团队|驻场团队|生产线)'),
 ('delivery_assets', 'asset_absence', rf'{OWN}.{{0,12}}(?:无|没有|缺少).{{0,14}}(?:本地团队|驻场团队|仓储|仓库|库存|车队)'),
 ('delivery_assets', 'asset_possession', rf'{OWN}.{{0,12}}(?:拥有|持有|具备).{{0,14}}(?:仓储|仓库|库存|车队|本地团队|驻场团队)'),
 ('product_range', 'own_products', r'(?:自营|自产|自有生产|自主生产).{0,18}(?:产品线|产品|材料|铺装|基材|设备|制造范围)'),
 ('historical_cost_basis', 'empirical_cost', r'(?:基于|依据|按|参考|利用).{0,20}(?:历史采购|历史成本|生产成本记录|同类项目单价|历史项目成本|内部成本记录)'),
 ('scope', 'english_capability', r'\b(?:we|our company|our firm)\s+(?:have|has|possess|lack|specialize|are experienced|can independently)\b'),
]

def outward_fields(data):
    """JSON-pointer-addressed strings; quoted assessment sources are data."""
    def visit(value, path):
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, list):
            for i, item in enumerate(value):
                yield from visit(item, path+'/'+str(i))
        elif isinstance(value, dict):
            for k, item in value.items():
                yield from visit(item, path+'/'+str(k).replace('~','~0').replace('/','~1'))
    for key,value in data.items():
        if key not in EXCLUDED:
            yield from visit(value,'/'+key)

def _not_a_fact(clause, match, kind, contextual=False):
    prefix=clause[:match.end()]
    before=clause[:match.start()]
    if contextual:
        # Reporting operators govern the following proposition, not an
        # independent assertion after a coordinator/adversative boundary.
        local=re.split(r'然而|但是|但|而且|并且|且|\bbut\b',prefix,flags=re.I)[-1]
        if re.search(r'(?:没有|无|未有).{0,16}(?:来源|证据|资料|记录).{0,8}(?:证明|表明|支持|显示)',local) and not re.search(r'并非没有|不是没有|不能没有',local):
            return True
        if re.search(r'是否|能否|尚待判断|尚不能判断|cannot determine whether',local,re.I):
            return True
        if kind in {'business_direction','scope_alignment'} and re.search(
            r'(?:资料|档案|来源).{0,80}(?:未载明|未记载|未载有|均无可用记录|无可用资料|无可用记录)',clause):
            return True
    if re.search(r'(?:非|不是|并非|不再|不|未)$',before) and not re.search(r'不是不|不能不|不得不',before):
        return True
    if kind in {'business_direction','scope_alignment'}:
        if re.search(r'(?:资料|档案|来源).{0,80}(?:均无可引用|无可引用|未提供|未披露|均无证据)',clause):
            return True
        if re.search(r'(?:业务范围|经营范围|经验|资质|交付资源|成本基础).{0,80}(?:均|全部|皆|都)?(?:为|是|属)?(?:unknown|未知|未经核实|未提供)',clause,re.I):
            if not re.search(r'(?:仍|却|但|然而).{0,15}(?:具备|有能力|主业)',clause):
                return True
    if (re.search(r'(?:资料|档案|证据|来源).{0,16}(?:未提供|未公开|未知|缺失|均无|尚待|未能提供)',clause)
        or re.search(r'(?:业务范围|经验|资质|资格|交付资源|成本基础).{0,40}(?:均为unknown|均为未知|目前均无|均未提供|尚未提供|未知)',clause)):
        if not re.search(r'(?:但|然而|而是|却).{0,20}(?:具备|有能力|主业|业务)',clause):
            # This is a statement about documentary absence, not an assertion
            # that the enterprise is incapable. Explicit lack-of-capacity
            # statements do not have this documentary subject.
            if re.search(r'资料|档案|证据|来源|投影',clause) or re.search(r'均为unknown|均为未知',clause):
                return True
    # A denial of making a claim is different from a negative claim of capacity.
    if re.search(r'(?:不能|不得|不应|不|未|无法)(?:对外)?(?:声称|断言|认定|宣称|表述为)|不作.{0,8}(?:能力|既有)|cannot (?:claim|assert)',prefix,re.I):
        if not re.search(r'不能不|不得不|无法不',prefix):
            return True
    if re.search(r'(?:资料|档案|来源|记录|证据).{0,12}(?:未提供|未公开|未知|缺失|未能证明)',prefix):
        # Do not use an earlier missing-evidence disclaimer to license a later
        # separate company assertion in the same comma-free clause.
        last_owner=list(re.finditer(OWN,prefix,re.I))
        if not last_owner or not re.search(r'具备|有能力|主业|业务方向相符',prefix[last_owner[-1].start():]):
            return True
    # A proposal to use EXISTING assets/products/history still asserts that
    # baseline exists. A bare proposed role does not.
    if kind not in {'existing_assets','own_products','empirical_cost','experience_claim','unsupported_incapacity','asset_absence','asset_possession','assumed_background'}:
        if re.search(r'拟|建议|计划|将(?:以|由|作为)|propos|plan to',prefix,re.I):
            return True
    return False

def narrative_context():
    return ('\nOutward company-claim contract v2.4 (opt-in): source assessment AND every outward field must agree. '
       'An unknown topic cannot become an actual company business direction, competence, lack of competence, '
       'experience, own products, existing assets, or historical cost basis in reason/content/cost bases. '
       'When stating dossier facts, quote the exact supplied excerpt and label it as dossier text, not reviewed acceptance. '
       'Separate proposed roles/workflows/resources from existing facts in each relevant clause. '
       'A proposal to use an existing warehouse or historical cost still asserts an unsupplied fact. '
       'Missing information is unknown, not incapacity. Keep useful conditional proposals; do not default to no_bid. '
       'Do not manufacture new pre-submission prerequisites for ordinary support plans. '
       'Uncertain semantic claims may require content review; a reference/regex pass does not establish narrative truth.\n')

def _clauses(original):
    boundary=r'[。；;，,！？\n]|但是|然而|但|而是|\bbut\b|\bhowever\b'
    start=0
    for match in re.finditer(boundary,original,re.I):
        if start<match.start():
            yield start,original[start:match.start()]
        start=match.end()
    if start<len(original):
        yield start,original[start:]

def _limited_scope_support(clause,kind,evidence,task_role=None):
    """Finite lexical support for business-direction paraphrases, not capacity."""
    if evidence['topics']['scope']['status']!='provided': return False
    if re.search(r'有能力|实际能力|已具备|资格(?:已|满足)|经验丰富|规模有限',clause): return False
    source=' '.join(evidence['sources'][r]['text'].translate(TRAD) for r in evidence['topics']['scope']['allowed_source_refs'])
    if kind=='actual_competence':
        role_terms={'supervisor':('监理','监管'),'designer':('设计',),'contractor':('施工','总承包'),'supplier':('材料','销售','供应','分销')}
        return bool(re.search(r'(?:业务|方向性|角色|合理)(?:上的)?(?:基础|定位)',clause)) and any(t in source for t in role_terms.get(task_role,()))
    if kind not in {'business_direction','scope_alignment'}: return False
    terms=('总承包','工程承包','建筑设计','设计','工程施工','施工','监理','监管','工程顾问','咨询','土木','公共工程','建筑材料','材料生产','商业开发','办公室','厂房')
    claimed=[t for t in terms if t in clause]
    return bool(claimed) and all(t in source for t in claimed)

def review_company_narrative(data,evidence,*,contextual=False):
    fields=list(outward_fields(data))
    findings=[]
    for path, original in fields:
        # Sentence/adversative boundaries prevent disclaimers licensing later
        # affirmations. Offsets refer to the exact original string, not a rewrite.
        for offset,raw in _clauses(original):
                clause=raw.translate(TRAD)
                # Verbatim, explicitly quoted supplied data is not an inferred
                # capability. Surrounding unquoted assertions remain checked.
                masked=clause
                for source in evidence['sources'].values():
                    text=source['text'].translate(TRAD)
                    for left,right in [('“','”'),('"','"'),('「','」')]:
                        masked=masked.replace(left+text+right,' '*len(left+text+right))
                for topic,kind,pattern in RULES:
                    for match in re.finditer(pattern,masked,re.I):
                        if _not_a_fact(masked,match,kind,contextual=contextual):
                            continue
                        provided=evidence['topics'][topic]['status']=='provided'
                        if contextual and topic=='scope' and _limited_scope_support(masked,kind,evidence,data.get('task_role')):
                            continue
                        if (provided and topic=='scope' and kind=='business_direction'
                            and re.search(r'(?:资料|证据|档案).{0,8}(?:仅|只|已|目前)?(?:确认|确证|覆盖|证明)|已披露(?:的)?业务范围',masked)
                            and not re.search(r'有能力|具备|真实能力|已获资格',masked)):
                            # Host already establishes presence of scope text.
                            # A statement that the dossier covers scope is not
                            # an inference of actual operational competence.
                            continue
                        # A range text can be repeated verbatim as a dossier fact.
                        tail=re.search(r'(?:经营范围|业务范围)(?:为|是|包括|涵盖|[:：])\s*(.+)$',masked)
                        if topic=='scope' and kind=='business_direction' and tail and any(
                            tail.group(1).strip(' "“”') in evidence['sources'][r]['text'].translate(TRAD)
                            for r in evidence['topics']['scope']['allowed_source_refs']):
                            continue
                        start=offset+match.start()
                        item={'path':path,'start':start,'end':offset+match.end(),
                          'quote':original[start:offset+match.end()],
                          'clause':raw,'topic':topic,'rule':kind,
                          'category':'source_entailment_review' if provided else 'unknown_company_claim',
                          'severity':'review_required' if provided else 'blocked',
                          'allowed_source_refs':evidence['topics'][topic]['allowed_source_refs']}
                        if not any(x['path']==path and x['topic']==topic and x['quote']==item['quote'] for x in findings):
                            findings.append(item)
    outward={k:deepcopy(v) for k,v in data.items() if k not in EXCLUDED}
    digest=hashlib.sha256(json.dumps(outward,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'version':'company-narrative.v2.5.1' if contextual else VERSION,'origin':'host_bounded_analysis_not_model_oracle',
       'company_id':evidence['company_id'],'projection_sha256':evidence['projection_sha256'],
       'status':'blocked' if any(x['severity']=='blocked' for x in findings) else 'review_required' if findings else 'limited_checks_passed',
       'findings':findings,'checked_paths':[p for p,_ in fields],
       'original_outward':outward,'adopted_outward':deepcopy(outward),
       'original_sha256':digest,'adopted_sha256':digest,'text_changes':[],
       'limits':'Bounded Chinese/traditional-normalized and limited English claim families. Arbitrary paraphrases, implicit claims, market prices, jurisdiction and source authenticity are not established. A pass is not full semantic validation.'}

class NarrativeIssue(ValueError):
    def __init__(self,report):
        self.report=report
        self.category=report['status']
        self.retryable=report['status']=='blocked'
        self.paths=sorted({x['path'] for x in report['findings']})
        super().__init__('Company narrative '+self.category+': '+json.dumps(report['findings'],ensure_ascii=False))

def require_company_narrative(data,evidence,*,contextual=False):
    report=review_company_narrative(data,evidence,contextual=contextual)
    if report['status']!='limited_checks_passed':
        raise NarrativeIssue(report)
    return report
