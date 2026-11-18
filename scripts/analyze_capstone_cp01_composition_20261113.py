"""Source-bound declared actions and explicit, post-hoc D1 reason decomposition."""
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
import json
from review_capstone_all_20261113 import MASTER,ROOT,read,save,sha,source

OUT=MASTER/'analysis/CP01_business_composition_001'


def main():
    index=read(MASTER/'response_index_CP01_first_review_complete_001.json')
    planned=[r for r in index['rows'] if r['cohort']=='CP01']
    assert len(planned)==192
    note=MASTER/'manual_labels/CP01_D1_primary_issue_coding_001.json'; authored=read(note)
    assignments={}
    for category,body in authored['categories'].items():
        for name in body['files']:
            assert name not in assignments
            assignments[name]=category
    records=[]; pins={str(note.relative_to(ROOT)):sha(note)}
    for slot in planned:
        if not slot['readable_outward_json']:continue
        wid,arm,repeat=slot['window_id'],slot['arm'],slot['repeat']
        path=MASTER/'business_review/CP01'/f'{wid}-{arm}-r{repeat}-a1.json'
        grade=read(path); check=MASTER/'business_recheck/CP01'/path.name
        assert read(check)['complete'] and read(check)['initial_record_sha256']==sha(path)
        raw,_,outward=source('CP01',wid,arm,repeat,1)
        assert sha(raw)==grade['response_sha256']==slot['response_sha256']
        pins.update({str(p.relative_to(ROOT)):sha(p) for p in [path,check,raw]})
        supplier=grade['role']=='supplier'
        if supplier:
            assert 'decision' not in outward
            action='supplier_proposal_no_management_decision_field'
        else:
            action=outward['decision']; assert action in {'bid','no_bid','bid_with_consortium'}
        issue=assignments.get(path.name)
        assert (issue is not None)==(grade['D1']['label']=='inappropriate')
        records.append({'window_id':wid,'arm':arm,'repeat':repeat,'role':grade['role'],
            'variant':slot['variant'],'project_group':grade['project_group'],
            'declared_action':action,'D1':grade['D1']['label'],'D2':grade['D2_correct_coverage'],
            'factor_counts':dict(Counter(f['rating'] for f in grade['factor_ratings'])),
            'D1_primary_issue':issue,'D1_reason':grade['D1']['reason'],'D1_quote':grade['D1']['quote'],
            'grade_path':str(path.relative_to(ROOT)),'grade_sha256':sha(path)})
    assert len(records)==190 and sum(r['D1_primary_issue'] is not None for r in records)==len(assignments)==40
    actions=[]
    for arm in ['v2_4','v2_5']:
        own=[r for r in records if r['arm']==arm]
        for action in sorted({r['declared_action'] for r in own}):
            rs=[r for r in own if r['declared_action']==action]
            actions.append({'arm':arm,'action':action,'n':len(rs),
                'D1_counts':dict(Counter(r['D1'] for r in rs)),
                'D2_answer_mean':mean(r['D2'] for r in rs)})
    issues={arm:dict(Counter(r['D1_primary_issue'] for r in records if r['arm']==arm and r['D1_primary_issue']))
            for arm in ['v2_4','v2_5']}
    factors={arm:dict(sum((Counter(r['factor_counts']) for r in records if r['arm']==arm),Counter()))
             for arm in ['v2_4','v2_5']}
    summary={'planned_answers':192,'readable_graded_answers':190,'missing_answers':2,
        'actions':actions,'D1_primary_issue_counts':issues,'D2_unweighted_item_counts':factors,
        'interpretation':['Action labels extracted from actual outward decision enum; not inferred from annotated_action or program status.',
            'Supplier proposal schema has no comparable management decision enum; no bid label imputed.',
            'Raw answer/item counts and action-conditioned means are descriptive; they do not replace project-paired main estimates.',
            'D1 categories are explicitly authored post-hoc primary reasons; no new scores inferred.'],
        'new_model_calls':0,'source_files_sha256':pins,
        'analysis_code_sha256':sha(Path(__file__))}
    save(OUT/'answer_ledger_001.json',records);save(OUT/'summary_001.json',summary)
    lines=['# CP01 行动构成与业务问题分解','',
        '固定192个首轮槽位中190份可读，2份历史缺失保留。以下是辅助描述，未替代24项目配对分析，也未重评或覆盖任何首轮评分。',
        '', '| 版本 | 原文行动字段／文书类型 | 回答数 | D1适当／不适当 | D2回答均值 |',
        '| --- | --- | ---: | --- | ---: |']
    for r in actions:
        c=r['D1_counts'];lines.append(f"| {r['arm']} | {r['action']} | {r['n']} | {c.get('appropriate',0)}／{c.get('inappropriate',0)} | {r['D2_answer_mean']:.3f} |")
    lines+=['','bid 是模型输出的行动标签，不代表已提交；其正文可能仍是附条件草稿。supplier 的文书没有同构行动字段，单列而不推定全部为投标。行动分组由输出产生，不能把分组内D2均值解释成因果效果，也不能仅因拒绝更多判更好。',
        '', '| D1不适当的主导理由 | V2.4回答数 | V2.5回答数 |','| --- | ---: | ---: |']
    for category,body in authored['categories'].items():
        lines.append(f"| {body['definition']} | {issues['v2_4'].get(category,0)} | {issues['v2_5'].get(category,0)} |")
    lines+=['','40份D1不适当回答均有原始理由、引文与逐项指定的主类，不由关键词自动归因。一份回答可有多个问题，此处只编码主导理由；误设门槛等非主导事项仍保留在原事项评分和成对偏好中，不能把本表无此主类解释为没有门槛错误。编码由同一作者辅助AI事后完成，有判断性，不是独立专家复核或新增主指标。',
        '', 'D2还保留correct／partial／missing／contradicted的原事项计数，见 `analysis/CP01_business_composition_001/summary_001.json`。不同角色事项数不同，原始事项计数不能替代先对每回答归一化再做项目配对的D2主结果。',
        '', '可复算证据：同目录 `answer_ledger_001.json` 逐份记录行动、原D1／D2及原因；`summary_001.json` 绑定原始回答、评分、复核和人工主类表哈希。本分析新增模型调用为0。']
    path=MASTER/'CP01行动与业务问题构成_001.md';assert not path.exists()
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['actions','D1_primary_issue_counts','D2_unweighted_item_counts']},ensure_ascii=False))


if __name__=='__main__':main()
