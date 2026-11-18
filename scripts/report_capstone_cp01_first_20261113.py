"""Describe all completed CP01 first-answer labels; never mix repair results."""
from collections import Counter
from datetime import datetime, timezone

from capstone_cp_common_20261112 import ROOT, read, save, sha
from review_capstone_all_20261113 import MASTER


def main():
    index_path=MASTER/'response_index_CP01_first_review_complete_001.json'
    rows=[r for r in read(index_path)['rows'] if r['cohort']=='CP01']
    assert len(rows)==192 and sum(r['readable_outward_json'] for r in rows)==190
    assert all(r['review_state']=='evidence_rechecked' for r in rows if r['readable_outward_json'])
    factor_counts={a:Counter() for a in ['v2_4','v2_5']}
    ordinal={m:{a:Counter() for a in factor_counts} for m in ['D3','D4']}
    grade_hashes={}
    for row in rows:
        arm=row['arm']
        if not row['readable_outward_json']:
            if row['repeat']==1:
                for metric in ordinal: ordinal[metric][arm]['unknown_no_score']+=1
            continue
        path=MASTER/'business_review/CP01'/f"{row['window_id']}-{arm}-r{row['repeat']}-a1.json"
        grade=read(path)
        assert grade['response_sha256']==row['response_sha256']
        factor_counts[arm].update(f['rating'] for f in grade['factor_ratings'])
        grade_hashes[str(path.relative_to(ROOT)).replace('\\','/')]=sha(path)
        if row['repeat']==1:
            for metric in ordinal:
                score=grade['detailed'][metric]['score'];assert score in [0,1,2]
                ordinal[metric][arm][str(score)]+=1
    figures=MASTER/'figures/CP01_first_review_001'
    metrics=read(figures/'metric_summary.json')
    save(MASTER/'CP01_first_review_business_summary_001.json',{'at_UTC':datetime.now(timezone.utc).isoformat(),
        'first_answer_slots':192,'readable_and_evidence_rechecked':190,'unknown_no_scores':2,
        'first_answer_only':True,'repair_scores_included':False,'metrics':metrics,
        'raw_factor_state_counts':{a:dict(c) for a,c in factor_counts.items()},
        'raw_repeat1_ordinal_counts':{m:{a:dict(c) for a,c in arms.items()} for m,arms in ordinal.items()},
        'source_index_sha256':sha(index_path),'grade_sha256':grade_hashes,
        'figure_manifest_sha256':sha(figures/'manifest.json'),'report_script_sha256':sha(__file__),
        'reviewer':'Same assistant participating in design; not independent/blinded; preselected order-swap pending',
        'new_model_calls':0,'new_grades':0})
    lines=['# CP01首轮业务结果：24源组的工作版本','',
        '190份可读首轮已逐项评分并完成一次同助手证据复核；192个计划槽位中的2次未知不重放、不造分。本表比较V2.5与V2.4的版本差异，不是S／D3／S4组织流程比较。修复回答未替换首轮，也未混入本表。', '',
        '## 项目配对结果','',
        '重复内先聚合，完整／缺资料两情景等权，再项目等权。D1／D2用24项目；D3／D4按预定repeat=1细评，两项目的一个情景因未知不能构成完整配对，因此观测配对n=22。区间为按角色分层、项目配对重采样20000次（seed=20261112）的探索性95%百分位区间。', '',
        '| 指标 | V2.4项目均值 | V2.5项目均值 | 差值V2.5−V2.4 | 探索性95%区间 | 配对项目n |',
        '|---|---:|---:|---:|---:|---:|']
    names={'D1':'适当行动比例','D2':'正确事项覆盖','D3':'可实施性（0—2）','D4':'权衡推理（0—2）'}
    for r in metrics:
        lo,hi=r['exploratory_percentile95'];m=r['metric']
        if m in ['D1','D2']:
            vals=[f"{r['v2_4_mean']:.2f}%",f"{r['v2_5_mean']:.2f}%",f"{r['difference']:+.2f}个百分点",f'[{lo:.2f}, {hi:.2f}]个百分点']
        else:
            vals=[f"{r['v2_4_mean']:.3f}",f"{r['v2_5_mean']:.3f}",f"{r['difference']:+.3f}分",f'[{lo:.3f}, {hi:.3f}]分']
        lines.append('| '+names[m]+' | '+' | '.join(vals)+f" | {r['paired_projects']} |")
    lines += ['', 'D1／D2是项目等权后的比例，不是把所有原始回答或事项直接拼成一个成功率。D3／D4等级均值与分差只作有序评分描述，不是精确连续商业效用。D4区间含0，且存在量表天花板，不写“已证明全部四维改善”。', '',
        '![CP01首轮项目配对差](figures/CP01_first_review_001/CP01_first_answer_effects.png)', '',
        '[SVG图](figures/CP01_first_review_001/CP01_first_answer_effects.svg) · [作图数据](figures/CP01_first_review_001/figure_data.csv) · [逐项目描述CSV](analysis/CP01_first_review_complete_001/CP01/rechecked_case_descriptions.csv)', '',
        '## 缺失与影响分析','',
        '| 指标 | 全24计划项目的缺失赋值边界 | 逐项目剔除后的均值差范围 |', '|---|---:|---:|']
    for r in metrics:
        low,high=r['all24_planned_slot_missing_bounds'];a,b=r['leave_one_project_out_range']
        unit='个百分点' if r['metric'] in ['D1','D2'] else '分'
        lines.append(f"| {r['metric']} | [{low:.3f}, {high:.3f}]{unit} | [{a:.3f}, {b:.3f}]{unit} |")
    lines += ['', '缺失边界依固定量表范围向两个版本作相反有利／不利填充，针对全部24个计划项目；它不是实际评分，也不是抽样区间。D3／D4的观测点与区间针对22个完整配对，人口不同，不能要求观测点一定落在全24项目的数学缺失边界内。完整重复槽位和逐复用企业剔除结果分别保存在四份指标JSON中，不依据效应方向删除案例。', '',
        '## 事项构成与等级分布','',
        '| 版本 | correct | partial | missing | contradicted | 不可判断 |', '|---|---:|---:|---:|---:|']
    for arm,c in factor_counts.items():
        lines.append('| '+arm+' | '+' | '.join(str(c[s]) for s in ['correct','partial','missing','contradicted','not_judgable'])+' |')
    lines += ['', '上表是已评首轮原始事项计数；不同角色每份有5或6个事项，且两次未知均在V2.4。它用于描述错误构成，不把这些事项当独立样本；主D2仍按每回答归一化及项目配对公式。', '',
        '| 指标 | 版本 | 0分 | 1分 | 2分 | 未知无评分 |', '|---|---|---:|---:|---:|---:|']
    for metric,arms in ordinal.items():
        for arm,c in arms.items(): lines.append('| '+metric+' | '+arm+' | '+' | '.join(str(c[s]) for s in ['0','1','2','unknown_no_score'])+' |')
    lines += ['', '等级表仅含预定repeat=1回答，保留完整／缺资料两情景。它是回答级描述，不改变项目级统计单位。', '',
        '## 当前可以写的结论与边界','',
        '在该固定24源组、当前模型／提示和作者辅助AI量表下，V2.5的适当行动、正确事项覆盖和可实施性评分的观测项目差为正；本工作版本相应探索区间未含0。权衡推理的差异较小、区间触及0，不据此宣称等效、非劣或普遍改善。', '',
        '评分中仍保留V2.5的无来源现有业务／制造能力断言、可选核查升级、项目特点遗漏和施工方案泛化等反例。尚未完成的行动构成、资料条件差中差及预选顺序互换不能由这张均值表替代，也不能据此称改善不是由行动构成变化造成。', '',
        '初评包可见版本标识，助手参与设计；一次引文复核和项目重采样不构成独立专家验证或去偏保证。见[评阅与输入边界](评价与数据边界记录_001.md)。预选顺序互换及单列修复分析完成后须版本化更新结论，不覆盖原评和本结果。CP00、CP08、CP07及宏观／反馈仍分别推进，本批不代替整个Capstone验证。', '',
        '[逐项汇总与来源哈希](CP01_first_review_business_summary_001.json) · [分析清单](analysis/CP01_first_review_complete_001/CP01/analysis_manifest.json) · [首轮去向索引](business_readiness_CP01_first_review_complete_001.json)', '']
    target=MASTER/'CP01首轮业务结果_001.md'
    if target.exists(): raise ValueError('Existing CP01 report; keep version history')
    target.write_text('\n'.join(lines),encoding='utf-8')
    save(figures/'visual_check_001.json',{'png_sha256':sha(figures/'CP01_first_answer_effects.png'),
        'inspected_with':'view_image','observed':'All four point estimates and intervals visible; separate units; labels/caption fully visible without overlap; working status and review limitation visible.',
        'new_model_calls':0})
    print({'CP01_first_reviews_and_rechecks':190,'planned_first_slots':192,'unknown':2,'report_saved':str(target),'new_calls':0})


if __name__=='__main__': main()
