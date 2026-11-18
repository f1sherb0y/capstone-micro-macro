"""Input-only DBB domain/region scenarios for the fixed CP03X candidates.

Real source type, region and named work scope are retained. Technical methods,
local-operating eligibility and every numeric capacity/cost are declared
controlled assumptions. This does not estimate local qualifications or costs.
"""
from copy import deepcopy
from dataclasses import asdict
import json

from integration.catalog import SharedCatalog, DEFAULT_SOURCE, ROLE_WORDS, stable_id
from integration.shared_data import SharedDataset
from src.models import Company

REGIONS = {'澳门': 'Macau', '澳門': 'Macau', '香港': 'Hong Kong', '广州': 'Guangzhou',
           '廣州': 'Guangzhou', '东莞': 'Dongguan', '東莞': 'Dongguan'}
NATIVE_TYPES = {'居住建筑': 'building', '公共服务建筑': 'building', '文旅与酒店娱乐项目': 'building',
                '市政与公共基础设施': 'infrastructure', '交通基础设施': 'infrastructure'}

DOMAIN_TASKS = {
    'foundation_and_basement': ('基础与地库工作包', '拟议基础及地库方案与结构接口复核', '基础与地库施工', '基础结构施工材料与文档'),
    'parking_facility': ('停车场设施', '拟议停车场布置、结构与通行接口设计', '停车场结构与交通设施施工', '停车场结构及配套设施材料'),
    'interior_fitout': ('长者日间中心装修包', '拟议室内装修、消防及服务空间接口设计', '室内装修及设施安装配合', '装修材料及设施产品文档'),
    'building_repair': ('公共房屋修复包', '拟议缺陷勘查、修复方案及既有建筑接口复核', '既有建筑修复施工', '修复材料及质量文档'),
    'pile_foundation': ('中央化验大楼桩基础包', '拟议桩基础布置、工法与结构接口复核', '桩基础成孔成桩与检测配合', '桩基础施工材料与检测文档'),
    'building_foundation': ('大楼与连接设施基础包', '拟议基础方案、施工接口与结构复核', '建筑及连接设施基础施工', '基础结构材料与质量文档'),
    'site_grading': ('公共房屋场地平整包', '拟议场地整平、临时排水与边界接口设计', '场地平整与临时排水作业', '场地整平及临时设施材料'),
    'fire_shutter_replacement': ('防火卷闸更换包', '拟议卷闸尺寸接口、功能要求与更换方案复核', '防火卷闸拆换与安装测试', '防火卷闸及配套部件质量保修文档'),
    'diaphragm_wall_and_pile_foundation': ('地下连续墙与桩基础包', '拟议地下连续墙、桩基础及连接结构接口设计', '地下连续墙与桩基础施工', '地下结构材料与检验记录'),
    'border_building_construction_and_extension': ('边检大楼建造及扩建命名范围', '拟议边检建筑及既有设施连接接口设计', '边检大楼建筑及扩建接口施工', '建筑结构与配套设施材料'),
    'housing_development': ('暂住房及置换房命名范围', '拟议住宅建筑、配套设施与专业接口设计', '住宅建筑及配套设施施工', '住宅建筑结构及配套材料'),
    'school_dormitory_building': ('学生宿舍建筑', '拟议宿舍建筑、设施及校区接口设计', '学生宿舍建筑施工', '宿舍建筑及设施材料'),
    'school_building': ('小学建筑', '拟议教学建筑、活动空间与专业接口设计', '学校建筑及配套设施施工', '学校建筑结构及设施材料'),
    'hotel_building': ('酒店建筑', '拟议酒店建筑、设施与专业接口设计', '酒店建筑及设施接口施工', '酒店建筑结构与设施材料'),
    'ground_investigation': ('场地勘探工作包', '拟议勘探点位、作业方案与成果报告要求复核', '场地勘探、取样与成果记录作业', '勘探作业耗材及取样文档'),
    'hospital_building': ('医院建筑命名范围', '拟议医院建筑、服务设施及专业接口设计', '医院建筑及设施接口施工', '医院建筑结构与设施材料'),
}
DOMAIN_WORDS = {
    'foundation_and_basement': ('基础', '地基', '土木', '基礎'), 'pile_foundation': ('桩', '樁', '地基', '基础'),
    'building_foundation': ('地基', '基础', '土木', '基礎'),
    'diaphragm_wall_and_pile_foundation': ('地下', '地基', '桩', '樁'),
    'ground_investigation': ('勘探', '勘察', '地质', '地質', '岩土'),
    'interior_fitout': ('装修', '装饰', '裝修', '裝飾'), 'building_repair': ('修缮', '修繕', '维修', '維修'),
    'fire_shutter_replacement': ('消防', '防火', '门窗', '門窗'),
    'hotel_building': ('酒店', '旅馆', '旅館', '房屋建筑', '房屋建築'),
    'school_building': ('学校', '學校', '教育', '房屋建筑'),
    'school_dormitory_building': ('学校', '學校', '住宅', '房屋建筑'),
    'hospital_building': ('医院', '醫院', '医疗', '醫療', '房屋建筑'),
    'housing_development': ('住宅', '房屋建筑', '房屋建築'),
    'parking_facility': ('停车', '停車', '交通', '建筑', '建築'),
    'site_grading': ('土石方', '场地', '場地', '土木'),
    'border_building_construction_and_extension': ('公共建筑', '公共建築', '房屋建筑', '房屋建築'),
}


