"""Render condition tables from exact computed JSON values."""
from analyze_capstone_cp01_conditions_20261113 import MASTER, OUT as SOURCE, read, sha, save


def main():
    summary=read(SOURCE/'summary_001.json')
    lines=['# CP01 信息完整性与版本差异：首轮业务评价补充','',
        '范围：24 个固定项目组，192 个计划首轮回答中 190 份可读、2 份历史未知；重复回答先在项目内平均。D1/D2 使用两个重复，D3/D4 使用预选 repeat=1。评分来自同一设计参与助手的作者辅助 AI 评阅及证据复核。此补充不新增模型调用或语义评分。','',
        '## 完整资料与缺失资料分别比较','',
        '下表为 V2.5 − V2.4。D1/D2 单位为百分点；D3/D4 是 0–2 有序量表分差。方括号为按角色分层、以项目为单位进行 20,000 次重采样的探索性 95% 区间。','',
        '| 指标 | 完整资料：差值 [区间]；n | 缺失资料：差值 [区间]；n | 条件交互：差值 [区间]；n |',
        '|---|---:|---:|---:|']
    for metric in ['D1','D2','D3','D4']:
        scale=100 if metric in {'D1','D2'} else 1
        digits=1 if scale==100 else 3
        cells=[]
        for name in ['version_full','version_missing','interaction']:
            x=summary[metric][name]; lo,hi=x['uncertainty']['exploratory_percentile95']
            cells.append(f"{x['project_equal_difference']*scale:+.{digits}f} [{lo*scale:.{digits}f}, {hi*scale:.{digits}f}]；{x['observed_projects']}")
        lines.append('| '+metric+' | '+' | '.join(cells)+' |')
    lines += ['',
        '条件交互 =（缺失资料下的 V2.5 − V2.4）−（完整资料下的 V2.5 − V2.4），在同一项目四个单元均可观察时计算。D3/D4 的两项条件结果分别有 22、24 对，交互只有 22 对，不能拿上表两个不同项目集合的汇总差值直接相减替代交互。','',
        'D1、D2 在两种资料条件下均呈正向版本差异，D3 亦有正向分差；D4 接近量表上限且区间触及零。四项交互区间均包含零，因此这里只能描述“资料缺失条件下仍观察到部分内容优势”，不能据此确定改进在资料缺失时更强，也不能宣称非劣效、等效或独立外部效度。','',
        '## 同一版本在资料减少后怎样变化','',
        '下表为缺失资料 − 完整资料，负值表示按既定评价规范所得内容分下降。它体现回答对信息条件的敏感性，不是虚构资料后应当保持全部原有内容的要求。','',
        '| 指标 | V2.4：变化 [区间]；n | V2.5：变化 [区间]；n |','|---|---:|---:|']
    for metric in ['D1','D2','D3','D4']:
        scale=100 if metric in {'D1','D2'} else 1
        digits=1 if scale==100 else 3
        cells=[]
        for name in ['information_v2_4','information_v2_5']:
            x=summary[metric][name]; lo,hi=x['uncertainty']['exploratory_percentile95']
            cells.append(f"{x['project_equal_difference']*scale:+.{digits}f} [{lo*scale:.{digits}f}, {hi*scale:.{digits}f}]；{x['observed_projects']}")
        lines.append('| '+metric+' | '+' | '.join(cells)+' |')
    lines += ['',
        '两版本的 D1/D2 在资料减少后均下降。V2.5 的下降点估计较小，但是否存在版本间不同的信息敏感性应看上表交互区间，不能只比较两个下降幅度便下结论。缺资料并不要求一律拒绝；有依据的等待、拒绝及有边界的条件方案均按同一任务卡分支评阅。','',
        '## 缺失、依赖关系和分析身份','',
        '- 两份未知回答保留缺失，不补零、不重放；每项 JSON 同时保留全 24 个计划项目的最有利／最不利缺失界限和只保留完整重复的敏感性结果。界限不是置信区间，也不一定与可观察配对点估计使用同一个项目集合。',
        '- 每项还保留逐项目、逐复用企业剔除结果。重复、两种资料条件和同一来源的不同回答都不增加独立项目数。',
        '- 本补充在首轮评分后实现，是对方案中两种信息条件的探索性展开；这些多重比较不作独立预注册的确认性检验，也不按方向选择性报告。',
        '- CASE-0221 原始规模存在单位不一致，原输入与原输出保留；该数据边界已单独记录，本补充未为提高结果而删除或修正该组。',
        '- 12 对同一助手顺序互换检查已另行完成，0 对偏好改变；它不能消除设计参与、既有版本知识或缺少独立评阅者的限制。','',
        '## 证据与图表','',
        '- [逐指标与逐项目源数据](analysis/CP01_condition_diagnostics_001/summary_001.json)，同目录每项保存完整项目单元、缺失界限、重采样和影响分析。',
        '- [分析与源文件哈希](analysis/CP01_condition_diagnostics_001/manifest.json)。',
        '- [条件比较图 PNG](figures/CP01_condition_diagnostics_001/CP01_information_conditions.png) / [SVG](figures/CP01_condition_diagnostics_001/CP01_information_conditions.svg) / [作图数据](figures/CP01_condition_diagnostics_001/figure_data.csv)。',
        '- [顺序互换检查](CP01顺序互换复核_001.md)。','',
        '整体工作仍未结束：CP01 的修复后回答需与首轮分开评阅，其他微观队列评分和宏观真实结果也待完成。本补充不能替代全实验阶段汇总。','']
    path=MASTER/'CP01资料条件业务结果_001.md'
    text='\n'.join(lines)
    if path.exists(): assert path.read_text(encoding='utf-8')==text
    else: path.write_text(text,encoding='utf-8')
    save(SOURCE/'report_source_001.json',{'summary_sha256':sha(SOURCE/'summary_001.json'),
        'report_sha256':sha(path),'report_script_sha256':sha(__file__),'new_model_calls':0})
    print('Saved source-derived CP01 condition report.')


if __name__=='__main__': main()
