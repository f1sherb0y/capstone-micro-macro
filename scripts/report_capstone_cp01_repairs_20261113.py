"""Paper-facing selected-repair description and transparent rating correction trail."""
from pathlib import Path
from statistics import mean

from review_capstone_all_20261113 import ROOT, MASTER, read, save, sha, source

SOURCE=MASTER/'analysis/CP01_repair_content_002'


def write_new(path,text):
    if path.exists(): assert path.read_text(encoding='utf-8')==text
    else: path.write_text(text,encoding='utf-8')


def main():
    doc=read(SOURCE/'summary_001.json')
    manifest=read(SOURCE/'manifest.json')
    assert doc['actual_repair_calls']==47 and manifest['effective_revisions_included']==3
    pairs=read(SOURCE/'answer_pairs.json')
    traces=[]
    for r in pairs:
        p0=source('CP01',r['window_id'],r['arm'],r['repeat'],1)[2]
        p1=source('CP01',r['window_id'],r['arm'],r['repeat'],2)[2]
        traces.append({'window_id':r['window_id'],'arm':r['arm'],'repeat':r['repeat'],
            'before_response_sha256':r['before_response_sha256'],'after_response_sha256':r['after_response_sha256'],
            'unchanged_public_top_level_fields':[k for k in sorted(set(p0)|set(p1)) if k in p0 and k in p1 and p0[k]==p1[k]],
            'changed_public_top_level_fields':[k for k in sorted(set(p0)|set(p1)) if p0.get(k)!=p1.get(k)]})
    save(SOURCE/'public_field_comparison_audit_001.json',traces)
    # Every reported selected-repair point must equal its explicit source CSV/JSON rows.
    for metric,r in doc['metrics'].items():
        eligible=[p for p in pairs if p[metric+'_change'] is not None]
        assert len(eligible)==r['selected_answer_pairs']
        assert sum(r[k] for k in ['improved_answers','unchanged_answers','lower_answers'])==len(eligible)
        assert abs(mean(p[metric+'_after']-p[metric+'_before'] for p in eligible)
                   -(r['raw_answer_after_mean']-r['raw_answer_before_mean']))<1e-12
    lines=['# CP01 修复后回答：独立于首轮的业务评价','',
        '已逐份完成全部 47 份实际返回的修复后回答评分与同助手证据复核，并与同一回答的首轮原件配对。涉及 22 个来源项目组；45 份来自缺失资料条件、2 份来自完整资料条件，版本分别为 V2.4 的 25 份和 V2.5 的 22 份。25 份预选 repeat=1 回答另作 D3/D4 细评，覆盖 18 个来源项目。','',
        '这些回答由既定校验规则触发修复，不是随机抽取的修复效果试验；两个版本的修复子集不同，不能据此比较版本优胜。实际使用 47 次已授权修复请求；上限 48 的最后一份未用额度不等于缺失的第 48 份修复回答，也不补造评分。','',
        '## 观察到的变化','',
        '先在每个来源项目内平均其实际被选中修复的回答，再对来源项目等权。这里的均值仅描述修复子集，不替代首轮主分析的完整／缺失资料等权。D1/D2 单位为百分比／百分点，D3/D4 为 0–2 有序分。','',
        '| 指标 | 回答对 / 来源项目 | 修前项目均值 | 修后项目均值 | 项目等权变化 | 改善 / 不变 / 下降的回答对 |',
        '|---|---:|---:|---:|---:|---:|']
    for m,r in doc['metrics'].items():
        scale=100 if m in {'D1','D2'} else 1
        digits=1 if scale==100 else 3
        lines.append(f"| {m} | {r['selected_answer_pairs']} / {r['selected_source_projects']} | {r['project_equal_before_mean']*scale:.{digits}f} | {r['project_equal_after_mean']*scale:.{digits}f} | {r['project_equal_change']*scale:+.{digits}f} | {r['improved_answers']} / {r['unchanged_answers']} / {r['lower_answers']} |")
    lines += ['',
        'D1 的原始回答计数为 29/47 适当 → 40/47 适当，11 份由不适当变为适当，仍有 7 份不适当。该原始回答比例变化与项目等权变化采用不同权重，不能混称。D2 有 11 份事项覆盖增加、35 份不变、1 份下降。','',
        'D1 的项目等权变化为 +15.9 个百分点，按被选中来源项目、角色分层重采样的探索性 95% 区间为 [5.7, 27.3]；D2 为 +3.5 个百分点，区间为 [0.8, 6.4]。这些区间仅反映当前选择性子集内部的不确定性，不能消除触发选择偏差或同助手评阅偏差。逐项目及逐复用企业剔除结果保留在源 JSON。','',
        'D3 与 D4 的 25 个回答对均没有观察到分数变化。这与本批主要修正事实表述或算术、没有充分补写实施组织与取舍内容相符；没有观察到变化不证明未来或总体等效，也不能用退化的 [0,0] 重采样区间声称零效应已被证明。','',
        '## 仍保留的业务问题与负向例子','',
        '- EXPAND-01 缺失资料 V2.5 repeat=2：修复说明声称总价已改，但正文总价仍为 22,620,000 MOP，分项复算为 22,650,000 MOP；3 万差额仍记事项矛盾。',
        '- EXPAND-07 缺失资料 V2.5 repeat=2：总额已改为可复算的 2,360,000 MOP，但可选审核门槛的前后措辞和管理费计提比例仍有不一致，事项不因此全部记正确。',
        '- EXPAND-12 缺失资料 V2.4 repeat=2：把“既有承建定位”改成“拟以承建商角色”，仍未回到题目要求的独立监督角色，职责冲突保留。',
        '- EXPAND-18 缺失资料 V2.4 repeat=2、EXPAND-21 缺失资料 V2.5 repeat=2：仍将名称推成实际仪器设备业务或工程管理业务，保留来源越界。',
        '- EXPAND-02 缺失资料 V2.4 repeat=1 的一项覆盖下降：原文把商业办公类型与本次承建任务定位相联系；修后删去该解释，主要只剩值得保留意向的泛化判断。实际解释内容减少的记录保留，没有为使所有修复正向而改分。','',
        '## 评分订正与效度边界','',
        '配对汇总审查发现 3 份修后初评存在尺度不一致，已追加 3 份订正记录，涉及 5 个事项／细评分值。原评、原复核、订正理由、精确引文和原始回答全部保留；首轮评分未改。涉及的组织架构或供货协调内容没有变化，修后初评却额外要求更细岗位、特定商品类别，或把主要范围错误扩散到其他维度，不能把这种评阅变化当成模型退步。','',
        'EXPAND-03 的设计职能组织事项恢复为正确；EXPAND-07 完整资料的有限供货协调范围恢复为正确；EXPAND-09 的双方职能事项恢复为正确、项目因素恢复为部分、整体实施性恢复为 1 分，其主要行动仍不适当。后一例与 EXPAND-03 的 content 在修前后逐字相同；EXPAND-07 保持同一协调型方案，主要变化为档案与能力措辞。','',
        '此处仍是参与设计的同一助手作者辅助 AI 评价，曾参照首轮评阅记录核对尺度，不是独立专家、真盲评或第二评阅者。47 份的原始初评汇总另保留为历史版本 001；论文引用本次带订正的版本 002。订正不会反向改变原始回答、首轮主结果或模型调用计数。','',
        '## 可复算入口','',
        '- [最终修复子集汇总](analysis/CP01_repair_content_002/summary_001.json)。',
        '- [逐回答配对 CSV](analysis/CP01_repair_content_002/answer_pairs.csv) / [来源项目级 CSV](analysis/CP01_repair_content_002/selected_project_metric_pairs.csv)。',
        '- [全部源文件及订正哈希](analysis/CP01_repair_content_002/manifest.json)。',
        '- [外显字段修前修后变化审计](analysis/CP01_repair_content_002/public_field_comparison_audit_001.json)。',
        '- [评分订正的作者依据](manual_labels/CP01_repair_consistency_revisions_001.json)，对应 business_revision/CP01 下 3 份追加记录。','',
        '本工作包的 47 份修复评分已齐。其他队列评分、事项构成及宏观／反馈结果仍须继续完成，不能据本子集宣称全部实验结束。','']
    report=MASTER/'CP01修复后业务结果_001.md'
    write_new(report,'\n'.join(lines))
    save(MASTER/'CP01_repair_analysis_revision_notice_001.json',{
        'historical_initial_review_summary':'analysis/CP01_repair_content_001/manifest.json',
        'historical_manifest_sha256':sha(MASTER/'analysis/CP01_repair_content_001/manifest.json'),
        'current_effective_summary':'analysis/CP01_repair_content_002/manifest.json',
        'current_manifest_sha256':sha(SOURCE/'manifest.json'),
        'explicit_revised_answer_reviews':3,'explicit_revised_items':5,'first_answer_grades_changed':0,
        'source_note_sha256':sha(MASTER/'manual_labels/CP01_repair_consistency_revisions_001.json'),
        'report_sha256':sha(report),'new_model_calls':0})
    save(SOURCE/'report_source_001.json',{'summary_sha256':sha(SOURCE/'summary_001.json'),
        'report_sha256':sha(report),'script_sha256':sha(__file__),'new_model_calls':0})
    print('Saved selected-repair business report and explicit correction/history references.')


if __name__=='__main__': main()