def source_region(value, *, project=False):
    value = value.strip()
    if value in REGIONS:
        return REGIONS[value]
    matches = {normalized for local, normalized in REGIONS.items() if local in value}
    if len(matches) == 1:
        return matches.pop()
    if project:
        raise ValueError('Source project region is unresolved; no default to Macau: ' + value)
    return None


def domain_spec(project, annotation):
    if project['delivery_mode'].strip().upper() != 'DBB':
        raise ValueError('Original DBB mode required; no EPC/D&B substitution')
    region = source_region(project['location'], project=True)
    native_type = NATIVE_TYPES.get(project['project_type'])
    if not native_type:
        raise ValueError('Unmapped source project type: ' + project['project_type'])
    domain = annotation['required_business_domain']
    if domain not in DOMAIN_TASKS:
        raise ValueError('No authored business/stage mapping for this domain')
    title, design, works, supplies = DOMAIN_TASKS[domain]
    return {'region': region, 'native_project_type': native_type, 'source_project_type': project['project_type'],
        'source_location': project['location'], 'domain': domain, 'scope_title': title,
        'work_type_code': 'controlled-' + domain, 'design_scope': design, 'construction_scope': works,
        'supply_scope': supplies, 'scope_class': annotation['scope_is_full_project_or_package'],
        'macro_family_id': annotation['macro_family_id'],
        'scope_note': annotation['annotation_reason'],
        'stage_mapping': ['命名范围的启动与融资', design, '该范围的造价咨询与独立合成文件审查',
            '两家情景承包方对同一命名作业范围各选一个合法定价选项', works,
            '该范围的供应交接、执行记录、完工与结算', '实际本业主结算进入后轮机会判断'],
        'boundary': 'Complete controlled lifecycle within the named source scope. Work-package/unclear rows are not full-parent-asset validation and are excluded from the whole-project stratum. No extra A02 windows. Domain text and methods are proposed scenario inputs, not observed technical specifications or calibrated physical behavior.'}


