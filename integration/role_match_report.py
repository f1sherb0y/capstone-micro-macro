"""Publish explicit multidimensional tables from frozen role retrieval rankings."""
import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from integration.role_match_metrics import score_roles

ROOT = Path(__file__).resolve().parents[1]
KS = (1, 3, 5, 12)
UNKNOWN = {'', '-', '/', '无', '未知', '暂无', '未披露', '无法获取', '不详', '未提供'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, records):
    if not records:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                         for k, v in row.items()} for row in records)


def summarize(records, field, hit_field):
    groups = defaultdict(list)
    for row in records:
        groups[str(row.get(field) or '资料缺失')].append(row)
    return [{'group': name, 'n': len(group), **{
        f'hits_top{k}': sum(row[hit_field][str(k)] for row in group) for k in KS}}
        for name, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--report', type=Path, default=ROOT / '组会与汇报/实验结果/2026-11-02_全量角色匹配多维统计.md')
    args = parser.parse_args()
    directory = args.directory.resolve()
    source = ROOT / 'data/test_sources/casebank_enterprise_matched'
    projects = {r['case_id']: r for r in rows(source / 'simulation_input_projects.csv')}
    companies = {r['company_id']: r for r in rows(source / 'simulation_input_enterprises.csv')}
    labels = rows(source / 'hidden_benchmark_project_enterprises.csv')
    predictions = read(directory / 'authored_rankings.json')
    manifest = read(directory / 'manifest.json')
    for name, expected in manifest['source_sha256'].items():
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected
    assert {p['case_id'] for p in predictions} == set(projects)
    assert len(predictions) == len(projects) * len(manifest['roles'])
    assert all(len(p['ranked_company_ids']) == len(set(p['ranked_company_ids'])) == 50 for p in predictions)
    result = score_roles(predictions, labels, ks=KS)
    result['scope'] = 'offline_role_candidate_retrieval_not_model_decisions_or_macro_awards'
    result['input_case_count'] = len(projects)
    result['model_calls'] = 0
    result['authored_rankings_sha256'] = hashlib.sha256((directory / 'authored_rankings.json').read_bytes()).hexdigest()
    result['benchmark_sha256'] = hashlib.sha256((source / 'hidden_benchmark_project_enterprises.csv').read_bytes()).hexdigest()
    project_records = []
    for row in result['projects']:
        source_project = projects[row['case_id']]
        completeness = sum(source_project.get(k, '').strip() not in UNKNOWN for k in
            ('project_name', 'project_type', 'location', 'delivery_mode', 'owner_name', 'scale'))
        project_records.append({**source_project, **row,
            'labelled_role_count_group': '3及以上' if row['labelled_role_count'] >= 3 else str(row['labelled_role_count']),
            'project_info_completeness': '5至6项' if completeness >= 5 else '3至4项' if completeness >= 3 else '0至2项'})
    role_records = []
    profile_fields = ('company_name', 'business_scope', 'industry', 'office_location', 'certifications', 'staff_scale')
    for row in result['project_roles']:
        profiles = [companies.get(key, {}) for key in row['historical_company_ids']]
        completeness = sum(sum(p.get(k, '').strip() not in UNKNOWN for k in profile_fields) for p in profiles) / (len(profile_fields) * len(profiles))
        project = projects[row['case_id']]
        role_records.append({**row, 'profile_completeness': '较全 ≥80%' if completeness >= .8 else '中等 50%至80%' if completeness >= .5 else '较少 <50%',
            'region_role': (project['location'] or '地区缺失') + '／' + row['role'],
            'mode_role': (project['delivery_mode'] or '模式缺失') + '／' + row['role']})
    definitions = [
        ('role', '历史角色', role_records, 'role', 'hit_at_k', '项目与角色组合'),
        ('region', '项目地区', project_records, 'location', 'any_role_hit_at_k', '项目'),
        ('project_type', '项目类型', project_records, 'project_type', 'any_role_hit_at_k', '项目'),
        ('delivery_mode', '原始交付模式字段', project_records, 'delivery_mode', 'any_role_hit_at_k', '项目'),
        ('cooperation', '合作方向', project_records, 'cooperation_direction', 'any_role_hit_at_k', '项目'),
        ('mic', 'MiC 标记', project_records, 'is_mic', 'any_role_hit_at_k', '项目'),
        ('role_count', '可核对的角色数量', project_records, 'labelled_role_count_group', 'any_role_hit_at_k', '项目'),
        ('project_info', '项目资料完整度', project_records, 'project_info_completeness', 'any_role_hit_at_k', '项目'),
        ('enterprise_info', '历史企业资料完整度', role_records, 'profile_completeness', 'hit_at_k', '项目与角色组合'),
        ('region_role', '地区与角色交叉', role_records, 'region_role', 'hit_at_k', '项目与角色组合'),
        ('mode_role', '交付模式与角色交叉', role_records, 'mode_role', 'hit_at_k', '项目与角色组合'),
    ]
    tables = {name: summarize(records, field, hit_field) for name, _, records, field, hit_field, _ in definitions}
    export = directory / 'dimension_tables'; export.mkdir(exist_ok=True)
    for name, data in tables.items():
        write_csv(export / (name + '.csv'), data)
    write_csv(export / 'project_details.csv', project_records)
    write_csv(export / 'role_details.csv', role_records)
    (directory / 'any_role_metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (export / 'tables.json').write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding='utf-8')
    report = args.report.resolve(); report.parent.mkdir(parents=True, exist_ok=True)
    link = lambda path, title: f'[{title}]({Path(os.path.relpath(path, report.parent)).as_posix()})'
    rate = lambda hits, n: f'{hits}/{n}（{hits/n:.1%}）' if n else '无可评分样本'
    lines = ['# 全量角色匹配多维统计 离线检索评估', '',
        '组会日期：2026 年 11 月 2 日。使用全部 352 个项目及 904 家企业；结果来自公开资料的本地候选检索，不是新增模型决策或完整宏观仿真结果。', '',
        '**计分规则：同一项目中，至少一个角色选中历史上同角色的一家企业，即计该项目命中。** 公司 ID 和历史角色必须同时匹配；不要求整套项目团队全部匹配，也不把只有“角色类型相同”算成命中。', '',
        'Top1 表示各角色只取第一家公司；Top3／Top5 表示检查各角色前三／前五家。Top12 是较宽候选覆盖，单独展示，不能代替选一家公司的准确率。', '',
        f"全部项目均完成预先固定的 11 种角色查询，共 {len(predictions):,} 次本地检索；其中 {result['eligible_project_role_pairs']} 个项目与角色组合有历史标签，可以评分。无历史标签的角色不计为失败。", '',
        '## 全量总体结果', '', '| 口径 | Top1 | Top3 | Top5 | 候选前12 |', '| --- | ---: | ---: | ---: | ---: |']
    overall = result['project_any_role']
    lines.append('| 项目至少一个角色命中 | ' + ' | '.join(rate(overall[str(k)]['hits'], overall[str(k)]['denominator']) for k in KS) + ' |')
    lines.append('| 项目与角色组合逐项命中 | ' + ' | '.join(rate(result['role_pair_hits'][str(k)]['hits'], result['role_pair_hits'][str(k)]['denominator']) for k in KS) + ' |')
    lines += ['', '## 各维度统计', '',
        '下列表格保留全部分组，按样本数量排列。不同维度之间会重复使用同一项目，不能把各表命中数相加。样本少于 10 的分组单独标记；较高比例是探索线索，不构成稳定优势证明。', '']
    observations = []
    for name, title, records, field, hit_field, unit in definitions:
        table = tables[name]
        displayed = table if name not in {'region_role', 'mode_role'} else [row for row in table if row['n'] >= 10]
        lines += [f'### {title}', '', f'分母单位：{unit}。' + ('正文只列样本不少于 10 的交叉分组，完整分组见配套数据。' if name in {'region_role', 'mode_role'} else ''), '',
            '| 分组 | 样本数 | Top1 | Top3 | Top5 | 前12覆盖 | 提示 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
        for row in displayed:
            lines.append('| ' + row['group'].replace('|', '／') + f" | {row['n']} | " + ' | '.join(rate(row[f'hits_top{k}'], row['n']) for k in KS)
                         + (' | 小样本 |' if row['n'] < 10 else ' | 探索统计 |'))
        if not displayed:
            lines.append('| 无达到显示样本数的分组 | — | — | — | — | — | 见完整数据 |')
        lines += ['', link(export / (name + '.csv'), '完整分组数据'), '']
        if name in {'role', 'region', 'project_type', 'delivery_mode'}:
            observations.extend({'dimension': title, **row} for row in table if row['n'] >= 20)
    observations.sort(key=lambda row: (-row['hits_top5']/row['n'], -row['hits_top1']/row['n'], -row['n']))
    lines += ['## 样本不少于20的较高观察值', '',
        '固定使用 Top5 对候选表现排序，同时列 Top1；这里没有剔除弱分组，全部结果保留在前文。分组之间重叠，且没有做独立验证或多重比较校正。', '',
        '| 维度 | 分组 | 样本数 | Top1 | Top5 |', '| --- | --- | ---: | ---: | ---: |']
    for row in observations[:10]:
        lines.append(f"| {row['dimension']} | {row['group']} | {row['n']} | {rate(row['hits_top1'],row['n'])} | {rate(row['hits_top5'],row['n'])} |")
    lines += ['', '## 已命中的具体项目', '',
        '以下列出 Top5 至少有一个角色命中的项目，便于核查公司的角色和来源。未命中项目仍全部保留在明细中。', '',
        '| 案例 | 项目 | 地区 | Top1 命中角色 | Top5 命中角色 |', '| --- | --- | --- | --- | --- |']
    for row in project_records:
        if row['any_role_hit_at_k']['5']:
            lines.append(f"| {row['case_id']} | {row['project_name'].replace('|','／')} | {row['location'] or '缺失'} | {'、'.join(row['matched_roles_at_k']['1']) or '无'} | {'、'.join(row['matched_roles_at_k']['5'])} |")
    lines += ['', '## 与完整微宏观运行的区别', '',
        '352 例都能用于这里的角色候选匹配，所以角色评价不需要限定为九例。九例的限制仅属于旧版澳门 DBB 基础设施完整生命周期适配；27 个 DBB 中其余 18 例还需地区或类型适配，153 个 EPC 需要设计施工责任及采购顺序适配，140 例交付模式缺失，另外 32 例原始模式或合同范围需分别核对。它们没有被改成 DBB。', '',
        '当前检索优先考虑资料中有目标角色业务描述的企业，再按项目主题相关性排序。业务描述不是已核验的执业资质；未知记录仍保留。结果使用严格公司 ID，未把母公司、分公司或联合体合并来增加命中。', '',
        '资料完整度只作为事后分析维度，历史关系仅在所有候选排序保存完成后参与评分。企业画像缺少投标前时间标识，因此不能把这些探索统计称为无时间泄漏的历史预测实验。下一步应针对有代表性的角色和项目核实资料，而不按已知中标名单补候选。', '',
        '## 数据入口', '',
        '- ' + link(directory / 'manifest.json', '输入与算法哈希清单'),
        '- ' + link(directory / 'summary.json', '全量处理及模式统计'),
        '- ' + link(directory / 'any_role_metrics.json', '角色匹配完整指标'),
        '- ' + link(export / 'project_details.csv', '全部352个项目明细'),
        '- ' + link(export / 'role_details.csv', '全部可评分项目与角色明细'),
        '- ' + link(ROOT / 'docs/案例库评估V2.md', '新版候选与宏观接线说明'),
    ]
    report.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'report': str(report), 'projects': len(project_records), 'role_pairs': len(role_records),
        'dimension_tables': len(tables), 'project_any_role': overall}, ensure_ascii=False))


if __name__ == '__main__':
    main()
