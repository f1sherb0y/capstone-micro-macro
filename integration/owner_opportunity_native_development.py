"""Build a frozen independent A03 template for actual native opportunity requests."""
import argparse
import hashlib
import json
from pathlib import Path

from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.project_financing_development import build_bundle as native_bundle
from integration.owner_opportunity_native import OwnerOpportunitySettings,OwnerOpportunityPolicy
from integration.owner_study_service_offer import OwnerStudyServiceOfferPolicy
from integration.owner_study_professional_intake import OwnerStudyProfessionalIntakePolicy
from integration.development_owner_funding import initial_owner_funding
from integration.bank_financing_development import initial_organization_actors
from decimal import Decimal


def build_bundle(directory,*,run_id,max_prior_initiations=1,max_prior_payment_requests=None,with_payment_project=False,
        max_prior_final_accounts=None,
        owner_funding=None,initiation_region_ids=None,with_observation=False,
        observation_minimum_demand='0',max_prior_declines=None,random_seed=None,
        with_proposal=False,proposal_review_cost='1000000',proposal_review_effort='0.5',
        study_question_code=None,study_target_interventions=(),study_budget='1000000',study_estimated_cost='500000',
        study_resource_requirement='0.5',study_duration=1,study_qualified=True,study_service_offer=None,study_professional_intake=None,
        allow_saved_recovery=False,query_saved_opportunity_on_error=False,initial_investment_policy=None,
        organization_actor_ids=None):
    if organization_actor_ids is not None and (not isinstance(organization_actor_ids,dict)
            or set(organization_actor_ids)-{'finance-owner-a','finance-qs','finance-architect'}):
        raise ValueError('Opportunity actor declarations must name the original Owner, QS or Architect')
    actors=initial_organization_actors(organization_actor_ids,
        ['finance-owner-a','finance-owner-b','finance-bank-a','finance-bank-b',
         *['finance-'+role for role in ('architect','engineer','qs','government','contractor','supplier')]])
    if initial_investment_policy is not None and initial_investment_policy not in {'evaluate','prepare_only','reject'}:
        raise ValueError('Initial investment policy must use an original evaluate/prepare_only/reject policy')
    if query_saved_opportunity_on_error and not allow_saved_recovery:
        raise ValueError('Saved opportunity query requires --allow-saved-recovery')
    if max_prior_final_accounts is not None and (type(max_prior_final_accounts) is not int or max_prior_final_accounts < 1):
        raise ValueError('Final-account review preference requires a positive integer event count')
    if with_proposal and not with_observation:
        raise ValueError('Original private proposal requires --with-observation')
    if not with_observation and observation_minimum_demand!='0':
        raise ValueError('Demand threshold requires the explicitly enabled original observation')
    owner_funding=initial_owner_funding(owner_funding)
    if owner_funding is not None and owner_funding.organization_id!='finance-owner-a':
        raise ValueError('Opportunity template requires its explicit original Owner cash disclosure')
    if with_payment_project and max_prior_payment_requests is None:
        raise ValueError('Payment-feedback development project requires an explicit request-count preference')
    if study_service_offer is not None:
        study_service_offer=OwnerStudyServiceOfferPolicy.model_validate(study_service_offer)
        if (study_question_code is None or study_service_offer.provider_organization_id not in
                {'finance-qs','finance-architect'}):
            raise ValueError('Standing research offer requires an explicit question and original professional provider')
    if study_professional_intake is not None:
        study_professional_intake=OwnerStudyProfessionalIntakePolicy.model_validate(study_professional_intake)
        if (study_question_code is None or study_service_offer is not None
                or study_professional_intake.provider_organization_id not in {'finance-qs','finance-architect'}
                or study_professional_intake.provider_organization_id=='finance-qs' and study_professional_intake.conflict_status is None):
            raise ValueError('Original professional study intake requires its question, provider and conflict source; standing offer is exclusive')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    native_bundle(directory/'native',run_id=run_id)
    read=lambda name:json.loads((directory/'native'/name).read_bytes())
    request=read('macro-request.json')
    if random_seed is not None:request['random_seed']=random_seed
    request['agents']=[a for a in request['agents'] if a['agent_id']!='finance-owner-b']
    request.update(ticks=2,target_project_count=2,max_active_projects=2)
    if with_payment_project:
        # These are declared pre-existing construction facts. Later payment
        # events must still be emitted by the original engine during this run.
        project_id='owner-existing-construction'
        request.update(target_project_count=3,max_active_projects=3,initial_projects=[{
            'project_id':project_id,'name':project_id,'project_type':'building','region':'Hong Kong',
            'owner_id':'finance-owner-a','initial_budget':2000000,'current_stage':'construction','stage_tick':0,
            'selected_contractor_id':'finance-contractor','contract_sum':1000000,
            'contracts':[{'contractor_id':'finance-contractor','contract_sum':1000000,'status':'active',
                'source':'explicit-preexisting-contract-not-current-micro-execution'}],
            'engagements':[{'engagement_id':project_id+'-initial-contractor','project_id':project_id,
                'agent_id':'finance-contractor','role':'Contractor','status':'active','start_stage':'construction',
                'joined_at_tick':0,'resource_allocation':1}],
            'flags':{'last_costed_progress':0.25},
            'performance':{'planned_duration':12,'elapsed_time':3,'actual_cost':250000,
                'actual_progress':0.25,'planned_progress':0.25,'overall_quality':1,
                'design_quality':1,'information_quality':1,'detected_defect_rate':0,'defect_rate':0,
                'safety_risk':0,'variation_risk':0,'claim_risk':0}}])
        next(a for a in request['agents'] if a['agent_id']=='finance-contractor')['occupied_resource']=1
    from integration.bootstrap import enable_gba_imports
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    request=SimulationCreateRequest.model_validate(request).model_dump(mode='json')
    template_path=Path(__file__).resolve().parents[1]/'tests/fixtures/roles/owner_investment.v1.json'
    template=json.loads(template_path.read_bytes())
    if owner_funding is not None:
        # Change initial source declarations before dynamic contexts, grants,
        # method inputs and evidence are formed. Never alter saved results.
        def bind(value):
            if isinstance(value,list):return [bind(v) for v in value]
            if not isinstance(value,dict):return value
            result={k:bind(v) for k,v in value.items()}
            if set(result)=={'kind','id','version'}:
                names={('FundingSource','actual-account'):'borrower-cash',
                    ('Obligation','existing-other-project-fee'):'due-mirror'}
                result['id']=names.get((result['kind'],result['id']),result['id'])
            return result
        template=bind(template)
        scaled=lambda value:format(Decimal(value)/Decimal('1000000'),'f')
        for row in template['objects']:
            value=row['value']
            if row['ref']['kind']=='FundingSource':
                value['actual_cash']['value']['value']=scaled(owner_funding.actual_cash)
                value['restricted_cash']['value']['value']=scaled(owner_funding.restricted_cash)
            if row['ref']['kind']=='Obligation':
                value['actual_due']['value']['value']=scaled(owner_funding.old_due)
                value['actual_paid']['value']['value']=scaled(owner_funding.actual_paid)
    # Independent authorization ceiling, declared before any opportunity is
    # generated. Forecast cash uses stay at 30 template HKD; the ceiling is
    # neither current cash nor a promised drawdown of the native budget.
    investment,=[r['value'] for r in template['objects'] if r['ref']['kind']=='InvestmentPlan'
        and r['ref']['id']=='build-investment']
    investment['expenditure_cap']['value']['value']='680'
    regions=['Guangzhou','Shenzhen','Hong Kong','Macau','Zhuhai','Foshan','Dongguan','Huizhou','Zhongshan','Jiangmen','Zhaoqing']
    # Explicit scenario use-code mapping, not an inferred native rule.
    policy=OwnerOpportunityPolicy.model_validate({'organization_id':'finance-owner-a','cost_organization_id':'finance-qs',
        'schedule_organization_id':'finance-architect','allow_scoped_template_authorizations':True,
        'allowed_regions':regions,'initiation_region_ids':initiation_region_ids,
        'project_use_codes':{'building':'housing','infrastructure':'transport',
            'industrial':'industrial_use','public_facility':'community_service','digital_smart':'digital_use'},
        'money_scale':'1000000','max_prior_initiations':max_prior_initiations,
        'initial_investment_policy':initial_investment_policy,
        'max_prior_payment_requests':max_prior_payment_requests,
        'max_prior_final_accounts':max_prior_final_accounts,
        'with_observation':with_observation,'observation_minimum_demand':observation_minimum_demand,
        'with_proposal':with_proposal,'proposal_review_cost':proposal_review_cost,'proposal_review_effort':proposal_review_effort,
        'observation_management_requirement':'1','max_prior_declines':max_prior_declines,
        'study_question_code':study_question_code,'study_budget':study_budget,'study_estimated_cost':study_estimated_cost,
        'study_target_interventions':list(study_target_interventions),
        'study_resource_requirement':study_resource_requirement,'study_duration':study_duration,'study_qualified':study_qualified,
        'study_service_offer':study_service_offer,
        'study_professional_intake':study_professional_intake,
        'native_budget_currency':'HKD','utility':'0.7','probability':'1'})
    source=_write(directory,'owner-opportunity-input.json',{'schema_version':'owner-opportunity-input.v1',
        'run_id':run_id,'template':template,'policies':[policy.model_dump(mode='json',exclude=
            ({'study_service_offer'} if study_service_offer is None else set())
            | ({'study_professional_intake'} if study_professional_intake is None else set()))]})
    organizations=[]
    for agent in request['agents']:
        org=agent['agent_id'];basis=ref('Evidence',org+'-opportunity-mandate')
        organizations.append({'organization_id':org,'actor_id':actors[org],'source_ids':['synthetic:'+org],
            'public_description':'Explicit synthetic initial organization and scoped assessment mandate; no real rights or project registration.',
            'public_location':known(agent['region']),'members':[],'evidence_refs':[basis],
            'assignments':[{'role':agent['role'],'function_ref':ref('FunctionAssignment',org+'-opportunity-function'),
                'configuration_version':'1','basis_refs':[basis]}]})
    settings=OwnerOpportunitySettings.model_validate({'version':'1','policy_version':'explicit-owner-opportunity-v1',**source,
        'allow_saved_recovery':allow_saved_recovery,
        'authority':{'runtime_id':run_id,'version':'1','organization_snapshot':{'schema_version':'organization.v2',
            'run_id':run_id,'organizations':organizations,'authorizations':[]}}})
    routes=read('native-host.json');r=routes['settings'];r['micro_owner_opportunity_scope']=True
    r['query_saved_opportunity_on_error']=query_saved_opportunity_on_error
    r['native_proposals']=[v for v in r['native_proposals'] if (v['role'],v['operation'])!=('Owner','evaluate_project_opportunity')]
    r['native_decisions']=[v for v in r['native_decisions'] if (v['role'],v['decision_type']) not in
        {('Owner','owner_project_opportunity'),('Owner','owner_project_initiation')}]
    # The first created project may reach native professional appointments.
    # Explicitly retain those original decisions outside this micro window.
    r['native_professional_intake_scope']=True
    r['native_proposals'] += [{'role':role,'operation':'consider_appointment'} for role in ('Architect','Engineer','QS')]
    r['native_proposals'].append({'role':'Owner','operation':'select_appointment'})
    r['native_decisions'] += [{'role':role,'decision_type':role.lower()+'_appointment_acceptance'} for role in ('Architect','Engineer','QS')]
    r['native_decisions'] += [{'role':'Owner','decision_type':'owner_select_'+role} for role in ('architect','engineer','qs')]
    _write(directory,'macro-request.json',request);_write(directory,'native-host.json',routes)
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':settings.model_dump(mode='json')})
    _write(directory,'source-provenance.json',{'origin':'synthetic','template_path':str(template_path),
        **({'initial_organization_actor_ids':organization_actor_ids} if organization_actor_ids is not None else {}),
        'initial_owner_funding':None if owner_funding is None else owner_funding.model_dump(mode='json'),
        'initial_project_ids':[p['project_id'] for p in request['initial_projects']],
        'max_prior_payment_requests':max_prior_payment_requests,
        'max_prior_final_accounts':max_prior_final_accounts,
        'with_observation':with_observation,'observation_minimum_demand':observation_minimum_demand,
        'with_proposal':with_proposal,'proposal_review_cost':proposal_review_cost,
        'proposal_review_effort':proposal_review_effort,
        'max_prior_declines':max_prior_declines,'random_seed':request['random_seed'],
        'allow_saved_recovery':allow_saved_recovery,'query_saved_opportunity_on_error':query_saved_opportunity_on_error,
        'initial_investment_policy':initial_investment_policy,
        'study_question_code':study_question_code,'study_budget':study_budget,'study_estimated_cost':study_estimated_cost,
        'study_target_interventions':list(study_target_interventions),
        'study_resource_requirement':study_resource_requirement,'study_duration':study_duration,'study_qualified':study_qualified,
        **({'study_service_offer':study_service_offer.model_dump(mode='json')} if study_service_offer is not None else {}),
        **({'study_professional_intake':study_professional_intake.model_dump(mode='json')} if study_professional_intake is not None else {}),
        'template_sha256':hashlib.sha256(template_path.read_bytes()).hexdigest(),
        'limits':['Independent forecasts, qualifications, rights, registration conditions, cash, restriction, prior debt and management load are explicit assumptions.',
            'No macro current financial-capacity scalar is converted into cash or professional analysis.',
            'Template amounts alone are scaled by the declared 1000000 factor; native opportunity budget is interpreted as HKD by this explicit development scenario.',
            'The initial build-investment authorization ceiling is explicitly 680000000 HKD; the independent 30000000 HKD forecast must fit the native budget, which must fit this ceiling. A native budget is not cash or an executed expenditure.',
            'An actual request creates only private assessment/view/grant identities under the explicit scoped mandate; only the original native core creates projects.',
            'Own project-creation and optional progress-payment request counts affect only explicitly configured private initiation preferences.',
            'The optional existing construction project, contract, engagement, progress and HKD unit are synthetic initial assumptions, not current micro tender, signing, work or payment proof.',
            'Only actual strictly earlier native payment requests are consumed; a delayed event is correlated once to its request, not counted as another payment. Approved does not prove cash execution, received payment or debt clearance.']})
    _write_launch_files(directory,assembly_hook='integration.owner_opportunity_native:configure_assembly',
        allow_native_project_generation=True,allow_native_initial_projects_with_generation=with_payment_project,
        readme_override='''# 原 OWN-A03 与真实原生项目机会

运行 `& './run.ps1'`。显式启用原生机会生成器，由原宏观生成当前机会；不会预先生成未来项目或机会资料。
只有实际请求到来，适配层才把完整机会内容绑定到独立合成的业主比较案例和预先声明的作用域授权模板。
原 OWN-A03 实算方案比较、现金日历和管理容量；`invest` 经同一原生提案/最终确认交宏观创建项目。
原投资 `reject` 或仅授权准备不会伪装成已立项。缺资料、技术失败、未知及不支持结果停止复核。
--initial-investment-policy <evaluate|prepare_only|reject> 可显式声明初始私有策略，默认保留原模板；prepare_only 仍由原 A03 实算现金日历、容量、权限和比较后选择有界准备方案，宏观返回暂不立项。后轮历史保留原准备计划、范围、条件和拟议投入，不将其当作已执行支出、资源占用或已完成工作。--max-prior-declines 计原生暂不立项事件，原微观 prepare/reject/study 语义分别保留。
原始专业分析、资格、权利和登记条件、资金及限制、原有债务和管理负荷均为明确合成假设；默认不执行 OWN-A02/A16 或专业分析生产。默认不执行 A01。
可选 --with-proposal（须同时启用 --with-observation）执行原 OWN-A16：候选草案、已有权利和规模方法支持域为独立合成初始声明，原处理器按实际全局需求指数、同源私有现金/旧债保护及原管理负荷实算规模和有限候选选择，实际草案替换原 A03 需求草案输入；非建设比较基线必须保留。--proposal-review-cost / --proposal-review-effort 只声明每个候选的预计审阅费用和工作量，不登记支出或资源预留。原 no_proposal 直接返回不立即立项，不执行 A03；只形成部分草案时保留结果并等待完整比较资料，不以原始模板补造未选草案。没有执行有限研究授权、专业调查、报告、外部委任、权利取得或详细设计。
可选 --with-observation 显式授权原 OWN-A01 在同一机会请求内先行观察：读取原宏观当前全局需求指数、候选地区和用途，以及独立声明的管理池与筛选工作量。--observation-minimum-demand 声明私有筛选阈值，默认 0；实际 follow 结果及其来源、审计摘要作为原 A03 的私有 Evidence，原 ignore 则直接返回原宏观 defer_project，不执行 A03。全局指数不是地区调查或专业预测；跟踪候选不创建正式项目、案件、权利或资源承诺。其他结果、资料不足或技术失败保留原结果并停止复核。
--max-prior-declines N 可声明累计 N 项本业主真实原生不立项事件后暂缓新增投资的私有偏好，默认关闭。多个私有候选拒绝只按原宏观实际发出的事件计数；后续原 A01/A03 读取原事件、原 deciding action、提案/最终确认及来源，不将拒绝当成创建、支出或仍未完成的义务。--random-seed 仅配置原引擎的初始种子。
建设投资预先声明的支出授权上限为 680000000 HKD，独立预测现金用途仍为 30000000 HKD；原生项目预算必须介于预测总成本与该授权上限之间。预算不等于实际成本、现金或放款。
保留非建设比较基线和原有义务；公共资金来源身份和物理管理池身份在多个机会之间保持稳定，案例授权视图使用独立版本。
实际创建事件只反馈本业主；下一时点核对原 A03 来源/审计、机会、提案、最终确认和原生项目后，显式新业务偏好可使后续原 A03 拒绝。
该历史不推断新支出、放款、实际到账或资源预留。融资、专业委任及月度经营继续显式采用原宏观实现，不计入本窗口微观覆盖。
可选 --max-prior-payment-requests N 声明累计收到 N 项原生进度款请求后暂缓新增投资的私有偏好，默认关闭；不是未付款、缺钱或债务的推定。历史有权查询绑定原生运行、主体、项目日志、原事件及严格较早时点，不冒充外部送达。
可选 --max-prior-final-accounts N 声明观察到 N 项本业主真实原生汇总结算后暂缓新增投资、等待私有组合复核的偏好，默认关闭；仅消费当前运行中严格较早的实际事件，不生成结算结果或初始完工项目，不将结算金额计入可用现金。缺陷、未清债务和移交状况保持未证明，偏好本身不执行复核或清债。
--with-payment-project 提供明确的既有施工项目并开启宏观已有的混合初始化；须同时声明上述偏好。初始合同、承包商占用和进度不是本轮微观履约证据。可将 --max-prior-initiations 设为 999，在这个两时点场景中单独观察付款请求反馈；默认立项次数偏好仍为 1。
宏观源码保持冻结；不使用旧采购生命周期或第二套正式业务账本，不调用真实模型。
可选 --study-question-code <问题代码> 声明尚未解决的初始比较问题。原 A03 实际形成 study_more 后，原 A02 用同源现金、未付义务保护和管理承诺评估有限内部研究授权；--study-budget / --study-estimated-cost / --study-resource-requirement / --study-duration 声明独立合成预算、预计成本、拟用资源和计划时长，--study-unqualified 明确关闭内部研究资格。原 internal_study 仅是拟议任务和有界授权，原 stop 仅是不授权；二者均保留未解决问题并返回暂不立项，不产生研究报告、正式任务、支出、资源占用或外部委任。真实不立项事件及其关联的私有授权可供后续原动作读取；资料不足、技术失败或其他未接结果仍停止复核。
可选 --allow-saved-recovery 允许查询同一当前请求已保存的原动作结果；再启用 --query-saved-opportunity-on-error，可在原宏观调用仍等待时核验并补齐技术收尾。所需原 A01/A16/A03/A02 结果必须全部已经保存，来源、授权、版本及原请求必须仍一致；缺结果保留原异常，不执行尚未开始的动作、不重新调用模型、不重启引擎或新建业务请求。两个开关默认关闭，不提供跨进程重启恢复。
--study-target-intervention <new_build|alter|extend|non_build> 可重复指定，须同时声明研究问题。未指定时保留整个比较案例；指定后只引用原比较内相应方案及其原有工作范围，原 A03 逐项校验后才交原 A02，后轮反馈保留方案与范围。某类方案或对应工作不存在时停止，不退回整体研究，不增加比较候选、正式任务或已完成研究。
--study-service-offer JSON 文件可声明期初独立专业研究报价，须同时声明研究问题。文件按 OwnerStudyServiceOfferPolicy 校验；source_declaration 必须为 independent_initial_standing_offer，提供者须为原 QS 或 Architect，币种 HKD，费用、资格、研究许可和支持问题保留各自已知/未知状态。原 OWN-A02 据此独立决定 commission 或 stop；未知资料仍等待。报价为明确合成假设，不是原专业 A02 已执行或收件回执；研究委托决定仍是私有授权，不创建正式委任、支出或报告。
--study-professional-intake JSON 与期初报价模式互斥，须同时声明研究问题。输入按 OwnerStudyProfessionalIntakePolicy 校验并明确独立初始资质、费用/最低收费、风险、工作量换算、各地区物理资源、原固定时窗承诺及 QS 冲突类别。原专业 A02 实际处理当前原 A03 问题，再将接受/拒绝和原条款经有权技术交接送给业主 A02；后轮读取双方原结果并重核当前授权。该交接不计外部宏观消息回执、正式委任、报告、资源预留或支出。
''')
    return {'status':'synthetic_owner_opportunity_bundle_unverified','directory':str(directory),'policies':1}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--max-prior-initiations',type=int,default=1)
    parser.add_argument('--max-prior-payment-requests',type=int)
    parser.add_argument('--max-prior-final-accounts',type=int)
    parser.add_argument('--with-payment-project',action='store_true')
    parser.add_argument('--with-observation',action='store_true')
    parser.add_argument('--with-proposal',action='store_true')
    parser.add_argument('--initial-investment-policy',choices=['evaluate','prepare_only','reject'])
    parser.add_argument('--proposal-review-cost',default='1000000')
    parser.add_argument('--proposal-review-effort',default='0.5')
    parser.add_argument('--observation-minimum-demand',default='0')
    parser.add_argument('--study-question-code')
    parser.add_argument('--study-target-intervention',action='append',default=[],
        choices=['new_build','alter','extend','non_build'])
    parser.add_argument('--study-budget',default='1000000')
    parser.add_argument('--study-estimated-cost',default='500000')
    parser.add_argument('--study-resource-requirement',default='0.5')
    parser.add_argument('--study-duration',type=int,default=1)
    parser.add_argument('--study-unqualified',action='store_true')
    parser.add_argument('--study-service-offer',type=Path,help='Independent initial standing offer JSON; requires --study-question-code')
    parser.add_argument('--study-professional-intake',type=Path,help='Independent professional inputs JSON; execute original A02 before Owner study authorization')
    parser.add_argument('--allow-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-opportunity-on-error',action='store_true')
    parser.add_argument('--max-prior-declines',type=int)
    parser.add_argument('--random-seed',type=int)
    parser.add_argument('--organization-actor-ids',type=Path,
        help='Initial JSON mapping for the original Owner/QS/Architect actors; legal party IDs stay unchanged')
    args=parser.parse_args(argv)
    print(json.dumps(build_bundle(args.output,run_id=args.run_id,max_prior_initiations=args.max_prior_initiations,
        max_prior_payment_requests=args.max_prior_payment_requests,with_payment_project=args.with_payment_project,
        max_prior_final_accounts=args.max_prior_final_accounts,
        with_observation=args.with_observation,observation_minimum_demand=args.observation_minimum_demand,
        max_prior_declines=args.max_prior_declines,random_seed=args.random_seed,
        with_proposal=args.with_proposal,proposal_review_cost=args.proposal_review_cost,
        initial_investment_policy=args.initial_investment_policy,
        proposal_review_effort=args.proposal_review_effort,study_question_code=args.study_question_code,
        study_target_interventions=args.study_target_intervention,
        study_budget=args.study_budget,study_estimated_cost=args.study_estimated_cost,
        study_resource_requirement=args.study_resource_requirement,study_duration=args.study_duration,
        study_qualified=not args.study_unqualified,allow_saved_recovery=args.allow_saved_recovery,
        study_service_offer=json.loads(args.study_service_offer.read_text(encoding='utf-8-sig')) if args.study_service_offer else None,
        study_professional_intake=json.loads(args.study_professional_intake.read_text(encoding='utf-8-sig')) if args.study_professional_intake else None,
        query_saved_opportunity_on_error=args.query_saved_opportunity_on_error,
        organization_actor_ids=json.loads(args.organization_actor_ids.read_text(encoding='utf-8-sig'))
            if args.organization_actor_ids else None)))


if __name__=='__main__':main()
