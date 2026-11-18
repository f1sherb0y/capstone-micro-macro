"""Describe all frozen first-answer preferences, preserving original review labels."""
from collections import Counter, defaultdict
import json
from review_capstone_cp01_pairs_20261113 import OUT, packet
from review_capstone_all_20261113 import MASTER, ROOT, read, save, sha


def main():
    summary=read(OUT/'summary_001.json')
    assert summary['completed_pairs']==48 and summary['paired_readable_answers']==46
    rows=[]; pins={}; crosswalk=[]
    bindings=read(MASTER/'order_check/CP01_001/source_binding.json')['pairs']
    for item in summary['rows']:
        path=OUT/'judgments'/f"{item['pair_id']}.json"; r=read(path); p=packet(item['pair_id'])
        assert r['packet_sha256']==sha(OUT/'packets'/path.name)
        pins[str(path.relative_to(ROOT))]=sha(path)
        if r['origin'].startswith('retained_original'):
            b=next(b for b in bindings if b['selection']['window_id']==r['window_id'])
            mapping={old_label:next(a['label'] for a in p['answers_in_frozen_order'] if a['source_arm']==arm)
                     for old_label,arm in zip(['A','B'],b['selection']['first_presentation_order'])}
            crosswalk.append({'pair_id':r['pair_id'],'original_judgment':r['authored_source_path'],
                'original_judgment_sha256':r['authored_source_sha256'],
                'original_reason_labels_to_current_labels':mapping,
                'reason_text_preserved':True,'preference_and_quotes_use_current_labels':True})
        rows.append(r)
    assert len(crosswalk)==12
    save(OUT/'retained_reason_label_crosswalk_001.json',{
        'purpose':'Retained reasons preserve ORIGINAL presentation labels; consult this mapping when reading them with current packets. No vote or rating changes.',
        'rows':crosswalk,'new_model_calls':0})
    groups=defaultdict(list)
    for r in rows: groups[r['project_group']].append(r)
    assert len(groups)==24 and all(len(v)==2 for v in groups.values())
    categories=['v2_5','v2_4','tie','not_judgable']
    project_equal={k:sum(sum(r['preferred_source_arm']==k for r in v)/2 for v in groups.values())/24 for k in categories}
    strata={key:{str(value):dict(Counter(r['preferred_source_arm'] for r in rows if r[key]==value))
        for value in sorted({r[key] for r in rows})} for key in ['role','variant']}
    result={'planned_source_projects':24,'planned_pairs':48,'readable_pairs':46,
        'raw_counts':summary['preferences'],'strata':strata,
        'equal_project_shares_all_planned_conditions':project_equal,
        'v25_minus_v24_net_preference_all_planned':(21-4)/48,
        'missing_extreme_bounds_net_preference':[(21-4-2)/48,(21-4+2)/48],
        'missing_bounds_are_confidence_intervals':False,
        'new_judgments':36,'retained_original_judgments':12,
        'individual_dimension_scores_changed':False,'new_model_calls':0,
        'limitations':['Descriptive auxiliary preferences, no independent expert or true blind review.',
            'Conditions clustered within24 projects;46 pairs are not46 independent projects.',
            'Relative preference can favor an answer still graded inappropriate.',
            'No causal utility, return on investment, or real procurement outcome is inferred.'],
        'source_judgment_sha256':pins,
        'retained_reason_crosswalk_sha256':sha(OUT/'retained_reason_label_crosswalk_001.json')}
    save(OUT/'descriptive_analysis_001.json',result)
    role_lines=[]
    for role,counts in strata['role'].items():
        role_lines.append('| '+role+' | '+' | '.join(str(counts.get(k,0)) for k in categories)+' |')
    text='''# CP01 首轮成对偏好辅助结果

已处理固定48组配对，来自24个来源项目的完整／缺核心资料两种条件；仅使用重复1首轮原始回答。46组双方可读，2组保留历史缺失，未将可读一侧自动算作胜出。

| 处理结果 | 组数 | 全部48组占比 |
| --- | ---: | ---: |
| 偏好 V2.5 | 21 | 43.75% |
| 偏好 V2.4 | 4 | 8.33% |
| 持平 | 21 | 43.75% |
| 无法比较 | 2 | 4.17% |

每个项目固定两种条件，因此保留缺失槽位的项目等权占比与上表相同。V2.5减V2.4的净偏好为35.42个百分点；仅将两组缺失分别全部置为任一版本胜出，极端边界为31.25至39.58个百分点。这是缺失情景边界，不是置信区间。不能把46组可读配对当成46个独立项目。

| 角色 | 偏好V2.5 | 偏好V2.4 | 持平 | 无法比较 |
| --- | ---: | ---: | ---: | ---: |
'''+ '\n'.join(role_lines)+'''

偏好主要涉及事实依据、职责边界、条件处理及可执行服务路径；没有将报价更低、篇幅更长、愿意投标或程序通过作为自动获胜规则。V2.5亦有负例：PAIR-11增加非必要提交核查，PAIR-13以无据主营错配主导拒绝，PAIR-41扩写工商范围。相对偏好不改变任何初始维度分数，PAIR-09等个例即使胜出仍保留D1不适当记录。

12组沿用先前顺序检查的首轮偏好；另36组为本轮逐案撰写，其中2组明确无法比较。沿用的12份理由原文保留原展示标签，其A/B可能与固定CP02展示不同；必须结合 `retained_reason_label_crosswalk_001.json` 阅读。已保存的偏好映射及引文标签使用当前CP02标签，原始记录、理由及评分均未覆盖。这项标签说明不产生新评价或改票。

全部评价由参与方案设计、已接触版本及评分的同一作者辅助AI完成；不能称独立专家评审、真正盲评或多评阅者一致性。先前12组顺序互换检查仅检验该子样本偏好稳定性，不能推广为48组全部完成顺序互换或不存在顺序偏差。其他批次和最终宏观结果仍在进行，本表不是总实验结论。

证据目录：`pair_preferences/CP01_001/`。其中 `summary_001.json` 保留全部计划槽位，`descriptive_analysis_001.json` 含分层计数、项目等权占比、缺失边界和48份评价哈希；每份评价绑定原始回答、题卡和精确引文。原CP02输入与A/B映射未修改。本分析新增模型调用为0。
'''
    target=MASTER/'CP01首轮成对偏好结果_001.md'
    assert not target.exists()
    target.write_text(text,encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['raw_counts','strata','equal_project_shares_all_planned_conditions']},ensure_ascii=False))


if __name__=='__main__':main()
