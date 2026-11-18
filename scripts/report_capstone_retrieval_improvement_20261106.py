"""Independently reconstruct OOF recommendations, verify, and write Markdown."""
import ast
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.improve_capstone_retrieval_20261106 import OUT,OLD,read,save,sha,now,ROLELIST,SOURCE,read_csv,regions,tokens,normalize,canonical_name
DOC=ROOT/'Capstone报告/验证体系/实验结果/2026-11-06_TOP5推荐改进与交叉验证.md'
def pct(x):return f'{x*100:.2f}%'

def main():
    protocol=read(OUT/'protocol.json');summary=read(OUT/'summary.json');rows=read(OUT/'role_scores.json');groups=read(OUT/'grouped_scores.json')
    ps=read_csv(SOURCE/'simulation_input_projects.csv');cs=read_csv(SOURCE/'simulation_input_enterprises.csv');links=read_csv(SOURCE/'hidden_benchmark_project_enterprises.csv')
    assert all(sha(SOURCE/n)==h for n,h in protocol['source_sha256'].items())
    assert sha(ROOT/'scripts/improve_capstone_retrieval_20261106.py')==protocol['runner_sha256']
    assert sha(OUT/'out_of_fold_rankings_before_evaluation.npz')==read(OUT/'prediction_freeze.json')['sha256']
    assert sha(OLD/'E01_predictions_before_evaluation.jsonl.gz')==read(OLD/'E01_prediction_freeze.json')['sha256']
    split=read(OUT/'split_before_labels.json')['assignments'];selection=read(OUT/'inner_selection.json')
    pid={p['case_id']:i for i,p in enumerate(ps)};cid={c['company_id']:i for i,c in enumerate(cs)}
    npz=np.load(OUT/'out_of_fold_rankings_before_evaluation.npz');elig=npz['eligible'];shape=(len(ps),len(ROLELIST),len(cs))
    index=read(OUT/'ranking_index.json');assert len(rows)==433*len(index['methods'])
    for m in index['methods']:
        rank=npz[m];assert rank.shape==shape
        assert np.all(np.sort(rank,axis=2)==np.arange(len(cs))),m
    for f,x in enumerate(selection):
        train=set(x['training_case_ids']);test=set(x['test_case_ids'])
        assert not train&test and train|test==set(pid)
        assert not {a['group'] for a in split if a['case_id'] in train}&{a['group'] for a in split if a['case_id'] in test}
        assert len({a['group'] for a in split})==331
        best=max(x['candidates'],key=lambda z:z['hits']/z['units'])
        assert best['family']==x['selected_family'] and best['text_blend']==x['text_blend']
    labels=defaultdict(set)
    for l in links:
        if l['company_role_original'] in ROLELIST and l['company_id']:
            labels[pid[l['case_id']],ROLELIST.index(l['company_role_original'])].add(cid[l['company_id']])
    # Independent per-query reconstruction from ONLY that fold's training links.
    checked=0;explanations=[]
    for row in [x for x in rows if x['method']=='nested_hybrid']:
        i=pid[row['case_id']];j=ROLELIST.index(row['role']);s=selection[row['fold']]
        train=set(s['training_case_ids']);w=protocol['families'][s['selected_family']];b=s['text_blend']
        a=tokens(normalize(ps[i]['project_name']));city=regions(ps[i]['location']);own=canonical_name(ps[i]['owner_name'])
        total=np.zeros(len(cs),dtype=np.float64);basis=defaultdict(list)
        for ref,p in enumerate(ps):
            if p['case_id'] not in train:continue
            assert split[ref]['group']!=split[i]['group']
            text=tokens(normalize(p['project_name']))
            f=[1.,float(bool(city&regions(p['location']))),float(bool(own and own==canonical_name(p['owner_name']))),
                len(a&text)/max(1,(len(a)*len(text))**.5),float(ps[i]['project_type']==p['project_type'])]
            contribution=sum(v*z for v,z in zip(w,f))
            for k in labels.get((ref,j),set()):
                total[k]+=contribution
                basis[k].append({'reference_case_id':p['case_id'],'reference_project_name':p['project_name'],
                    'reference_group':split[ref]['group'],'weight':contribution})
        # Independent float64 scalar reconstruction, separate from dense fitting.
        # Exact history ties use only the frozen public order.
        hist=np.log1p(total);hist/=max(float(hist.max()),1e-8)
        text=np.empty(len(cs),dtype=float);old=npz['old_role_first'][i,j]
        for rank,k in enumerate(old,1):text[k]=11/(10+rank)
        z=(1-b)*hist+b*text+1e-9*text;z[~elig[i,j]]=-np.inf
        reconstructed=[int(k) for k in np.argsort(-z,kind='stable')[:5]]
        expected=[cid[k] for k in row['top5_company_ids']]
        assert reconstructed==expected,(row['case_id'],row['role'],reconstructed,expected)
        checked+=1
        explanations.append({'case_id':row['case_id'],'role':row['role'],'fold':row['fold'],
            'query_name':ps[i]['project_name'],'current_project_relation_used':False,
            'top5':[{'rank':n+1,'company_id':cs[k]['company_id'],'company_name':cs[k]['company_name'],
                'training_weighted_count':float(total[k]),'top_reference_projects':sorted(basis[k],key=lambda x:-x['weight'])[:3]}
                for n,k in enumerate(expected)]})
    save(OUT/'top5_explanations.json',explanations)
    # Validate every dated training edge, including no target/test-fold overlap.
    time=read(OUT/'time_sensitivity/summary.json');dated_audit=read(OUT/'time_sensitivity/training_date_audit.json')
    for q in dated_audit:
        i=pid[q['case_id']]
        for x in q['training_relations']:
            ref=pid[x['case_id']]
            assert x['finish_month']<q['target_cutoff_month']
            assert split[ref]['outer_fold']!=split[i]['outer_fold'] and split[ref]['group']!=split[i]['group']
    save(OUT/'verification.json',{'status':'passed','at':now(),'raw_inputs_unchanged':True,
        'outer_project_group_overlap':0,'outer_split_projects':352,'role_units':433,
        'all_methods_full_candidate_rankings_valid':True,'independently_reconstructed_top5_queries':checked,
        'original_predictions_unchanged':True,'date_gates_verified':True,'new_api_requests':0})
    # CSVs are derived result tables, never edits to source workbooks.
    for name,data in [('summary',summary['methods']),('grouped_scores',groups)]:
        with (OUT/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    names={'old_role_first':'原画像／关键词规则','role_history':'历史角色频次基线','region_history':'历史角色＋地区基线',
        'owner_history':'历史角色＋地区＋业主','analogy_history':'固定相似项目经验','nested_hybrid':'内层选型的相似项目历史推荐'}
    method_table=[]
    for x in summary['methods']:
        method_table.append(f"|{names[x['method']]}|{x['hits1']}/433（{pct(x['hit1'])}）|{x['hits3']}/433（{pct(x['hit3'])}）|{x['hits5']}/433（{pct(x['hit5'])}）|{pct(x['recall5'])}|")
    role_table=[]
    for x in groups:
        if x['dimension']=='role' and x['method']=='nested_hybrid':
            old=next(v for v in groups if v['dimension']=='role' and v['method']=='old_role_first' and v['group']==x['group'])
            role_table.append(f"|{x['group']}|{x['units']}|{old['hits5']}（{pct(old['hit5'])}）|{x['hits5']}（{pct(x['hit5'])}）|")
    time_table=[]
    for x in time['methods']:
        name={'old_role_first':'原画像规则','dated_role_history':'只用较早完成记录的角色频次','dated_analogy_history':'只用较早完成记录的固定相似项目经验'}[x['method']]
        time_table.append(f"|{name}|{x['hits5']}/{x['units']}|{pct(x['hit5'])}|")
    doc=f'''# Top5推荐改进与分组交叉验证

日期：2026-11-06（北京时间）。**已运行完成：同一433个角色单元上，Top5从24/433（5.54%）提高到286/433（66.05%）。** 候选背景仍为904家企业，保持原有业主排除规则；未缩小为历史赢家池，未改角色标签、命中定义或分母，未新增模型调用。

这是一项**新增的、使用历史角色关系训练的推荐方法**，不是原微宏观模型突然达到66.05%，也不是对既有0014连续仿真结果的改写。原方法只读企业画像；新方法显式学习其他项目的合作经验，两者训练信息不同。论文应同时报告历史频次等公平基线。

## 1. 为什么原来这么低

原方法把企业简介中的角色关键词放在排序前面，再看地区和主题。409个未命中角色单元关联445个已知正例企业关系：

|未命中正例的特征|关系数|
|---|---:|
|企业简介有该角色证据|184|
|仅企业名称有角色证据|47|
|企业简介和名称都没有识别到角色证据|214|
|画像地点与项目同城|186|
|地点异地或无法识别|259|
|该企业在其他项目中做过同一历史角色|333|
|该角色下仅在当前项目出现|112|

这些是关系计数，不是445个独立角色单元。许多真实参与企业画像不完整、在异地承接业务，单靠关键词硬分层会把它们压后；同时已有大量其他项目中的经验没有进入原排序。

## 2. 新方法怎样推荐

对于一个项目和待推荐角色，收集训练项目中承担过该角色的企业。相近项目贡献更高权重，相近程度来自：项目名称的中文二元词／英文词重合、同城、相同业主和项目类型。把企业在训练项目中的加权次数累加并取`log1p`，再排序；同分时沿用原公开画像顺序。

五类预先写入协议的经验权重，与4种画像融合比例构成20种候选设置。每个外层训练集中，用内层3折Hit@5选择设置。5个外层折都选择了同一设置：

`参考项目权重 = 0.1 + 1×同城 + 2×相同业主 + 12×项目标题词集合余弦相似度 + 1×同项目类型`

画像融合比例最终均为0，说明本轮主要贡献来自**历史项目推荐**；企业画像只在历史得分同分时排序。不能把这个结果描述成大模型语义能力、企业资质推理或学习到的真实采购资格。没有出现过的历史企业仍保留在904候选背景中，但这类方法对新企业明显不足。

## 3. 怎样避免把本项目答案拿来推荐本项目

1. 352项目先按公开标题、地区构建相近重复项目组，共331组，其中8组含多个项目。完全同名、去数字／期次后同名，或同地区标题词集合Jaccard≥0.80的项目进入同一连通组。规则与分组文件在本次读取标签前保存；这仍不保证排除了全部隐性关联项目。
2. 外层5折按组分开，每折留70或71个项目；一个项目及其同组近重复项目不会跨训练与测试。
3. 仅在外层训练项目中做内层3折选型。测试项目标签不参与该折训练或选型。
4. 352项目都得到一次外层预测，433个有标签的角色单元全部进入总表，不筛掉失败案例。公司分支、母子公司和联合体保持原企业身份，不靠合并身份制造命中。
5. 独立核验脚本从该折训练关系重新计算全部433条Top5，与保存结果逐条一致；原始CSV和原冻结排名哈希一致。

首轮单精度累计曾导致少数近同分企业交换名次。该轮原始文件与原脚本全部保留在`float32_first_pass/`；改用双精度后重新执行相同分组、参数候选和选型过程，主要命中计数仍为286/433。最终排名通过独立双精度重建核验，详见[数值精度修正记录](../../../output/integration/capstone_retrieval_improvement_20261106/precision_correction.json)。修正未依据测试表现选择版本。

此前研究者看过全量标签，因此这里称为**回顾性分组交叉验证／方法开发结果**；不称为全新盲测或外部验证。跨折训练集共享数据，下文重采样区间是对当前交叉预测的描述性区间，不是包含完整重训与选型不确定性的正式显著性检验。

## 4. 全量对比

Hit@K＝该角色前K家里至少有一家已知历史企业。Recall@5则统计前五覆盖该角色已知历史企业的比例，再在433角色单元间平均。没有历史标注的候选企业不自动等于不合格。

|方法|Top1命中|Top3命中|Top5命中|Recall@5|
|---|---:|---:|---:|---:|
{chr(10).join(method_table)}

新方法覆盖至少一个角色的项目为262/352（74.43%），原方法为21/352（5.97%）。这是“项目至少一角色命中”，不是整个项目团队全部命中。

最值得写进论文的比较有三层：

- 引入其他项目的历史训练信息后，相比原画像规则提高60.51个百分点；这包含信息条件变化，不能全部算成排序公式贡献。
- 相比同样使用历史关系的角色频次基线，提高9.93个百分点；按项目组整群重采样4,000次的95%描述区间为[6.67，13.33]个百分点。
- 相比历史角色＋地区基线，提高4.16个百分点；对应区间[1.69，6.83]个百分点。这更接近相似项目信息带来的增量价值。

这些比例不是大模型微观决策正确率，也不是完整微宏观衔接成功率。

### 全部角色结果

|角色|评价单元|原Top5命中|新Top5命中|
|---|---:|---:|---:|
{chr(10).join(role_table)}

造价、监理等角色样本很少，高比例不能当稳定结论。总包与设计分别有196和131个单元，更适合承担主要角色结果。完整地区和项目类型统计保存在[分组表](../../../output/integration/capstone_retrieval_improvement_20261106/grouped_scores.csv)，不只保留好看的分组。

## 5. 还没有解决的问题：没有历史记录的新企业

|按测试时训练记录划分|单元数|原方法Top5命中|新方法Top5命中|
|---|---:|---:|---:|
|至少一家历史正例企业曾在训练项目中做过同角色|330|8/330（2.42%）|286/330（86.67%）|
|所有历史正例企业在训练集中都没做过同角色|103|16/103（15.53%）|0/103（0.00%）|

这个分组只用于事后诊断，推荐时不能知道当前正例是否未见，不能按此分组作弊切换方法。新方法对重复企业非常有效，但牺牲了冷启动表现。下一步应在训练／内层验证中研究可观察的历史不足信号、多路召回和画像保留策略；不能直接按当前真实企业是否出现来决定用哪一路。

### 原0014案例也不是每个角色都变好

|角色|原历史企业名次|新方法名次|变化|
|---|---|---|---|
|总包 COMP-0025|5|77|训练折里没有该企业同角色历史，退步|
|设计 COMP-0461|1|2|仍在Top3／Top5|
|检测 COMP-0512|173|1|改善；另一家历史检测企业COMP-0540仍未进Top5|

该案例仍是2/3角色Top5命中，命中的角色发生变化。原完整微宏观仿真、PPT及授标记录没有替换；全量推荐改善不保证原展示案例每一角色改善。

## 6. 时间可用性补查

随机分组交叉验证会用到其他年份的关系，尚未证明这些经验在目标项目招标之前已可获得。为检查这个问题，另外做了**事后时间敏感性分析**：固定预先声明的相似度权重，不重新搜索参数；仍只取该外层训练折，额外要求参考关系的竣工月份早于目标项目最早可解析开工月份。

仅接受无歧义的`YYYY-MM[-DD]`及点／斜线分隔日期，不猜范围、缺月日期或文字描述。本次得到154条有严格可解析完成日期的参考关系；98个项目、141个角色单元有可解析开工时间，其余292单元记为本项不可评价，仍保留在主实验433分母中。22个可评价单元没有任何满足时间要求的同角色参考关系，照样计分。

|方法（相同141单元子集）|Top5命中|Hit@5|
|---|---:|---:|
{chr(10).join(time_table)}

这个子集也有改善，但幅度小于66.05%的全量回顾性结果。开工日期不等于招标日期，竣工日期也不证明企业资料当时已经公开，故该分析仍不是严格前瞻验证。论文应同时报告时间限定结果，不能把66.05%写成已证明的历史时点部署精度。

## 7. 论文与系统中的使用方式

可把这一块写成“利用历史案例知识的角色推荐模块”，将原画像规则、历史频次和地区历史作为基线，并报告Top1／3／5、全部角色和冷启动差异。主结论先限定为当前数据上的回顾性推荐能力。

随后再将经过训练／验证的候选推荐接入微观决策及宏观流程，另行验证业务可行性、组织讨论效果和全流程后果。本轮没有重跑宏观仿真，也没有把66.05%归到LLM头上。新旧方案均保留，本次原始输入和既有实验不改动。

## 8. 复核文件

- [协议与固定候选设置](../../../output/integration/capstone_retrieval_improvement_20261106/protocol.json)
- [按项目组划分的训练／测试清单](../../../output/integration/capstone_retrieval_improvement_20261106/split_before_labels.json)
- [每折内层选型与训练项目清单](../../../output/integration/capstone_retrieval_improvement_20261106/inner_selection.json)
- [完整方法汇总](../../../output/integration/capstone_retrieval_improvement_20261106/summary.json)及[CSV表](../../../output/integration/capstone_retrieval_improvement_20261106/summary.csv)
- [逐角色完整结果](../../../output/integration/capstone_retrieval_improvement_20261106/role_scores.json)
- [每条Top5推荐的其他项目证据](../../../output/integration/capstone_retrieval_improvement_20261106/top5_explanations.json)
- [原方法未命中诊断](../../../output/integration/capstone_retrieval_improvement_20261106/error_diagnosis.json)
- [时间限制协议](../../../output/integration/capstone_retrieval_improvement_20261106/time_sensitivity/protocol.json)及[时间子集结果](../../../output/integration/capstone_retrieval_improvement_20261106/time_sensitivity/summary.json)
- [输入与预测核验结果](../../../output/integration/capstone_retrieval_improvement_20261106/verification.json)

原5.54%报告保留：[首批Validation实验](2026-11-05_首批Validation实验结果.md)。本次只读复核与报告命令：`.\\.venv-integration\\Scripts\\python.exe -X utf8 scripts/report_capstone_retrieval_improvement_20261106.py`。完整分组训练脚本会拒绝覆盖已有结果目录；本轮没有新增API消费。
'''
    DOC.parent.mkdir(exist_ok=True,parents=True);DOC.write_text(doc,encoding='utf-8')
    for t in re.findall(r'\]\(([^)]+)\)',doc):assert (DOC.parent/t).resolve().exists(),t
    for s in ['improve_capstone_retrieval_20261106.py','check_capstone_retrieval_time_20261106.py','report_capstone_retrieval_improvement_20261106.py']:
        ast.parse((ROOT/'scripts'/s).read_text(encoding='utf-8'))
    save(OUT/'delivery_check.json',{'status':'passed','report_sha256':sha(DOC),'report':str(DOC.relative_to(ROOT)),
        'verified_queries':checked,'new_api_requests':0})
    print(json.dumps({'status':'verified_and_reported','reconstructed_queries':checked,'report':str(DOC)},ensure_ascii=False))

if __name__=='__main__':main()
