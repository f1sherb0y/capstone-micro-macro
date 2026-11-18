"""Separate description of the 48 actual CP00 repairs with complete lineage."""
from collections import Counter,defaultdict
from statistics import mean
import csv,json
import argparse
from pathlib import Path
from review_capstone_all_20261113 import ROOT,MASTER,CP00,read,save,sha,source,cards
from analyze_capstone_content_20261113 import grade_value
from capstone_project_analysis_20261113 import stratified_bootstrap,influence
from capstone_cp_common_20261112 import no_provider
from revise_capstone_business_evidence_20261113 import effective_review

OUT=MASTER/'analysis/CP00_repair_content_001'


def main(tag='CP00_repair_content_002',report_number='002'):
    OUT=MASTER/'analysis'/tag
    assert not OUT.exists()
    paths=sorted((CP00/'run/jobs').glob('*/attempt-2.json'))
    assert len(paths)==48
    pairs=[];pins={};transitions=Counter();equal_count=0
    with no_provider() as calls:
        for path in paths:
            job=read(path)['job'];wid,arm,repeat=[job[k] for k in ['window_id','arm','repeat']]
            records=[];payloads=[]
            for attempt in [1,2]:
                gp=MASTER/'business_review/CP00'/f'{wid}-{arm}-r{repeat}-a{attempt}.json'
                initial=read(gp);g,revisions=effective_review(gp)
                rp,_,payload=source('CP00',wid,arm,repeat,attempt)
                assert g['response_sha256']==sha(rp) and payload is not None
                cp=MASTER/'business_recheck/CP00'/gp.name
                if cp.exists():
                    c=read(cp);assert c['complete'] and c['initial_record_sha256']==sha(gp)
                    assert c['response_sha256']==sha(rp)
                    pins[str(cp.relative_to(ROOT))]=sha(cp)
                else:
                    assert attempt==1 and g['evidence_recheck']['complete']
                    ep=ROOT/g['evidence_recheck']['initial_record_path']
                    assert sha(ep)==g['evidence_recheck']['initial_record_sha256']
                    pins[str(ep.relative_to(ROOT))]=sha(ep)
                    cal=MASTER/'calibration/six_block_calibration.json'
                    assert sha(cal)==g['evidence_recheck']['calibration_sha256']
                    pins[str(cal.relative_to(ROOT))]=sha(cal)
                for p in [gp,rp,ROOT/g['input_card_path'],ROOT/g['authored_labels_path']]:
                    pins[str(p.relative_to(ROOT))]=sha(p)
                for p in revisions:
                    note=ROOT/read(p)['authored_notes_path']
                    assert sha(note)==read(p)['authored_notes_sha256']
                    pins[str(p.relative_to(ROOT))]=sha(p);pins[str(note.relative_to(ROOT))]=sha(note)
                records.append(g);payloads.append(payload)
            before,after=records
            assert before['project_group']==after['project_group'] and before['role']==after['role']
            assert [f['id'] for f in before['factor_ratings']]==[f['id'] for f in after['factor_ratings']]
            equivalent={k:v for k,v in payloads[0].items() if k!='repair_explanation'}=={k:v for k,v in payloads[1].items() if k!='repair_explanation'}
            if equivalent:
                equal_count+=1
                assert grade_value(before,'D1')==grade_value(after,'D1')
                assert [f['rating'] for f in before['factor_ratings']]==[f['rating'] for f in after['factor_ratings']]
            for b,a in zip(before['factor_ratings'],after['factor_ratings']):transitions[b['rating']+' -> '+a['rating']]+=1
            row={'window_id':wid,'arm':arm,'repeat':repeat,'project_group':after['project_group'],
                 'role':after['role'],'company_id':cards('CP00')[1][wid]['company_id'],
                 'variant':'missing_core' if wid.endswith('-missing_core') else 'full',
                 'before_grade_path':str((MASTER/'business_review/CP00'/f'{wid}-{arm}-r{repeat}-a1.json').relative_to(ROOT)),
                 'after_grade_path':str((MASTER/'business_review/CP00'/f'{wid}-{arm}-r{repeat}-a2.json').relative_to(ROOT)),
                 'before_response_sha256':before['response_sha256'],'after_response_sha256':after['response_sha256'],
                 'outward_equal_except_repair_explanation':equivalent}
            for metric in ['D1','D2']:
                b,a=[grade_value(g,metric) for g in records];assert b is not None and a is not None
                row.update({metric+'_before':b,metric+'_after':a,metric+'_change':a-b})
            pairs.append(row)
        reports={};project_rows=[]
        for metric in ['D1','D2']:
            groups=defaultdict(list)
            for r in pairs:groups[r['project_group']].append(r)
            projects=[]
            for group,rows in sorted(groups.items()):
                assert len({r['role'] for r in rows})==len({r['company_id'] for r in rows})==1
                item={'metric':metric,'project_group':group,'role':rows[0]['role'],'company_id':rows[0]['company_id'],
                    'selected_repair_answers':len(rows),'before_mean':mean(r[metric+'_before'] for r in rows),
                    'after_mean':mean(r[metric+'_after'] for r in rows),'difference':mean(r[metric+'_change'] for r in rows)}
                projects.append(item);project_rows.append(item)
            reports[metric]={'selected_answer_pairs':48,'selected_source_projects':len(projects),
                'project_equal_before_mean':mean(p['before_mean'] for p in projects),
                'project_equal_after_mean':mean(p['after_mean'] for p in projects),
                'project_equal_change':mean(p['difference'] for p in projects),
                'improved_answers':sum(r[metric+'_change']>0 for r in pairs),
                'unchanged_answers':sum(r[metric+'_change']==0 for r in pairs),
                'lower_answers':sum(r[metric+'_change']<0 for r in pairs),
                'selected_project_exploratory_uncertainty':stratified_bootstrap(projects),
                'leave_project_out':influence(projects,'project_group'),'leave_firm_out':influence(projects,'company_id')}
        assert equal_count==4
        for i in range(1,5):
            stem=f'CP00_repair_delta_batch{i:02d}_001'
            for suffix in ['.json','_expanded_labels.json','_expanded_rechecks.json','_source_bindings.json']:
                p=MASTER/'manual_labels'/(stem+suffix);pins[str(p.relative_to(ROOT))]=sha(p)
        save(OUT/'answer_pairs.json',pairs)
        for filename,rows in [('answer_pairs.csv',pairs),('selected_project_metric_pairs.csv',project_rows)]:
            with (OUT/filename).open('x',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        save(OUT/'summary_001.json',{'actual_repair_answers':48,'all48_reviewed_and_rechecked':True,
            'source_projects':len({r['project_group'] for r in pairs}),'source_roles':dict(Counter(r['role'] for r in pairs)),
            'variants':dict(Counter(r['variant'] for r in pairs)),'arms':dict(Counter(r['arm'] for r in pairs)),
            'equivalent_public_business_objects_except_repair_explanation':equal_count,
            'metrics':reports,'factor_transitions':dict(transitions),'initial_first_records_changed':False,
            'effective_S6_category_correction_included':sum('/business_revision/' in p.replace('\\','/') for p in pins),
            'D1_D2_numeric_first_scores_changed_by_revision':False})
        lines=['# CP00修复后业务结果（探索性、触发选择样本）','',
            f'全部48份实际修复回答已完成逐份业务复核，覆盖{len({r["project_group"] for r in pairs})}个源项目。对照对象为各自原首轮，先平均同一项目内被触发修复的回答，再让各入选项目等权；这与首轮完整/缺失资料各半权重的总体比较是不同估计量。','',
            '| 指标 | 修复后−首轮，项目等权 | 条件性探索95%区间 | 改善／不变／下降回答 |','|---|---:|---:|---:|']
        for m,title in [('D1','行动适当率'),('D2','正确事项覆盖率')]:
            r=reports[m];ci=r['selected_project_exploratory_uncertainty']['exploratory_percentile95']
            lines.append(f'| {title} | {100*r["project_equal_change"]:+.2f}个百分点 | [{100*ci[0]:.2f}, {100*ci[1]:.2f}]个百分点 | {r["improved_answers"]}／{r["unchanged_answers"]}／{r["lower_answers"]} |')
        lines += ['', '4份修复回答除修复解释外，公开业务对象与首轮完全相同，所有评分均保持；其余44份通过逐字段差异复核，未改部分继承同一作者已完成的首轮判断，改变部分逐项人工式审查，并绑定两次原文、初评、修复评和复核哈希。此为同一作者辅助AI的内容对照，不是新的独立评阅。','',
            '保留未修复成功的业务问题。例如EXPAND-02缺失资料V2.5-r2只改理由，正文仍声称档案显示实际建筑设计研究机构；EXPAND-24缺失资料V2.5-r1仍保留既有土木工程顾问身份及业务方向；两者D1未改善。EXPAND-05/11的加总差异修正后，整包施工越过供应角色的问题仍在。','',
            'EXPAND-14完整资料V2.4-r2只是删除报价数组中明确“合计”的汇总行：首轮已按六项费用求得260万，业务S6原本正确，因此修复不计业务改善。程序格式变好与业务结果改善分开报告。','',
            '这些回答由既定校验条件触发，非随机选择；修复本身使用了额外反馈及调用，不能用来比较两个版本在等成本下的因果提升，不能按臂高低均值排优劣，也不能作为48个新案例。所有首轮评分和首轮主结果保持，不用修复替代失败首轮。本批没有新增D3/D4评分。','',
            f'完整配对分数、项目权重、区间和逐项目/企业剔除结果见`analysis/{tag}/`。区间按入选源项目、角色分层20,000次bootstrap，seed=20261112，仅是该触发选择样本的描述性不确定性。',
            '本版纳入EXPAND-23完整资料V2.5-r2首轮S6类别一致性修订：合计不符仍存在，与本批其他同类错误一致记“部分”，不计正确覆盖。原初评未覆盖，D1/D2数值及修复改善数量不变；事后类别修订与首轮错误均披露。','']
        rp=MASTER/f'CP00修复后业务结果_{report_number}.md';assert not rp.exists();rp.write_text('\n'.join(lines),encoding='utf-8')
        pins[str(rp.relative_to(ROOT))]=sha(rp)
        for p,d in pins.items():assert sha(ROOT/p)==d
        save(OUT/'manifest.json',{'source_sha256':pins,'code_sha256':sha(__file__),
            'artifacts':{p.name:sha(p) for p in OUT.iterdir()},'new_provider_calls':0,'new_semantic_labels_inferred':0,**calls})
    print(json.dumps({m:{k:r[k] for k in ['selected_source_projects','project_equal_change','improved_answers','unchanged_answers','lower_answers']} for m,r in reports.items()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--tag',default='CP00_repair_content_002')
    parser.add_argument('--report-number',default='002');args=parser.parse_args();main(args.tag,args.report_number)
