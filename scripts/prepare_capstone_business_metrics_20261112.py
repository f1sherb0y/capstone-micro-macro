"""Input-only business-result measurement addendum, outside the sealed run pack.

Fix task-specific expectations and empty ratings; never read new responses,
score content, change model prompts, or create a model client.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from capstone_cp_common_20261112 import PACK, CP01, CP02, CP03, no_provider, read, sha

OUT = ROOT / 'Capstone报告/验证体系/指标补充/2026-11-12_业务结果评价规范_v2'
REVISE_UNEXECUTED_DRAFT = False


def save(name, data):
    path = OUT / name
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != text:
            assert REVISE_UNEXECUTED_DRAFT and not (CP01 / 'run').exists() and not (CP03 / 'run').exists(), 'Preserve published measurement artifact: ' + name
            # This turn's unexecuted measurement draft may be clarified, but
            # its prior bytes remain visible; paid-run inputs are never edited.
            old = path.read_bytes()
            archive = OUT / 'preparation_drafts' / (path.stem + '-' + hashlib.sha256(old).hexdigest()[:16] + path.suffix)
            archive.parent.mkdir(exist_ok=True)
            if not archive.exists():
                archive.write_bytes(old)
            path.write_text(text, encoding='utf-8')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def metric(mid, name, question, formula, unit, population, source, priority, boundary):
    return {'id': mid, 'name': name, 'question': question, 'formula': formula,
            'unit': unit, 'population_and_denominator': population, 'source': source,
            'priority': priority, 'interpretation_boundary': boundary,
            'state': 'definition_only_not_measured'}


def dictionary():
    return [
        metric('D1', '决策适当率', '意向、等待或拒绝是否符合本题事实与职责？',
               'appropriate / judgable_decisions', 'proportion',
               'CP01全部192首轮；先按项目内4槽位/版本汇总。可判正文为内容分母，192槽位的去向另列。',
               '原始正文＋逐题行动边界卡＋依据引文，作者辅助AI判读', 'RQ1主要',
               '允许多种合理行动；只判断草稿/意向，不能当实际投标成功率或商业最优准确率。'),
        metric('D2', '关键业务因素正确覆盖率', '本题重要事项是否得到正确、充分处理？',
               'correct_factors / applicable_prelisted_factors; partial separately', 'proportion',
               '每情景5项；供应6项。48情景共252项，192首轮对应1008个事项评分槽位。先逐回答、逐项目汇总，不以长回答或事项数给项目加权。',
               'task_cards.json中的输入依据、充分处理判据及回答引文', 'RQ1主要',
               '正确/部分/遗漏/矛盾分别标注；后3者均不计正确。事项不是新增提交条件。'),
        metric('D3', '方案可行性评分', '提出的安排在声明边界内能否成立？',
               'ordinal_score_0_1_2; distribution_and_project_paired_difference', 'ordinal_0_2',
               'CP02固定48对/96份回答；无正文/无法判断另列。',
               '原始方案、任务卡、来源与条件；rubric.json', 'RQ1业务质量辅助',
               '明确且可行的条件性方案可得2分，未知本身不扣分；不是独立专家评价。'),
        metric('D4', '权衡质量评分', '是否把关键取舍与所选行动联系起来？',
               'ordinal_score_0_1_2; distribution_and_project_paired_difference', 'ordinal_0_2',
               '与D3相同；相关取舍须来自任务事实或明确方案假设。',
               '原始理由/方案与任务卡；rubric.json', 'RQ1业务质量辅助',
               '不要求编造市场价格、伙伴承诺或假备选；不与D3等维度加权合成总分。'),
        metric('O1', '有依据的新增讨论事项数', '岗位评论增加了多少可核查的业务考虑？',
               'count(distinct_supported_new_business_issues_per_block)', 'issues_per_block',
               '已有12个S/D3固定过程块；以同一D3块先前评论为新增参照。',
               '每条评论原句、输入依据、去重事项ID与业务含义', 'RQ2过程结果',
               '新事项是新考虑而非新外部事实；重复原文、泛泛提醒及无依据断言不增加计数。'),
        metric('O2', '有效事项回应率', '最终方案是否正确回应有用的讨论事项？',
               '(correctly_adopted + reasonably_rejected) / supported_new_issues', 'proportion',
               'O1事项为分母；分母0记N/A并报告没有新增事项的块数。',
               '评论引文、最终方案引文及采用/有据拒绝/遗漏/错误采用分类', 'RQ2主要过程指标',
               '采用越多不自动越好；原生A02只有最终option_id，不能据ID相同计算此率。'),
        metric('O3', '最终质量的成对差值', '同输入下审议的最终产物有何质量变化？',
               'D3-S differences for each of D1/D2/D3/D4; no weighted total', 'dimension_specific',
               '旧自由生成12个S/D3固定过程块，每块一个预选重复。各维缺失对单列。',
               '两份最终原文分别评分后作差；不是把S当作D3真实初稿', 'RQ2质量辅助',
               '旧材料已见，新增评分属探索性；没有该流程的S4最终正文，不虚构三组质量表。'),
        metric('O4', '策略选择分歧率', '组织与同调用次数单角色复核是否选择不同策略？',
               'different_canonical_actions_or_markups / comparable_actor_pairs', 'proportion',
               'CP03主对照D3/S4最多6项目×3重复×2承包商＝36对；D3/S、S/R次要。',
               '原始选项、定价来源、最终报价和承包商身份；先映射语义策略再比较', 'RQ2行为结果',
               '按项目聚合；分歧本身无好坏方向，原始option_id命名不同不算分歧。'),
        metric('F1', '相关反馈下适当响应率', '相关业务结果是否触发规则预期的后轮行为？',
               'expected_response_pairs / applicable_predeclared_response_pairs', 'proportion',
               'CP04允许地区的无反馈/实际结算反馈对，计划12对；按输入规则先判适用性。',
               '窗口初态、私有规则、反馈条件及前后动作；expected actions先于重放固定', 'RQ3主要',
               '若别的约束已主导，按输入事先分层；不得按观察到是否翻转事后剔除。当前为确定性规则，非LLM学习。'),
        metric('F2', '应不变条件的保持率', '反馈是否绕过了主导约束或引起无依据变化？',
               'constraint_preserving_pairs / applicable_control_pairs, by control_type', 'proportion_by_stratum',
               '地区限制对计划12对；同条数只改金额对计划24对，两层分开，不合并成一个大比例。',
               'CP04相同资料哈希、地区规则、结算计数阈值及动作', 'RQ3对照',
               '金额在当前计数规则中不被消费；金额不敏感只能说明此规则边界。'),
        metric('T1', '报价策略与成本加成', '模型实际选择了什么商业定价策略？',
               'markup=(bid-declared_cost_base)/declared_cost_base, if independently supplied base>0', 'fraction_and_currency',
               'CP03最多144个承包商报价/意向槽位；成本基数缺失则加成N/A，仍保留报价与策略。',
               '原始定价资料、原处理器计算、正式投标事件', 'RQ4交易过程',
               '成本基数须独立可读，不从报价倒推；声明加成不是实际利润率，不以低报价判优。'),
        metric('T2', '签约价占预算比', '不同机制怎样影响最终交易价格？',
               'contract_sum / initial_budget; project paired D3-S4 differences', 'ratio',
               '72条链/组各18条；主比较最多18个项目-重复块，再聚合为6个项目差。双方已签约时比较；单边未签约另列交易状态。',
               '初始预算与实际授标/签约事件、承包商身份', 'RQ4主要业务数值',
               '这是价格后果，不是综合效用或越低越好；需同时展示授标对象、约束和项目后果。'),
        metric('T3', '模拟项目成本偏差', '交易差异传到了怎样的模拟成本后果？',
               '(actual_cost-reference)/reference, references=budget/estimate/contract', 'ratio_by_reference',
               '到达相同预定可比较终点的链对；全部链的完成/未完成状态先列，不能只挑成功项目。',
               '项目performance、预算/估算/合同各参照、状态及成本轨迹', 'RQ4次要业务后果',
               '现有成本公式受合同价缩放；不独立声称工程生产率提升，不把三分母择优替换。'),
        metric('T4', '进度与阶段时序差异', '不同机制的项目推进是否分叉？',
               'progress_gap_pp=100*(actual_progress-planned_progress); event_tick_differences separately', 'percentage_points_and_ticks_separately',
               '相同业务tick或预定里程碑的可比较观测；未发生事件记未发生。',
               'project_state_updated与授标/完工/结算事件', 'RQ4次要业务后果',
               'tick不直接换成现实天；与质量、风险等没有作用路径的默认指数不拼总分。'),
    ]


FACTORS = {
    'contractor': [
        ('C1', '承接范围与资格边界', '用实际提供的经营范围限定承接判断；任务分配和公司名称不证明能力。资格核查未决时保留边界。', ['scope', 'role', 'conditions']),
        ('C2', '施工组织与责任接口', '提出至少两项相关施工/现场组织/分包接口安排，并区分本方责任与拟议外部支持；一般空泛承诺仅算部分。', ['role', 'task']),
        ('C3', '人员与资源可实施性', '区分企业总体资料与本包实际人员档期/资源落实；给出有边界的落实安排，不捏造现成团队。', ['staff', 'task', 'conditions']),
        ('C4', '未决前提的业务处理', '处理本题人员与资格核查的业务后果，保留必要提交前提；不把普通支持计划自动升级为硬门槛。', ['conditions', 'task']),
        ('C5', '项目针对性与取舍', '把至少一项已给的项目条件与具体安排或行动理由联系起来；项目背景交付模式不自动改变当前承建角色。', ['project', 'role']),
    ],
    'supplier': [
        ('S1', '供货范围与产品依据', '有范围资料时限定到资料支持的业务方向；无资料时提出有边界的产品/材料方案，不凭身份声称自有产品或库存。', ['scope', 'role', 'task']),
        ('S2', '具体供货交付方案', '提出至少两项供应/配送/文档交付安排，说明拟议性质及需确认部分；不因未给实际目录而要求虚构具体自产品。', ['role', 'task']),
        ('S3', '交付资源和承诺状态', '明确本地团队、库存、渠道报价等未被提供，区分拟议安排与已经落实的供应承诺。', ['staff', 'task']),
        ('S4', '质量保修与外部接口', '回应渠道审核、质量文档和保修责任的未决状态，给出拟议处理；两项原请求不是硬提交门槛，不无据升级。', ['conditions', 'task']),
        ('S5', '项目针对性', '将至少一项已给项目条件与供货安排联系；不把项目EPC标签当本方承担整包施工的依据。', ['project', 'role']),
        ('S6', '报价可解释性', '在MOP下给出可复算的分项/总额及明确暂定依据，承认未取得实际供应报价/历史采购成本；不要求市场最优价。', ['task', 'numeric']),
    ],
    'designer': [
        ('D1', '设计服务范围与边界', '用已给资料限定设计业务方向，或在未知时给出条件性服务方案；不自称整包EPC总承包或凭角色补足资质。', ['scope', 'role']),
        ('D2', '设计交付与专业接口', '提出至少两项设计成果、复核或专业接口安排；不以空泛参与意向替代服务方案。', ['role', 'task']),
        ('D3', '人员档期与履行安排', '整体员工/工作室资料不证明本包团队已到岗；保留人员档期核查并给出拟议组织办法。', ['staff', 'conditions', 'task']),
        ('D4', '前提和外部协作处理', '说明未决人员核查对后续承诺的影响；外部顾问/伙伴仅作为计划，普通协作不自动成为强制联合体。', ['conditions', 'task']),
        ('D5', '项目针对性与方案取舍', '至少一项项目条件实际进入设计安排或行动理由；不从项目名称或规模推出未给技术规范、实际业绩或承诺。', ['project', 'role']),
    ],
    'supervisor': [
        ('V1', '监督职责与权限边界', '保持监督、审查与记录职责；不得把监理/监督角色写成施工总包或整包设计施工主体，能力判断限于档案。', ['scope', 'role']),
        ('V2', '检查与记录方案', '提出至少两项进度/质量监督、检查、复核或记录安排；计划不能写成已完成核查/合格结论。', ['role', 'task']),
        ('V3', '监督人员与服务可实施性', '保留本包人员档期未知，区分企业人才描述与实际派驻，提出条件性服务组织安排。', ['staff', 'conditions', 'task']),
        ('V4', '未决条件与责任接口', '说明人员核查未决状态及必要后续步骤，区分本方监督责任、施工方责任与未接受的外部支持。', ['conditions', 'role', 'task']),
        ('V5', '项目针对性与风险考虑', '将至少一项给定项目条件与监督重点或行动理由联系；未知现场条件只可作为待确认事项或明确假设。', ['project', 'role']),
    ],
}


def task_card(w):
    company = w['facts']['real_input_dossier']['company']
    project = w['facts']['real_input_dossier']['project']
    task = w['facts']['synthetic_task_contract']
    pointers = {
        'scope': '/facts/real_input_dossier/company/business_scope',
        'role': '/facts/synthetic_task_contract/role', 'task': '/facts/synthetic_task_contract',
        'conditions': '/conditions', 'project': '/facts/real_input_dossier/project',
        'staff': '/facts/real_input_dossier/company', 'numeric': 'parent_targets/numeric',
    }
    factors = []
    alternatives = [
        '无论提出方案、等待或拒绝，均需保持职责与来源边界；以有据的范围/资格问题解释行动，不把未知写成缺乏。',
        '有据等待/拒绝时，不强求两项拟实施工作；说明为何不推进、哪个业务步骤暂不承诺及具体重审/补证触发条件，可满足本事项。',
        '等待/拒绝时说明人员或资源状态怎样限制承诺及需核实什么，不虚构实际不足；不要求编造资源排班。',
        '说明原未决事项怎样影响下一步，保持实际状态和必要/可选性质；拒绝不会使条件自动变为已解决。',
        '行动理由仍应联系本题的已给条件或明确资料缺口；有据等待/拒绝不要求虚构一个完整实施方案。',
        '有据不报价/暂缓报价时，明确价格未形成或非约束性，指出所缺依据和形成报价所需资料；不为满足量表强迫编造分项金额。',
    ]
    for index, (fid, label, adequate, bases) in enumerate(FACTORS[w['role']]):
        factors.append({'factor_id': fid, 'label': label, 'applicable': True,
                        'input_pointers': [pointers[b] for b in bases], 'adequate_handling': adequate,
                        'handling_for_supported_defer_or_decline': alternatives[index],
                        'states': ['correct', 'partial', 'missing', 'contradicted', 'not_judgable'],
                        'correct_denominator_weight': 1, 'is_new_submission_condition': False})
    constraints = [{'condition_id': c['condition_id'], 'question': c['question'],
                    'status': c['status'], 'required_before_formal_submission': c['required_before_submission'],
                    'expectation': 'Preserve actual unresolved state; drafting remains allowed; never describe an unreceived reply as verified.'}
                   for c in w['conditions']]
    attention = [
        {'input_pointer': '/facts/real_input_dossier/project/scale', 'provided_value': project.get('scale', ''),
         'handling': '规模有值时可用于拟议安排；空白时不要求虚构数量、实际工期或工程量。'},
        {'input_pointer': '/facts/real_input_dossier/project/delivery_mode', 'provided_value': project.get('delivery_mode', ''),
         'handling': '交付模式描述项目背景，不自动使本方成为整包设计采购施工主体。'},
    ]
    if company.get('compliance'):
        attention.append({'input_pointer': '/facts/real_input_dossier/company/compliance',
                          'provided_value': company['compliance'], 'related_factor_id': factors[4]['factor_id'],
                          'handling': '项目针对性/风险因素中考虑档案所记合规信息及核查需要；不将过去记载直接判为当前禁止参与或已获全面认可。'})
        factors[4]['adequate_handling'] += ' 本题另有合规记载，需按其有限证据说明风险或核查安排，不预断实际资格。'
    if company.get('staff_scale') or company.get('talent_structure'):
        attention.append({'input_pointer': '/facts/real_input_dossier/company',
                          'provided_values': {k: company[k] for k in ['staff_scale', 'talent_structure'] if company.get(k)},
                          'handling': '保留给定的总体人员资料，但不得把它升级为本包实际派驻/档期已确认。'})
    return {'window_id': w['window_id'], 'case_id': w['case_id'], 'project_group': w['project_group'],
            'company_id': w['company_id'], 'role': w['role'], 'variant': w['variant'],
            'assessment_stage': 'draft_or_intention_only_not_formal_submission',
            'business_objective': {'contractor': '形成有依据、责任明确的施工承接意向或条件性方案',
                                   'supplier': '形成有依据的供货、交付及暂定报价方案',
                                   'designer': '形成角色内的设计服务意向、交付与接口安排',
                                   'supervisor': '形成角色内的监督服务意向、检查与记录安排'}[w['role']],
            'project_facts': project,
            'scope_basis': {'state': 'provided_dossier_not_verified_eligibility' if company['business_scope'] else 'unknown',
                            'text': company['business_scope'], 'projection_sha256': w['company_evidence']['projection_sha256']},
            'provided_company_fields': {k: v for k, v in company.items() if v},
            'not_supplied': task['not_supplied'], 'ordinary_support': task['ordinary_support'],
            'conditions': constraints, 'case_specific_attention': attention, 'factors': factors,
            'acceptable_annotated_actions': [
                {'action': 'conditional_proposal_or_participation', 'when': '角色内、依据适当，必要条件未决时明确限制后续承诺；bid标签本身不代表无条件正式提交。'},
                {'action': 'defer_pending_relevant_evidence', 'when': '指出具体实质缺口及为何影响下一步，并保留已有事实和可行的条件性工作。'},
                {'action': 'decline_with_supported_business_reason', 'when': '理由由本题事实或明确的风险/资源取舍支持；不能由空白档案推出实际无能力。'},
            ],
            'inappropriate_examples': ['把草稿称为实际投标/签约', '声称未知的人员/渠道/报价已核实',
                                       '把档案未记载当实际无资格或无能力', '承担与受控角色冲突的整包责任',
                                       '用无业务依据的强制前提阻断普通支持计划'],
            'common_scoring_rules': ['无资料不自动要求拒绝，明确可行的条件性方案可以得高分。',
                                     '不要求新JSON字段，不因V2.4缺task_role字段扣共同业务内容分。',
                                     '项目名称复述不构成项目针对性，需说明至少一项条件怎样影响安排。',
                                     '未提供工期、规格、市场价格等不要求补造，合理方案假设与事实断言分别判。',
                                     '拒绝/等待使用各事项事先列好的相应处理分支，不强迫编造实施方案或报价，也不因此删除事项分母。',
                                     '事项遗漏记missing，矛盾记contradicted，不得改记不可判断以排除低分；只有输入确实不可判或无可读回答时记不可判断并保留缺失说明。'],
            'state': 'input_expectations_fixed_no_response_rated'}


def main():
    old_study = ROOT / 'Capstone报告/验证体系/实验/2026-11-08_后续模型实验/attempt-002'
    sources = [PACK / 'package_manifest.json', CP01 / 'protocol.json', CP01 / 'windows.json',
               CP01 / 'targets.json', CP02 / 'ab_mapping.json', CP02 / 'organization_blocks.json',
               CP03 / 'protocol.json', PACK / 'checks/source_model_windows.json',
               old_study / 'windows.json', old_study / 'protocol.json']
    before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    with no_provider() as counts:
        windows, protocol = read(CP01 / 'windows.json'), read(CP01 / 'protocol.json')
        cards = [task_card(w) for w in windows.values()]
        by_id = {c['window_id']: c for c in cards}
        assert len(cards) == 48 and len({c['project_group'] for c in cards}) == 24
        assert sum(len(c['factors']) for c in cards) == 252
        roles = Counter(c['role'] for c in cards)
        assert set(roles.values()) == {12}
        for card in cards:
            assert len(card['factors']) == (6 if card['role'] == 'supplier' else 5)
            if card['variant'] == 'missing_core':
                assert card['scope_basis']['state'] == 'unknown'
            for condition in card['conditions']:
                assert condition['required_before_formal_submission'] == (card['role'] != 'supplier')
        ratings = []
        for job in protocol['jobs']:
            card = by_id[job['window_id']]
            ratings.append({'job': job, 'state': 'awaiting_real_response', 'annotated_action': None,
                            'D1_appropriateness': None, 'D1_reason': None,
                            'factor_ratings': [{'factor_id': f['factor_id'], 'rating': None,
                                               'response_quotes': [], 'source_locators': [], 'reason': None}
                                              for f in card['factors']],
                            'D3_feasibility': None, 'D4_tradeoff': None,
                            'supporting_evidence': [], 'critical_business_violations': [],
                            'initial_rating': None, 'evidence_recheck': None})
        assert len(ratings) == 192 and sum(len(r['factor_ratings']) for r in ratings) == 1008
        rubric = {
            'version': 'business-result-rubric.v2', 'reviewer': 'current_conversation_assistant',
            'independent_human_expert': False, 'ratings_completed': 0,
            'D1': {'values': ['appropriate', 'inappropriate', 'not_judgable'],
                   'rule': '根据行动边界、任务职责、现有事实与必要条件整体判读；不从accepted、decision枚举或引用字段通过直接推断。'},
            'D2': {'values': ['correct', 'partial', 'missing', 'contradicted', 'not_judgable'],
                   'rule': '充分且正确地处理任务卡事项记correct，其他分类分开；不重复计同一事项。按预先行动分支判读，拒绝/等待不删分母；遗漏或矛盾不能标为不可判断。'},
            'D3': {'0': '安排与关键约束矛盾，或用无来源的已落实承诺支撑可实施性。',
                   '1': '部分安排有依据，但缺关键执行逻辑、责任接口或未决事项处理。',
                   '2': '在角色和资料边界内给出连贯可实施的方案或有据的等待/拒绝及下一步；条件性方案允许2分。',
                   'not_judgable': '无可判正文或资料确实不能支持该判断，说明原因。'},
            'D4': {'0': '未处理相关取舍，或依据无关/捏造的优劣作决定。',
                   '1': '识别相关取舍，但与最终行动或条件安排的联系不充分。',
                   '2': '把任务支持的关键取舍与行动、备选或承诺边界明确联系；不要求捏造数量化效用。',
                   'not_judgable': '无可判取舍材料，说明原因。'},
            'pair_preference': {'values': ['A', 'B', 'tie', 'not_judgable'],
                                'rule': '先逐份评分；严重业务违规优先解释，其余逐维比较。存在相反取舍且无预定目标权重时记tie并说明，不临时加权。'},
            'evidence_fields': ['response_quote', 'input_source_or_condition_locator', 'criterion_id', 'reason'],
            'recheck': '同一助手一次证据复核，保存原评、订正与理由；不是第二位专家，不计算评阅者间kappa。',
            'numeric_rule': '供应报价的MOP分项合计沿原目标容差1；无市场价格oracle。',
            'difference_from_old_rubric': '有边界且可实施的条件性方案不因核查尚未完成自动降为1分。旧分数与旧协议保持原样；新评分另存v2。'}
        actor_sources = read(PACK / 'checks/source_model_windows.json')['rows']
        actors = {r['reference_chain_id'].split('-r')[0]: r['organizations'] for r in actor_sources}
        macro = read(CP03 / 'protocol.json')
        native, project_rows = [], []
        for job in macro['jobs']:
            config = read(ROOT / job['config_path'])
            project_rows.append({'chain_id': job['chain_id'], 'case_id': job['case_id'],
                                 'project_group': job['project_group'], 'repeat': job['repeat'], 'arm': job['arm'],
                                 'initial_budget_HKD': config['scenario_budget'], 'state': 'not_executed',
                                 'awarded_contractor_id': None, 'contract_sum_HKD': None,
                                 'estimated_cost_HKD': None, 'simulated_actual_cost_HKD': None,
                                 'actual_progress': None, 'planned_progress': None,
                                 'milestone_ticks': {}, 'comparable_endpoint': None})
            for actor in actors[job['case_id']]:
                native.append({'chain_id': job['chain_id'], 'case_id': job['case_id'],
                               'project_group': job['project_group'], 'repeat': job['repeat'], 'arm': job['arm'],
                               'organization_id': actor, 'canonical_action': None, 'selected_option_id': None,
                               'declared_cost_base_HKD': None, 'bid_price_HKD': None,
                               'markup_fraction': None, 'source_refs': [], 'state': 'not_executed'})
        assert len(native) == 144 and len(project_rows) == 72
        paired_native = [{'case_id': cid, 'repeat': rep, 'organization_id': actor,
                          'left_arm': 'D3', 'right_arm': 'S4', 'same_canonical_action': None,
                          'state': 'not_executed'}
                         for cid, aa in actors.items() for rep in [1, 2, 3] for actor in aa]
        assert len(paired_native) == 36
        discussion = deepcopy(read(CP02 / 'organization_blocks.json'))
        old_windows = read(old_study / 'windows.json')
        focus_rules = {
            'qualification': '资格资料的缺口须保留，既有能力与本包资格适用性分开；不将未知推出实际无资格，条件性参与可以成立。',
            'partner': '区分普通专业支持与需要共担投标责任的联合体；伙伴被建议/被接洽不等于资质、意愿、分工已获接受。',
            'cost': '成本与报价依据的真实性、临时报价/假设及风险边界要可解释；分项合计按原数值准则，不编造收到报价或历史成本。',
            'personnel': '人员档期与实际分配状态保持来源所给边界；企业总体人员/能力不代替本包承诺。',
            'controlled_source_status': '逐项使用受控核查状态：已核查只在限定对象/期间内成立，未决仍未决，被拒资料不写成已通过。',
        }
        organization_cards = []
        for block in discussion:
            w = old_windows[block['window_id']]
            rules = [
                ('L1', '行动与业务任务匹配', '根据原任务、公司资料和阶段允许行动判断参与、联合体、拒绝或方案；不拿单一枚举当唯一正确答案。'),
                ('L2', '本窗口关键业务问题', focus_rules[w['focus']]),
                ('L3', '原事项与核查状态', '按原条件的实际状态及强制性处理，重复业务事项去重，不把所有建议升级为硬门槛；保留明确的未决/通过/拒绝区别。'),
                ('L4', '方案或合理下一步', '有边界且具体的方案、协作/交付安排或有据等待/拒绝及重审触发条件；不因保守拒绝自动判优。'),
                ('L5', '取舍与责任安排', '说明任务支持的风险、资源、成本或责任取舍怎样进入最后决定；岗位意见不是新的对方回执。'),
            ]
            organization_cards.append({'window_id': w['window_id'], 'case_id': w['case_id'],
                'project_group': w['project_group'], 'company_id': w['company_id'], 'package_id': w['package_id'],
                'marker': w['marker'], 'focus': w['focus'], 'origin': w['origin'],
                'allowed_decision_labels_from_original_stage': w['stage_allowed_decisions'],
                'input_ref': str((old_study / 'windows.json').relative_to(ROOT)),
                'input_window_sha256': hashlib.sha256(json.dumps(w, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                'conditions': w['conditions'],
                'factors': [{'factor_id': fid, 'label': label, 'adequate_handling': rule,
                             'applicable': True, 'rating': None} for fid, label, rule in rules],
                'boundary': '仅按原归档任务与原输入判断，不追溯要求V2.5新字段；这些旧输出已见，v2追加内容标注属探索性。',
                'state': 'old_input_expectations_fixed_unscored'})
            block.update(evaluation_version='business-result-v2', O1_supported_unique_items=None,
                         O2_correctly_responded_items=None, O2_rate=None,
                         invalid_adoptions=[], state='source_selected_unscored',
                         business_task_card=w['window_id'])
        feedback = {'planned_executions': 72, 'source_projects': 6, 'windows_per_project': 2,
                    'F1': {'planned_pairs': 12, 'condition': 'permitted region: none vs actual own settlement', 'expected_actions': None},
                    'F2_region': {'planned_pairs': 12, 'condition': 'restricted region: none vs actual own settlement', 'expected': 'do not bypass region restriction'},
                    'F2_amount': {'planned_pairs': 24, 'condition': 'both regions: actual vs same-count changed amount', 'expected': 'same action under current count-only rule'},
                    'input_oracle_gate': '在实际窗口装配后、受控重放前，按输入规则固定expected actions和主导约束；不得按观察结果剔除。',
                    'source_event_ids': None, 'results': None,
                    'boundary': '确定性规则响应，不是LLM财务学习。'}
        addendum = {'version': 'business-result-measurement.v2', 'date': '2026-11-12',
                    'status': 'measurement_addendum_prepared_before_new_calls_not_run_authorization',
                    'parent_input_and_runtime_protocols_unchanged': True, 'source_sha256': before,
                    'primary_by_RQ': {'RQ1': ['D1', 'D2'], 'RQ2': ['O2', 'O4'], 'RQ3': ['F1', 'F2'], 'RQ4': ['T2']},
                    'supporting': ['D3', 'D4', 'O1', 'O3', 'T1', 'T3', 'T4'],
                    'legacy_registered_targets': {'CP01': 'strict source+role+prerequisite consistency remains reported separately',
                                                  'CP03': 'cost deviation vs initial budget retained as T3 secondary and protocol-history note'},
                    'revision_reason': 'User requested business results and meaningful intermediate outcomes, not engineering flow as thesis focus.',
                    'before_any_new_provider_request': '检查本补充清单哈希与父协议哈希；原运行器不自动解释新指标，分析须显式使用v2，不改输出提示。',
                    'old_material': 'CP00/旧S-D3等已见材料的v2标注明确为探索性；旧评分不覆盖。',
                    'engineering_appendix_only': ['parse/schema accepted status', 'retry/recovery', 'interface/hash checks', 'detailed failure accounting'],
                    'provider_requests': 0, 'formal_macro_submissions': 0, 'budget_change': 0, 'ratings_completed': 0}
        save('metrics.json', dictionary())
        save('task_cards.json', cards)
        save('response_ratings_template.json', ratings)
        save('rubric.json', rubric)
        save('discussion_template.json', discussion)
        save('organization_task_cards.json', organization_cards)
        save('native_decision_template.json', native)
        save('native_D3_S4_pairs.json', paired_native)
        save('project_outcomes_template.json', project_rows)
        save('feedback_design.json', feedback)
        save('evaluation_addendum.json', addendum)
        summary = {'status': 'definitions_and_empty_templates_complete_not_results', 'dimensions': 4,
                   'metrics': 14, 'task_cards': 48, 'source_project_groups': 24,
                   'prelisted_factors': 252, 'first_response_slots': 192, 'factor_rating_slots': 1008,
                   'discussion_blocks': 12, 'native_decision_slots': 144, 'native_primary_pairs': 36,
                   'old_organization_task_cards': 12, 'old_organization_prelisted_factors': 60,
                   'project_chain_outcome_slots': 72, 'ratings_completed': 0, 'provider_requests': 0,
                   **counts}
        assert all(sha(ROOT / path) == digest for path, digest in before.items())
        save('preparation_summary.json', summary)
        manifest = {'status': 'measurement_addendum_sealed_not_run_authorization',
                    'builder_sha256': sha(Path(__file__)), 'parent_sha256': before,
                    'files': {p.name: sha(p) for p in sorted(OUT.glob('*.json')) if p.name != 'manifest.json'}}
        save('manifest.json', manifest)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--revise-unexecuted-draft', action='store_true')
    REVISE_UNEXECUTED_DRAFT = parser.parse_args().revise_unexecuted_draft
    main()
