"""Explicit source-name scope/family annotations, without eligibility shortcuts."""
from collections import Counter

from capstone_cp_common_20261112 import ROOT, read, save, sha

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-13_总实验收尾/macro_preparation'
SOURCE = BASE / '指标补充/2026-11-12_完整方案_v4/scope.json'

# Authored after reading all 27 source names. These are conservative study
# groupings, not externally verified historical project hierarchies.
ANNOTATIONS = {
    'CASE-0001': ('named_intervention_scope', 'waterfront_reinforcement', 'single-CASE-0001', '研究堤围加固这一命名干预，不外推整个湖区工程。'),
    'CASE-0003': ('named_whole_project_scope', 'reservoir_expansion', 'single-CASE-0003', '命名范围为水库扩容，不把库容改变量直接换成实际成本或生产率。'),
    'CASE-0004': ('work_package_or_phase', 'foundation_and_basement', 'family-muralhas-public-housing', '仅公共房屋的基础及地库工作包，不能标成整栋公屋交付。'),
    'CASE-0005': ('work_package_or_phase', 'road_connection', 'family-fourth-bridge-peripheral-roads', '第四跨海大桥周边路网的口岸人工岛连接线。'),
    'CASE-0006': ('work_package_or_phase', 'road_connection', 'family-fourth-bridge-peripheral-roads', '同一路网的A区东轴线第1期，与其他连接线有共同上位项目名称。'),
    'CASE-0007': ('work_package_or_phase', 'road_connection', 'family-fourth-bridge-peripheral-roads', '同一路网的北安区连接线，联合分析时按家族敏感性处理。'),
    'CASE-0008': ('named_facility_scope', 'parking_facility', 'family-macau-science-centre', '研究停车场这一命名设施，不当作科学馆整体建造。'),
    'CASE-0009': ('work_package_or_phase', 'interior_fitout', 'family-ilha-verde-social-housing-day-centre', '长者日间中心装修包，不当作社会房屋整体开发。'),
    'CASE-0010': ('named_intervention_scope', 'ecological_optimization', 'single-CASE-0010', '生态保护区二区优化干预；具体工程量和技术措施未由名称给出。'),
    'CASE-0011': ('work_package_or_phase', 'building_repair', 'family-ilha-verde-public-housing-lots1and2', '公共房屋第1及2地段修复，与卷闸更换采用共同名称家族。'),
    'CASE-0012': ('work_package_or_phase', 'demolition', 'family-guangdong-macau-new-channel-qingmao', '南粤批发市场清拆，按共同粤澳新通道名称保守并入家族；并非已核实合同隶属关系。'),
    'CASE-0013': ('work_package_or_phase', 'pile_foundation', 'family-islands-health-complex-central-lab', '中央化验大楼桩基础，78支桩是公开规模描述，不是完整医院数量清单。'),
    'CASE-0014': ('named_intervention_scope', 'pipeline_diversion_and_grading', 'single-CASE-0014', '排放管改道与周边平整这一命名干预，不扩为污水厂整体。'),
    'CASE-0015': ('work_package_or_phase', 'building_foundation', 'family-conde-hospital-phase1-public-health', '医院第一期扩建中公共卫生专科大楼基础，不是离岛医疗中央化验大楼。'),
    'CASE-0016': ('work_package_or_phase', 'site_grading', 'family-wai-long-public-housing', '公屋场地平整包，不当作完整公屋建设与交付。'),
    'CASE-0017': ('work_package_or_phase', 'fire_shutter_replacement', 'family-ilha-verde-public-housing-lots1and2', '100樘防火卷闸更换，与同地段修复按名称共同家族处理。'),
    'CASE-0018': ('work_package_or_phase', 'building_foundation', 'family-guangdong-macau-new-channel-qingmao', '青茂口岸联检大楼与连接通道基础包，与同名地下连续墙包不算独立整项目。'),
    'CASE-0019': ('work_package_or_phase', 'pedestrian_tunnel_improvement', 'family-zoneA-peninsula-connection', '研究连接通道的行人隧道改善，不扩为全部填海工程。'),
    'CASE-0020': ('work_package_or_phase', 'diaphragm_wall_and_pile_foundation', 'family-guangdong-macau-new-channel-qingmao', '青茂口岸地下连续墙及连接通道桩基础，与CASE-0018共用上位名称。'),
    'CASE-0021': ('scope_unclear_from_input', 'border_building_construction_and_extension', 'family-border-gate-building', '建造及扩建可能包含多期，现有输入不足以断定单次完整合同或各阶段边界。'),
    'CASE-0032': ('named_whole_project_scope', 'housing_development', 'family-areia-preta-plotP-housing', '命名范围为暂住房及置换房；完整性仅按输入名称标注，未外部核实全部开发边界。'),
    'CASE-0049': ('named_building_scope_within_larger_facility', 'school_dormitory_building', 'family-huangpu-experimental-school', '研究学生宿舍建造合同，不代表整个学校项目。'),
    'CASE-0051': ('named_whole_project_scope', 'school_building', 'family-dongguan-xiangshi-second-primary', '保留东莞原地区；完整性为名称层面，未将未记录分期视为不存在。'),
    'CASE-0204': ('named_whole_project_scope', 'hotel_building', 'family-the13-hotel', '保留酒店建筑领域，不改写为基础设施；实际经营表现不进入机制后果。'),
    'CASE-0206': ('named_whole_project_scope', 'hotel_building', 'family-grand-lisboa-hotel', '保留新葡京酒店建筑背景；成本工期仍为明示模拟假设。'),
    'CASE-0261': ('work_package_or_phase', 'ground_investigation', 'family-northern-metropolis-northwest-investigation', '2023–25场地勘探包，需独立勘探作业与报告交付映射，不能套成整个新界北开发的施工后果。'),
    'CASE-0315': ('scope_unclear_from_input', 'hospital_building', 'family-grantham-hospital', '名称仅医院，现有字段不足以判断新建、重建或某期工程；保留范围不确定性。'),
}


