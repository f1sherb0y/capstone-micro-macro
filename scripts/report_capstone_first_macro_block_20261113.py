"""Business interpretation of the first verified fixed native four-arm block."""
from decimal import Decimal
from pathlib import Path
import json
from review_capstone_all_20261113 import MASTER,ROOT,read,save,sha
from load_capstone_macro_results_20261113 import chain_table_row

SOURCE=MASTER/'macro_results/first_fixed_block_001'
OUT=MASTER/'figures/first_fixed_macro_block_001'


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    manifest=read(SOURCE/'manifest.json')
    for name,digest in manifest['artifact_sha256'].items():assert sha(SOURCE/name)==digest
    rows=read(SOURCE/'first_block_observations.json')
    assert len(rows)==4 and {r['arm'] for r in rows}=={'R','S','D3','S4'}
    assert len({r['fixed_fact_block_sha256'] for r in rows})==1
    assert all(r['technical_verification']['technical_integrity_passed'] for r in rows)
    baseline=rows[0]['observations']
    identical=all(r['observations']==baseline for r in rows)
    assert identical,'This descriptive report only asserts equality after comparing the actual observations'
    choices={r['arm']:{p['organization_id']:p['canonical_commercial_choice'] for p in r['pricing']} for r in rows}
    assert all(len(v)==2 for v in choices.values())
    comparable=set(choices['D3'])&set(choices['S4'])
    disagreements=sum(choices['D3'][k]!=choices['S4'][k] for k in comparable)
    assert len(comparable)==2
    quotes=[p for r in rows for p in r['pricing']]
    assert len(quotes)==8 and all(p['actual_bid_event_links'] for p in quotes)
    assert all(Decimal(p['bid_price'])==Decimal('110000000') and p['markup_fraction']==.1 for p in quotes)
    fields=['actual_cost','actual_progress','planned_progress','overall_quality','design_quality',
        'construction_quality','material_quality','delay_days','supply_delay_risk','safety_risk','claim_risk','dispute_risk']
    paths=[];pins={}
    for r in rows:
        path=ROOT/r['formal_chain_directory']/'runtime/result.json'
        assert sha(path)==manifest['source_sha256'][path.relative_to(ROOT).as_posix()]
        projects=read(path)['simulation']['project_results']
        p=next(p for p in projects if p['project_id']==r['case_id'])
        trajectory=[{'tick':e['tick'],'stage':e['stage'],**{k:e['data'].get(k) for k in fields}}
            for e in p['event_log'] if e['event_type']=='project_state_updated'
            and e['tick']>=r['observations']['valid_construction_first_tick']]
        assert trajectory
        paths.append(trajectory);pins[str(path.relative_to(ROOT))]=sha(path)
    assert all(p==paths[0] for p in paths),'Never draw one shared curve without verifying all four paths'
    observed=baseline;metric=chain_table_row(rows[0]);o4=disagreements/len(comparable)
    summary={'source_case_id':rows[0]['case_id'],'source_project_name':rows[0]['source_project_name'],
        'source_scope_stratum':rows[0]['scope_stratum'],'source_region':rows[0]['source_region'],
        'source_groups':1,'repeat_blocks':1,'mechanism_chains':4,'planned_catalogue_slots':324,
        'four_arm_observations_identical':identical,'four_arm_actual_state_trajectories_identical':True,
        'canonical_choices_by_arm':choices,'O4_D3_vs_S4':{'comparable_actor_pairs':2,'disagreements':disagreements,
            'fraction':o4,'not_independent_project_pairs':True},
        'T1_each_actual_bid_markup':.1,'T1_actual_bid_worker_rows':8,
        'T2_to_T8_shared_observations':observed,'model_currency':'HKD',
        'progress_gap_definition':'100*(actual_progress-planned_progress), snapshot field; not delay_days.',
        'delay_gap_direction_caveat':{'progress_gap_pp':metric['T4_final_progress_gap_pp'],
            'reported_delay_days':metric['T4_reported_delay_days'],
            'inference':'Different internal progress measures, retained separately; neither converted into a real completion-time benefit.'},
        'interpretation':['The first fixed block has identical commercial choices and observed downstream states; no observed macro gain in this block.',
            'One source group and one repeat block do not support a project-population effect, confidence interval or equivalence claim.',
            'Canonical commercial actions were compared; motivations and member-comment quality were not inferred.',
            'Budget, contract, cost and state variables are controlled simulation evidence, not audited real-project values.'],
        'new_model_calls':0,'new_simulations':0,'source_manifest_sha256':sha(SOURCE/'manifest.json')}
    save(SOURCE/'business_interpretation_001.json',summary)
    out=MASTER/'宏观首块业务结果_001.md';assert not out.exists()
    text=f'''# 宏观首个固定对照块：业务结果

来源为“{rows[0]['source_project_name']}”（CASE-0010），标注为具名优化工程范围 `named_intervention_scope`，不是已核实独立完整现实项目。仅包含repeat=1、seed=42的R／S／D3／S4四条正式原生链，外部事实块哈希相同，均已跑完固定48 tick并通过原生链核验。按既有执行顺序取首块，无收益择例；324个计划槽位完整保留，其他320条未在本表提取。

四组的实际商业行动、T2—T8观测和原始状态轨迹均相同。本块没有观测到宏观收益差异；这不是所有项目无效或统计等效的证据。

| 指标 | 四组共同观测 | 解释边界 |
| --- | --- | --- |
| T1 报价加成 | 每个实际A02报价均为10% | 两企业×四机制共8个worker；不是8个独立项目或实得利润 |
| O4 D3−S4商业行动分歧 | {disagreements}/{len(comparable)}，{o4:.0%} | 对应同一块的两个企业主体；只比规范化商业行动，不推断动机 |
| T2 合同／初始预算 | 110,000,000／130,000,000={100*metric['T2_contract_to_budget']:.2f}% | HKD、受控模拟金额；较低合同额不等实际节约 |
| T3 完工实际成本 | 152,652,347.57 HKD | 模型内部成本，不是已审计现实成本 |
| T3 相对初始预算偏差 | +{100*metric['T3_final_cost_vs_budget']:.2f}% | 分母130,000,000 |
| T3 相对估算成本偏差 | +{100*metric['T3_final_cost_vs_estimate']:.2f}% | 分母128,440,000 |
| T3 相对签约金额偏差 | +{100*metric['T3_final_cost_vs_contract']:.2f}% | 分母110,000,000；三参考基准不能混称同一超支率 |
| T4 固定终点进度差 | +{metric['T4_final_progress_gap_pp']:.2f}个百分点 | 100×(实际进度−计划进度)的状态快照值 |
| T4 模型报告延期 | {metric['T4_reported_delay_days']:.0f}天 | 与上一行是不同内部刻度，不能互相替换或直接推出提前竣工 |
| T5 完工总体质量 | {metric['T5_completion_overall_quality']:.5f} | 模型0—1状态，不是现实验收评分 |
| T7 授标／完工／结算 | 全部发生，tick分别19／43／45 | 四机制同一来源块，不据4/4估计全部项目成功率 |
| T8 检验不通过比例 | 3／7={100*metric['T8_inspection_failure_fraction']:.2f}% | 正文原事件：4次通过、3次不通过 |
| T8 供应延误／安全事件 | 1／0次 | 本块具有实际施工暴露；0安全事件不等零风险 |

| T6风险状态 | 施工期峰值 | 固定终点 |
| --- | ---: | ---: |
'''
    for key,label in [('supply_delay_risk','供应延误'),('safety_risk','安全'),('claim_risk','索赔'),('dispute_risk','争议')]:
        risk=observed['T6'][key];text+=f"| {label} | {risk['construction_peak']:.5f} | {risk['fixed_horizon_state']:.5f} |\n"
    text+='''
商业路径核对：八个A02实际worker的选择均为submit_bid、成本基数100,000,000 HKD、加成10%、商业allowance为0，分别链接到原始实际投标事件。四组合同额及后续事件状态一致，因此本块不能被解释为“讨论提高质量后带来成本、进度或风险改善”。评论的语义质量和不同选择的原因仍需另行评阅，不能由结构化选项反推。

进度解释须保留一个限制：末态实际进度高于计划20.83个百分点，模型同时累计报告延期31天。本表原样报告两个字段，不改公式、不把其中有利的一项单独写成真实工期收益；最后全样本讨论需解释这两种内部计量的定义与适用范围。

示例轨迹图只绘制经逐项验证完全重合的一条共同路径，含成本与总体质量，不伪造四条分离曲线。只用首次实质施工更新后的原始状态；实际观察覆盖保留在数据内，不把初始默认质量或无施工阶段当改进。图与数据见 `figures/first_fixed_macro_block_001/`。

本块用于展示可追溯的商业选择→实际投标→授标→项目状态链。是1个来源组、1个重复块的描述，没有置信区间或总体显著性推断，也没有独立专家验证。各批继续按原固定样本、预算与停止规则运行，不因同值删题、改参数或追加付费尝试。

证据：`macro_results/first_fixed_block_001/manifest.json`绑定四条原始输入、SQLite、输出、实际请求和既有提取器；`first_block_metrics.csv`、`first_block_observations.json`及`business_interpretation_001.json`可复算。新增模型调用及新增模拟均为0。
'''
    out.write_text(text,encoding='utf-8')
    assert not OUT.exists();OUT.mkdir(parents=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'svg.fonttype':'none',
        'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(13,5.6));fig.subplots_adjust(left=.08,right=.96,bottom=.28,top=.69,wspace=.28)
    trajectory=paths[0];ticks=[p['tick'] for p in trajectory]
    axes[0].plot(ticks,[p['actual_cost']/1e6 for p in trajectory],color='#237d87',linewidth=2.8,label='Shared actual cost')
    axes[0].axhline(130,color='#be7b31',linestyle='--',linewidth=1.5,label='Initial budget: 130m')
    axes[0].axhline(110,color='#7b6ba6',linestyle=':',linewidth=1.8,label='Signed contract: 110m')
    axes[0].set_ylabel('Model cost / reference (HKD million)');axes[0].legend(frameon=False,fontsize=9,loc='upper left')
    axes[1].plot(ticks,[p['overall_quality'] for p in trajectory],color='#237d87',linewidth=2.8)
    axes[1].set_ylabel('Model overall quality (0–1)');axes[1].set_ylim(0,1)
    for ax,title in zip(axes,['Cost and fixed monetary references','Overall quality trajectory']):
        ax.set_xlabel('Simulation tick');ax.set_title(title,loc='left',fontsize=12,pad=16)
        ax.grid(color='#e7ebef',linewidth=.7,alpha=.8);ax.set_axisbelow(True)
    fig.suptitle('First fixed macro block | Identical paths across four arms',x=.08,y=.96,ha='left',fontsize=19,fontweight='bold',color='#19384f')
    fig.text(.08,.86,'CASE-0010 · repeat 1 · seed 42 · R / S / D3 / S4 · one shared curve after substantive construction starts',fontsize=10,color='#526170')
    fig.text(.08,.17,'All four original state trajectories were compared before drawing one coincident curve; no simulated or inferred separation.',fontsize=10,color='#40576a')
    fig.text(.08,.10,'One source group and one block, not a population effect. Model-internal values; no measured real-project benefit.',fontsize=10,color='#526170')
    fig.text(.08,.045,'Progress gap and reported delay use different internal measures and remain separately reported in the accompanying table.',fontsize=9,color='#526170')
    for ext in ['png','svg']:fig.savefig(OUT/f'first_fixed_macro_block_trajectories.{ext}',dpi=240,facecolor='white')
    plt.close(fig)
    save(OUT/'trajectory_data.json',{'all_four_identical':True,'displayed_common_path':trajectory,
        'source_manifest_sha256':sha(SOURCE/'manifest.json'),'currency':'HKD','source_groups':1,'new_model_calls':0})
    save(OUT/'manifest.json',{'original_result_sha256':pins,'source_manifest_sha256':sha(SOURCE/'manifest.json'),
        'script_sha256':sha(Path(__file__)),'business_report_sha256':sha(out),
        'artifact_sha256':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()},'new_model_calls':0,'new_simulations':0})
    print('First-block business table, common cost/quality trajectories and source bindings saved;no global effect claim.')


if __name__=='__main__':main()
