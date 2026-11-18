"""Source-bound description of all retained CP00 first answers; no new judging."""
from collections import Counter
from copy import deepcopy
import json
from statistics import mean
from pathlib import Path

from review_capstone_all_20261113 import ROOT, MASTER, read, save, sha
from capstone_project_analysis_20261113 import project_pairs, summary, stratified_bootstrap

TAG='CP00_first_review_complete_001'
SOURCE=MASTER/'analysis'/TAG/'CP00'
OUT=MASTER/'analysis'/TAG


def main():
    pins={}
    summaries={}
    condition_summaries={}
    review_states=Counter()
    for metric in ['D1','D2']:
        path=SOURCE/f'{metric}_v2_5_minus_v2_4.json'
        r=read(path)
        assert r['pending_readable_content_reviews_or_rechecks']==0
        summaries[metric]=r['cohort_estimate']
        pins[str(path.relative_to(ROOT)).replace('\\','/')]=sha(path)
        sp=SOURCE/f'{metric}_slot_values.json'
        slots=read(sp)
        assert len(slots)==192 and sum(s['value'] is not None for s in slots)==188
        pins[str(sp.relative_to(ROOT)).replace('\\','/')]=sha(sp)
        if metric=='D1':
            for s in slots:
                if s['value'] is None:
                    review_states[s['status']]+=1
                    continue
                gp=ROOT/s['grade_path']
                assert sha(gp)==s['grade_sha256']
                pins[s['grade_path']]=sha(gp)
                cp=MASTER/'business_recheck/CP00'/gp.name
                if cp.exists():
                    assert read(cp)['complete'] and read(cp)['initial_record_sha256']==sha(gp)
                    pins[str(cp.relative_to(ROOT)).replace('\\','/')]=sha(cp)
                else:
                    assert read(gp)['evidence_recheck']['complete']
        paired=project_pairs(slots,left='v2_5',right='v2_4')
        condition_summaries[metric]={}
        for variant in ['full','missing_core']:
            cases=[]
            for p in paired:
                left=p['conditions']['v2_5'][variant]['observed_mean']
                right=p['conditions']['v2_4'][variant]['observed_mean']
                cases.append({**p,'left_mean':left,'right_mean':right,
                              'difference':left-right if left is not None and right is not None else None})
            condition_summaries[metric][variant]={
                'analysis_identity':'separate information-condition contrast, not reweighting the primary mixed-condition estimate',
                'project_equal_means':{a:mean(p['conditions'][a][variant]['observed_mean'] for p in paired
                    if p['conditions'][a][variant]['observed_mean'] is not None) for a in ['v2_4','v2_5']},
                'uncertainty':stratified_bootstrap(cases)}
    d1slots=read(SOURCE/'D1_slot_values.json')
    # Entire low-information stratum, chosen by input condition alone. This is
    # deliberately broader than a subjective subset of borderline phrases.
    stress=[]
    for direction in ['unfavourable_to_v2_5','favourable_to_v2_5']:
        rows=deepcopy(d1slots)
        changed=[]
        for s in rows:
            if s['variant']=='missing_core' and s['value'] is not None:
                s['value']=float((s['arm']=='v2_5')==(direction=='favourable_to_v2_5'))
                changed.append(s['grade_path'])
        pairs=project_pairs(rows,left='v2_5',right='v2_4')
        stress.append({'direction':direction,'hypothetical_observed_slots':len(changed),
                       'selected_grade_paths':changed,'summary':summary(pairs)})
    missing=[{k:s[k] for k in ['window_id','arm','repeat','status','response_path','response_sha256']}
             for s in d1slots if s['value'] is None]
    flags=MASTER/'manual_labels/CP00_D1_ambiguous_reading_flags_001.json'
    pins[str(flags.relative_to(ROOT)).replace('\\','/')]=sha(flags)
    for p in [MASTER/'data_quality/CP00_EXPAND15_retained_architectural_practice_001.json',
              MASTER/'data_quality/CP00_explicit_quotation_total_rows_001.json']:
        pins[str(p.relative_to(ROOT)).replace('\\','/')]=sha(p)
    raw_counts={a:dict(Counter(s['value'] for s in d1slots if s['arm']==a)) for a in ['v2_4','v2_5']}
    evidence={'planned_slots':192,'readable_first_answers_graded_and_rechecked':188,
        'fixed_project_groups':24,'missing_first_answers':missing,
        'raw_answer_D1_counts_not_project_equal_rates':raw_counts,
        'first_answer_primary':summaries,'separate_information_conditions':condition_summaries,
        'whole_missing_information_stratum_D1_stress':stress,
        'stress_identity':'Post-hoc hypothetical replacement of every readable missing_core D1 score in both directions; no original score changes, no new semantic labels, no confidence interval.',
        'older_13_manual_borderline_flags_not_exhaustive':True,
        'additional_full_and_missing_cohort_semantic_boundary_audit_still_required':True,
        'repair_answers_not_in_first_estimate':48,'CP00_CP01_same24_projects_not_independent_replications':True,
        'reviewer':'Same author-assisting AI participating in design; not independent, professional expert, or blinded validation',
        'D3_D4_not_collected_for_CP00':True,'new_provider_calls':0,'initial_scores_changed':False}
    save(OUT/'business_description_001.json',evidence)
    lines=['# CP00首轮业务结果（探索性旧材料）','',
        '固定24个项目×两种资料条件×两版×两次重复，共192个首轮槽位。188份可读回答全部完成作者辅助AI业务评分及证据复核；4份历史未知保留缺失、未重放。程序接受与否不直接决定业务分数。','',
        '| 指标 | V2.5−V2.4，项目等权 | 探索性95%区间 | 4份缺失双向极端界限 |','|---|---:|---:|---:|']
    for metric,title in [('D1','行动适当率'),('D2','正确事项覆盖率')]:
        p=summaries[metric]['paired'];ci=summaries[metric]['uncertainty']['exploratory_percentile95'];bo=p['all_planned_slot_bounds']
        lines.append(f'| {title} | {100*p["project_equal_difference"]:+.2f}个百分点 | [{100*ci[0]:.2f}, {100*ci[1]:.2f}]个百分点 | [{100*bo[0]:.2f}, {100*bo[1]:.2f}]个百分点 |')
    lines += ['', '重复先平均，完整/缺失资料各半权重，再对24个配对项目等权；按四角色分层进行20,000次bootstrap，seed=20261112。缺失界限是对原192个槽位作双向极端填充的数学界限，不是观测分数或置信区间。20个项目的全部重复槽位完整，完整项目敏感性和逐项目/复用企业剔除结果保存在分析JSON。','',
        '| 单独资料条件 | D1差，百分点 | D2差，百分点 |','|---|---:|---:|']
    for v,label in [('full','完整资料'),('missing_core','核心资料缺失')]:
        lines.append(f'| {label} | {100*condition_summaries["D1"][v]["uncertainty"]["difference"]:+.2f} | {100*condition_summaries["D2"][v]["uncertainty"]["difference"]:+.2f} |')
    bo=[s['summary']['all_planned_slot_bounds'][i] for i,s in enumerate(stress)]
    lines += ['',f'将所有可读的核心资料缺失条件D1评分同时替换为对V2.5最不利/最有利的假设值，并连同历史缺失作极端填充，混合条件差异范围为[{100*bo[0]:.2f}, {100*bo[1]:.2f}]个百分点。这是按输入条件全覆盖的事后压力分析，覆盖范围远大于13项旧歧义标记，不能当作真实重评分或统计区间，也不能据此称所有表述都存在歧义。完整队列的具体语义边界补充审查仍需完成。','',
        '资料缺失不自动要求拒绝。有限提案、适当暂缓和有据拒绝按各角色分支评价；公司名称不能证明实际经营能力，但残留字段中的实际业务背景仍须计入。例如EXPAND-15的缺失资料仍保留“1980年起在澳门开展建筑实践”，已单列数据边界；EXPAND-14报价数组末行“合计”不作为另一项费用重复求和。','',
        '本批有两版均低分、部分无差异以及V2.5仍有错误的回答。例如EXPAND-23完整资料V2.5-r2，六项合计29,080,000 MOP而报告29,050,000 MOP，保留30,000 MOP差异，S6记矛盾。较低报价本身不计优点。','',
        '本批为先前已见材料的探索性补充业务评价，与CP01使用相同24个项目，不能合成48个独立项目，不能称独立重复验证。CP00未按新量表采集D3、D4，不回填或从总分推算。48份历史修复回答另行评价，不替换首轮、也不当新增案例。','',
        '评阅者为参与研究设计的同一作者辅助AI，不是独立专家或真实盲评。本文结果描述受控任务中的业务内容，不证明真实中标、项目利润、投资回报或实际工程改善。','',
        '可复算来源：`analysis/CP00_first_review_complete_001/CP00/`；逐槽分数、逐项目差异、独立缺失清单和全条件压力分析见同目录上一级`business_description_001.json`；证据哈希见`business_report_manifest_001.json`。','']
    report=MASTER/'CP00首轮业务结果_001.md'
    assert not report.exists()
    report.write_text('\n'.join(lines),encoding='utf-8')
    for p in [report,OUT/'business_description_001.json',Path(__file__)]:
        pins[str(p.relative_to(ROOT)).replace('\\','/')]=sha(p)
    save(OUT/'business_report_manifest_001.json',{'source_sha256':pins,'new_provider_calls':0,'initial_scores_changed':False})
    print(json.dumps({'report':str(report.relative_to(ROOT)),'D1_missing_stratum_stress_bounds':bo,'readable_rechecked':188},ensure_ascii=False))


if __name__=='__main__':
    main()