def scenario(catalog, config):
    """Build genuine role/domain inputs instead of the old road-only catalog."""
    with catalog.connect() as db:
        project_row = db.execute('SELECT payload FROM projects WHERE id=?', (config['case_id'],)).fetchone()
        enterprises = [json.loads(r[0]) for r in db.execute('SELECT payload FROM companies ORDER BY id')]
    if not project_row:
        raise ValueError('Unknown fixed source case')
    project = json.loads(project_row[0])
    spec = config['domain_region']
    assert spec['region'] == source_region(project['location'], project=True)
    assert spec['native_project_type'] == NATIVE_TYPES[project['project_type']]
    assert project['delivery_mode'].strip().upper() == 'DBB' and config['scenario_currency'] == 'HKD'
    cid, seed, budget, duration = project['case_id'], config['random_seed'], config['scenario_budget'], config['contract_duration']
    owner_name = project['owner_name'] or 'Scenario owner for ' + cid
    owner_id = stable_id('OWNER-', owner_name)
    companies = [asdict(Company(owner_id, owner_name, 'owner', '输入业主名称；采购与资金行为为明示控制情景。', [], [], [], [], '见情景参数', [], []))]
    selected, evidence = set(), {}
    words = DOMAIN_WORDS[spec['domain']]
    for role, count in [('designer', 2), ('supervisor', 2), ('contractor', 3), ('supplier', 2)]:
        ranked = []
        for enterprise in enterprises:
            if enterprise['company_id'] in selected or enterprise['company_name'] == owner_name:
                continue
            text = enterprise['business_scope'] + ' ' + enterprise['industry']
            role_terms = [word for word in ROLE_WORDS[role] if word in text]
            if not role_terms:
                continue
            domain_terms = [word for word in words if word in text]
            local_match = source_region(enterprise['office_location']) == spec['region']
            score = len(role_terms) + 3 * len(domain_terms) + 3 * local_match
            ranked.append((-score, stable_id('', f'CP03X/{cid}/{seed}/{role}/{enterprise["company_id"]}'), enterprise, role_terms, domain_terms))
        ranked.sort(key=lambda r: r[:2])
        if len(ranked) < count:
            raise ValueError(f'Insufficient source-supported {role} firms: {len(ranked)} < {count}')
        for _, _, enterprise, role_terms, domain_terms in ranked[:count]:
            key = enterprise['company_id']
            selected.add(key)
            evidence[key] = {'role_terms_in_scope_or_industry': role_terms, 'domain_terms': domain_terms,
                'source_office_location': enterprise['office_location'],
                'selection': 'Input scope/industry role evidence plus authored domain terms and source office match, fixed hash ties; no company-name-only role evidence, outcomes, costs or historical partners.',
                'eligibility_boundary': 'Text supports business direction only. Local operating permission, method competence and numerical capacity are explicit scenario assumptions, not verified firm qualifications.'}
            companies.append(asdict(Company(key, enterprise['company_name'], role,
                '公开经营范围：' + enterprise['business_scope'] + '；行业：' + enterprise['industry'] + '。本次角色与数值能力为控制情景，实际本地资格及资源未核实。',
                [], [], [enterprise['certifications']] if enterprise['certifications'] else [], [], '以控制情景参数为准', [], [])))
    payload = {'schema_version': '1.0', 'companies': companies, 'projects': [{
        'project_id': cid, 'name': project['project_name'], 'owner_id': owner_id,
        'region': spec['region'], 'project_type': spec['native_project_type'],
        'scope': '；'.join([project['project_type'], project['scale'], project['project_name'], spec['scope_note']]),
        'budget': budget, 'currency': 'HKD', 'duration_months': duration, 'delivery_mode': 'DBB'}],
        'packages': [], 'environment': {}, 'policy': {}, 'assumptions': {
            'version': 'CP03X-domain-region-input.v1', 'source_note': '真实公开输入背景＋领域内命名范围的明示DBB控制情景；不是历史项目回放、地方资质验证、币种换算或物理领域模型校准。',
            'catalog': catalog.metadata(), 'candidate_selection': evidence, 'domain_region': deepcopy(spec),
            'eligibility': '列入企业的本次独立参与及方法许可为初始合成授权，不从注册资本、历史关系或未记载资格反推。',
            'units': {'resource': 'normalized_enterprise_capacity', 'time': 'months', 'currency': 'HKD'},
            'enterprise_parameters': {}, 'enterprise_regions': {},
            'support_agents': [{'agent_id': 'REGULATOR-' + spec['region'], 'name': 'Scenario regulator', 'role': 'Government',
                'enterprise_type': 'scenario_support', 'region': spec['region'], 'total_resource_capacity': 3, 'policy_adaptability': .9}],
            'budget_origin': 'controlled_assumption_not_observed_cost', 'duration_origin': 'controlled_assumption_not_historical_duration',
            'regional_operations': 'Assigned local scenario operations; actual source office geography remains in candidate evidence; no local legal qualification inferred.'}}
    for company in companies:
        key = company['company_id']
        payload['assumptions']['enterprise_parameters'][key] = {'total_resource_capacity': 2., 'qualification_level': .85,
            **{k: .8 for k in ['financial_capacity', 'technical_capability', 'management_capability', 'design_capability', 'cost_estimation_capability',
                'construction_capability', 'safety_management_capability', 'quality_management_capability', 'supply_reliability', 'material_quality', 'policy_adaptability']}}
        payload['assumptions']['enterprise_regions'][key] = spec['region']
    def package(suffix, kind, fraction, scope, dependencies=(), parent=None):
        role = {'design': 'designer', 'cost_consulting': 'supervisor', 'construction': 'contractor', 'supply': 'supplier'}[kind]
        return {'package_id': f'{cid}/{suffix}', 'project_id': cid, 'kind': kind,
            'buyer_id': '$construction_lead' if parent else owner_id, 'name': scope, 'scope': scope,
            'budget': round(budget * fraction, 2), 'currency': 'HKD', 'resource_required': .7 if kind == 'construction' else .25,
            'depends_on': list(dependencies), 'cost_inclusion': 'included_in_parent' if parent else 'owner_additional',
            'parent_package_id': parent, 'candidate_ids': [c['company_id'] for c in companies if c['company_role'] == role]}
    payload['packages'] = [package('design', 'design', .03, spec['design_scope']),
        package('cost', 'cost_consulting', .015, spec['scope_title'] + '造价咨询及合同成本管理')]
    # Catalog packages describe domain work streams. The native experiment
    # remains one integrated named work scope, two competing A02 subjects,
    # eight signed-contract handoffs if awarded, and no additional windows.
    for suffix, scope in [('A', spec['construction_scope']), ('B', spec['construction_scope'] + '的配套与接口作业')]:
        parent = f'{cid}/construction-{suffix}'
        payload['packages'] += [package('construction-' + suffix, 'construction', .425, scope, [f'{cid}/design', f'{cid}/cost']),
            package('supply-' + suffix, 'supply', .12, spec['supply_scope'], [parent], parent)]
    dataset = SharedDataset(payload)
    catalog.save_scenario(dataset)
    return dataset