def main():
    candidates = read(SOURCE)['macro']['all_DBB_candidates']
    assert set(ANNOTATIONS) == {c['case_id'] for c in candidates}
    rows = []
    for original in candidates:
        scope, domain, family, reason = ANNOTATIONS[original['case_id']]
        rows.append({**original, 'scope_is_full_project_or_package': scope,
            'required_business_domain': domain, 'macro_family_id': family,
            'annotation_reason': reason, 'annotation_evidence': {
                'source': str(SOURCE.relative_to(ROOT)).replace('\\', '/'), 'source_sha256': sha(SOURCE),
                'input_fields': ['case_id', 'project_name', 'project_type', 'location', 'delivery_mode', 'scale'],
                'identity': 'Conservative author-assisted source-name annotation, not externally verified project genealogy'},
            'scope_confidence': 'unclear' if scope == 'scope_unclear_from_input' else 'explicit_name_scope_only',
            'eligibility': 'pending_genuine_domain_region_sources_and_native_stage_validation_not_excluded_for_implementation_cost',
            'whole_real_project_claim_permitted': False})
    summary = {'candidate_source_units': len(rows), 'provisional_name_based_families': len({r['macro_family_id'] for r in rows}),
        'scope_classes': dict(Counter(r['scope_is_full_project_or_package'] for r in rows)),
        'region_counts': dict(Counter(r['location'] for r in rows)),
        'meaning': 'Family count is a conservative analysis grouping, not 22 independently verified whole real-world projects.',
        'not_an_execution_or_eligibility_result': True, 'model_calls': 0}
    save(OUT / 'source_scope_and_families.json', rows)
    save(OUT / 'scope_annotation_summary.json', summary)
    print(summary)


if __name__ == '__main__':
    main()
