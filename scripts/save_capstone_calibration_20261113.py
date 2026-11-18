"""Persist six previously read calibration blocks and explicit rubric lessons.

The lessons are authored by the assistant after reading all12 outward answers.
This creates no model response, formal score or additional evaluation sample.
"""
import json

from capstone_cp_common_20261112 import ROOT, CP02, read, save, sha

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-13_总实验收尾/calibration'

LESSONS = {
    'SOURCE-01-missing_core': {
        'quotes': {'v2_4': '与本公司作为澳门本地工程顾问的定位相符', 'v2_5': '监理角色与本公司工程顾问的业务方向对口'},
        'lesson': '两份都在经营范围为空时用实际工程顾问业务定位支持决定；角色指派和公司名不提供既有业务能力依据。条件性参与本身可合理，但其来源依据要独立判断，不能因给出未知声明就忽略另一句事实断言。'},
    'SOURCE-02-missing_core': {
        'quotes': {'v2_4': '相关安排均为拟议计划', 'v2_5': '公司现有产品目录、库存、本地团队及历史采购成本均属未知'},
        'lesson': '缺档案允许有边界供货方案。拟议分批配送、报审、质量和保修安排可支持可行性；不能仅因未核实资源自动降分。验证失败状态不替代内容判断，正式提交前的审慎安排也不能仅凭关键词当无依据门槛。'},
    'SOURCE-04-missing_core': {
        'quotes': {'v2_4': '我司计划由我方担任设计主导并承担整体设计责任', 'v2_5': '单独投标在评标中难以证明本地经验与团队档期'},
        'lesson': '两种不同意向不自动构成优劣。应区分设计角色计划、把名称当已知能力的简称、缺少证明与实际无能力；组合体要看共享责任及实际商业取舍，不能只按bid或consortium标签给分。无输入的评标效果断言需保留不确定性，参保人数不证明本包档期。'},
    'SOURCE-03-full': {
        'quotes': {'v2_4': '公司档案业务范围为建筑总承包', 'v2_5': '在两项核查落实前不提交投标'},
        'lesson': '经营方向有明确档案依据，但不等于资格证明或实际人员已落实。两版均保留两项未决原条件；可对合理参与给正面判断，同时把仅列原则、缺少人员或实施细节的因素记partial，不由程序复核状态决定业务分。'},
    'SOURCE-02-full': {
        'quotes': {'v2_4': '上述金额均为暂列假设，非已收到供应商报价', 'v2_5': '不构成正式提交'},
        'lesson': '暂列数值可接受但需逐项核算，并保留未知与责任边界。不能以报价更低判商业更好，不能将无市场价格oracle解释成所有暂定分项都无效。原两供应核查并非强制提交条件，评价语义和理由而非只看暂缓措辞。'},
    'SOURCE-01-full': {
        'quotes': {'v2_4': '具体人员配置以提交前确认的岗位计划为准', 'v2_5': '人员配置与报价均为暂定方案'},
        'lesson': '完整档案中的总体人员与专业方向可引用，但不能升级为本包已派驻。可行性按具体组织、检查与交付逻辑判断；等待核查不自动为1分，空泛暂定也不自动为2分。项目针对性必须有条件到安排的联系。'},
}


def main():
    selection_path = CP02 / 'calibration_selection.json'
    selection = read(selection_path)
    assert len(selection) == 6 and set(LESSONS) == {r['window_id'] for r in selection}
    evidence, source_hashes, groups = [], {}, set()
    for row in selection:
        directory = ROOT / row['source_root']
        inputs = directory / 'windows.json'
        window = read(inputs)[row['window_id']]
        groups.add(window['project_group'])
        source_hashes[str(inputs.relative_to(ROOT)).replace('\\', '/')] = sha(inputs)
        answers = []
        for arm in ['v2_4', 'v2_5']:
            path = directory / 'run/jobs' / f"{row['window_id']}-{arm}-r1" / 'attempt-1.json'
            record = read(path)
            payload = record.get('parsed')
            assert isinstance(payload, dict)
            outward = {k: v for k, v in payload.items() if k not in {'thoughts', 'company_assessment'}}
            quote = LESSONS[row['window_id']]['quotes'][arm]
            assert quote in json.dumps(outward, ensure_ascii=False)
            source_hashes[str(path.relative_to(ROOT)).replace('\\', '/')] = sha(path)
            answers.append({'arm': arm, 'response_path': str(path.relative_to(ROOT)).replace('\\', '/'),
                'response_sha256': sha(path), 'program_status_not_used_as_quality_score': record['status'], 'reviewed_quote': quote})
        evidence.append({'window_id': row['window_id'], 'role': window['role'], 'project_group': window['project_group'],
            'source_window_ref': str(inputs.relative_to(ROOT)).replace('\\', '/') + '#' + row['window_id'],
            'input_scope_present': bool(window['facts']['real_input_dossier']['company']['business_scope']),
            'responses': answers, 'rubric_lesson': LESSONS[row['window_id']]['lesson']})
    save(OUT / 'six_block_calibration.json', {'state': 'calibration_reading_complete_not_formal_model_quality_results',
        'selected_blocks': 6, 'outward_answers_read': 12, 'source_project_groups': len(groups),
        'reviewer': 'Same author-assisting AI, involved in development; not independent or blinded',
        'rubric_version_unchanged': 'business-result-rubric.v2', 'formal_dataset_score_count': 0,
        'lessons': evidence, 'source_sha256': source_hashes, 'new_paid_calls': 0,
        'constructed_boundary_examples_not_model_outputs': [
            {'illustration': '资料未提供，所以该公司一定无资质，拒绝。', 'criterion': 'D1不适当的未知转无能力；不是本次真实模型输出。'},
            {'illustration': '暂缓正式承诺，先核实指定岗位档期；同时提出由设计负责人协调顾问复核、形成资料清单的拟议工作。',
             'criterion': '有据暂缓可支持D1及可行性高分，仍需任务与来源符合；不是本次真实模型输出。'},
            {'illustration': '等待全部资料。', 'criterion': '缺具体原因、下一步和重审条件，不能仅因保守就给高分；不是本次真实模型输出。'}]})
    report = '''# 六块评分校准记录

已按原预选6个旧窗口阅读两版repeat=1的12份对外回答，涉及4个原项目组。不是6个独立新项目，不进入正式质量统计，也不当专业准确率。逐例原文、输入位置及哈希见six_block_calibration.json。

校准确认沿用原v2量表，不改正式任务或评分锚点：未知不是无能力，也不支持从名字补回业务方向；条件性方案可得高分但需实质安排；等待／拒绝不自动加分；方案细节不足按相应事项partial，而非把所有来源合理的回答视为充分；D1与D2逐因素判断，不由程序accepted决定；不同意向、较低报价或组合体枚举本身不是质量oracle。

报价暂列与实际收到供应商报价分开，人员总数与本包派驻分开，原强制与非强制条件按输入保留。既有材料上的简称或预测性措辞需指出歧义，不在正式评分时按版本使用不同标准。

示意反例已明确标为人为构造的量表说明，不伪装为模型输出。原24的4份初评保留，需在此统一量表下复核后才纳入正式指标。所有正式评分仍须逐项精确引文与证据复核，未由本校准自动生成任何正式分数。
'''
    path = OUT / '校准记录.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_text(encoding='utf-8') == report
    else:
        path.write_text(report, encoding='utf-8')
    print(json.dumps({'calibration_blocks': 6, 'outward_answers_read': 12, 'source_projects': len(groups), 'formal_scores_created': 0, 'new_paid_calls': 0}))


if __name__ == '__main__':
    main()
