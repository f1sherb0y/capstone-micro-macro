"""Independent synthetic A04 sources; no stored future micro/native outcomes."""
from copy import deepcopy
from decimal import Decimal
import argparse
import json
from pathlib import Path

from integration.bootstrap import enable_gba_imports
from integration.contractor_tender_development import _write, _write_launch_files, known, ref
from integration.supplier_order_actions import SupplierOrderActionAssembler
from integration.supplier_order_native import SupplierOrderNativePlan, SupplierOrderNativeSettings
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_order_objects import order_agreement_digest
from src.coordination.tasks import task_digest


def _initial_actor_sources(value, actors):
    """Bind newly authored initial actor fields, preserving legal organization IDs.

    Never apply this to a registered source, saved invocation or signature.
    References, business parties and native agent identities remain unchanged.
    """
    if isinstance(value,list):return [_initial_actor_sources(v,actors) for v in value]
    if not isinstance(value,dict):return deepcopy(value)
    result={key:(actors.get(item,item) if isinstance(item,str) and (key=='actor_id' or key.endswith('_actor_id'))
        else _initial_actor_sources(item,actors)) for key,item in value.items()}
    if 'recipient_organization_id' in value and 'recipient_id' in value:
        org=value['recipient_organization_id']
        if org not in actors or value['recipient_id']!=org:
            raise ValueError('Initial inquiry must retain its explicitly declared original recipient before actor binding')
        result['recipient_id']=actors[org]
    return result


def build_bundle(directory,*,run_id,with_quote=False,with_product=False,with_screening=False,with_contractor=False,
        owner_id='supply-owner',contractor_id='supply-contractor',supplier_ids=('supply-a','supply-b'),
        clock_id=None,owner_function_id=None,additional_project_windows=(),first_decline_stage=None,
        allow_saved_recovery=False,query_saved_supply_on_error=False,with_product_substitution=False,
        contractor_substitution_permitted=True,continue_unstarted_actions_on_error=False,
        organization_actor_ids=None,decline_after_prior_declines=None,source_namespace=None,decline_all_quotes=False):
    if type(decline_all_quotes) is not bool or (decline_all_quotes and (not with_quote or with_contractor)):
        raise ValueError('All-quote refusal requires explicit quote sources and original native selection')
    if source_namespace is not None and (not isinstance(source_namespace,str) or not source_namespace.strip()):
        raise ValueError('Initial supply source namespace must be a nonempty string')
    namespace='' if source_namespace is None else '-'+source_namespace
    if decline_after_prior_declines is not None and (
            type(decline_after_prior_declines) is not int or decline_after_prior_declines < 1 or not with_screening):
        raise ValueError('Supplier decline feedback requires original screening and a positive integer threshold')
    if with_product_substitution and not with_product:
        raise ValueError('Alternate catalog product requires original product preparation')
    if not contractor_substitution_permitted and (not with_product_substitution or not with_contractor):
        raise ValueError('Withheld substitution permission requires the alternate-product micro Contractor scene')
    if query_saved_supply_on_error and not allow_saved_recovery:
        raise ValueError('Supply query requires --allow-saved-recovery')
    if with_product and not with_quote:raise ValueError('Product preparation requires explicit with_quote composition')
    if with_screening and not with_product:raise ValueError('Screening preparation requires explicit with_product composition')
    if with_contractor and not with_quote:raise ValueError('Micro Contractor procurement requires explicit with_quote composition')
    if first_decline_stage is not None:
        if first_decline_stage not in {'screening','product','quote'}:
            raise ValueError('Supply decline source must select screening, product or quote')
        if not {'screening':with_screening,'product':with_product,'quote':with_quote}[first_decline_stage]:
            raise ValueError('Supply decline source requires its explicitly enabled original stage')
    parties=[owner_id,contractor_id,*supplier_ids]
    if (len(supplier_ids)!=2 or any(not isinstance(v,str) or not v for v in parties)
            or len(set(parties))!=len(parties)):
        raise ValueError('Supply input needs distinct explicit Owner, Contractor and two Suppliers')
    actors={org:org for org in parties}
    if organization_actor_ids is not None:
        if (not isinstance(organization_actor_ids,dict) or not set(organization_actor_ids)<=set(parties)
                or any(type(actor) is not str or not actor.strip() for actor in organization_actor_ids.values())):
            raise ValueError('Initial organization actor mapping requires known organizations and nonempty actor IDs')
        actors.update(organization_actor_ids)
        if len(set(actors.values()))!=len(actors):
            raise ValueError('Initial organization actors must remain distinct across the original organizations')
    cases=[{'project_id':project,'tick':tick,'delivery_start':3,'delivery_end':4,
        'business_money_scale':'1','procurement_limit':'1000','require_native_award':False}
        for project in ('supply-first','supply-followup') for tick in (1,2)]
    for original in additional_project_windows:
        if (set(original)!={'project_id','tick','delivery_start','delivery_end','business_money_scale','procurement_limit','require_native_award'}
                or not isinstance(original['project_id'],str) or not original['project_id']
                or any(type(original[k]) is not int for k in ('tick','delivery_start','delivery_end'))
                or not 1<=original['tick']<=original['delivery_start']<original['delivery_end']<99
                or original['require_native_award'] is not True):
            raise ValueError('Additional supply window needs explicit timing, commercial assumptions and actual native award')
        scale,limit=Decimal(original['business_money_scale']),Decimal(original['procurement_limit'])
        if not scale.is_finite() or scale<=0 or not limit.is_finite() or limit<=0:
            raise ValueError('Supply commercial scale and independent procurement limit must be finite and positive')
        cases.append(deepcopy(original))
    if len({(r['project_id'],r['tick']) for r in cases})!=len(cases):
        raise ValueError('Supply source windows repeat an original project/time selector')
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    roles={owner_id:'Owner',contractor_id:'Contractor',supplier_ids[0]:'Supplier',supplier_ids[1]:'Supplier'}
    projects=list(dict.fromkeys(r['project_id'] for r in cases));clock=ref('ClockProfile',clock_id or run_id+'-monthly-clock')
    point=lambda n:{'clock_ref':clock,'offset':n}
    window={'start':point(0),'end':point(99),'bounds':'closed_open'}
    common=ref('Evidence',run_id+'-initial-identities'+namespace)
    common_value={'ref':common,'source_kind':'synthetic','basis_kind':'assumed','locator':'explicit-supply-development-identities',
        'content_hash':task_digest({'roles':roles,'projects':projects,'region':'Hong Kong','source_windows':cases}),'effective_window':window}
    organizations=[];grants=[];plans=[]
    for org,role in roles.items():
        organizations.append({'organization_id':org,'actor_id':org,'source_ids':['synthetic:'+org],
            'public_description':'Explicit synthetic supply sources; no detailed formal order, stock reservation or cash.',
            'public_location':known('Hong Kong'),'members':[],'evidence_refs':[common],
            'assignments':[{'role':role,'function_ref':ref('FunctionAssignment',
                owner_function_id if role=='Owner' and owner_function_id else org+'-function'+namespace),
                'configuration_version':'1','basis_refs':[common]}]})
    for org in supplier_ids:
        for project in projects:
            for case in [r for r in cases if r['project_id']==project]:
                tick=case['tick'];scale=Decimal(case['business_money_scale'])
                schedule={'start':point(case['delivery_start']),'end':point(case['delivery_end']),'bounds':'closed_open'}
                tag=f'{org}-{project}-t{tick}'+namespace;rr=lambda kind,name:ref(kind,tag+'-'+name)
                scope={'kind':'project','ref':ref('Project',project),'coverage_refs':[]}
                basis=rr('Evidence','explicit-input');native=rr('Evidence','actual-native-request')
                objects=[{'ref':common,'value':deepcopy(common_value)}]
                objects.append({'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed',
                    'locator':'explicit-independent-supply-order-sources','content_hash':task_digest({'tag':tag,
                        'initial_stock_panels':10,'committed_stock_panels':0,'pool_capacity':10,'cash_HKD':1000,
                        'commercial_input':case,'signed_independent_buyer_terms':True,
                        'all_amounts_and_rates_assumed':True}),'effective_window':window}})
                objects.append({'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
                    'locator':'actual-native-supply-request-and-own-earlier-selections','content_hash':None,'effective_window':window}})
                def add(reference,**value):objects.append({'ref':reference,'value':{'ref':reference,'evidence_refs':[basis],**value}})
                measured=lambda n,unit:{'value':str(n),'unit':unit,'basis_ref':basis}
                money=lambda n:{'value':format(Decimal(str(n)).normalize(),'f'),'currency':'HKD','basis_ref':basis}
                add(scope['ref'],evidence_refs=[common])
                product=rr('ProductSpecification','panel');offer=rr('SupplyOffer','offer');proposal=rr('OrderProposal','proposal')
                terms=rr('SupplyTerms','terms');requirement=rr('Requirement','technical')
                origin=rr('Location','factory');destination=rr('Location','site');service=rr('DeliveryService','factory-supply')
                pool=rr('ResourcePool','delivery');delivery_window=rr('TimeWindow','delivery');validity=rr('TimeWindow','offer-validity')
                objects.extend([{'ref':delivery_window,'value':deepcopy(schedule)},{'ref':validity,'value':deepcopy(window)}])
                add(product,supplier_organization_id=org,product_code=known('synthetic-panel'),factory_id=known(org+'-factory'),
                    use_codes=known(['synthetic-envelope']),quantity_unit='panel',effective_window=window,properties=known([]),
                    product_evidence_refs=[],deviation_refs=[])
                add(origin,region_id='Hong Kong',factory_id=org+'-factory');add(destination,region_id='Hong Kong',factory_id=None)
                add(service,service_code='factory_supply',provider_organization_id=org,destination_ref=destination,effective_window=window)
                add(pool,organization_id=org,region_id='Hong Kong')
                delivery={'product':{'product_ref':product,'destination_scope_ref':scope,'quantity':measured(2,'panel'),
                    'requirement_refs':[requirement],'deviation_refs':[]},'delivery_window_ref':delivery_window,
                    'destination_ref':destination,'included_service_refs':[service],'price':money(Decimal(200)*scale)}
                add(offer,supplier_organization_id=org,buyer_id=contractor_id,payer_id=contractor_id,scope=scope,
                    status='active',available_at=point(0),validity_ref=validity,terms_ref=terms,condition_refs=[],
                    lines=[{'local_key':'batch-1','delivery':delivery}])
                add(proposal,offer_ref=offer,supplier_organization_id=org,recipient_actor_id=org,buyer_id=contractor_id,
                    payer_id=contractor_id,scope=scope,status='active',received_at=point(0),response_window=window,
                    terms_ref=terms,condition_refs=[],lines=[{'local_key':'line-1','offer_line_key':'batch-1','delivery':delivery}])
                proposed=deepcopy(objects[-1]['value'])
                add(terms,offer_ref=offer,order_proposal_ref=proposal,supplier_organization_id=org,buyer_id=contractor_id,
                    payer_id=contractor_id,currency='HKD',effective_window=window,payment_rules=[{'milestone_code':'delivery','fraction':'1'}])
                add(requirement,offer_ref=offer,order_proposal_ref=proposal,scope=scope,condition_code='explicit-panel-requirement',
                    satisfied=known(True),available_at=point(0),effective_window=window)
                inventory=rr('InventorySnapshot','stock');capacity=rr('SupplierCapacity','capacity');funding=rr('FundingPosition','cash')
                add(inventory,organization_id=org,as_of=point(tick),coverage='complete',lots=[{'batch_ref':rr('ProductBatch','actual-stock'),
                    'product_ref':product,'location_ref':origin,'status':'usable','actual':measured(10,'panel'),'committed':measured(0,'panel')}])
                add(capacity,organization_id=org,as_of=point(tick),resource_coverage='complete',commitment_coverage='complete',
                    resources=[{'resource_ref':pool,'region_id':'Hong Kong','total':known(measured(10,'delivery-unit')),'effective_window':window}],
                    commitments=[])
                add(funding,organization_id=org,as_of=point(tick),coverage='complete',actual_cash=known(money(1000)),committed_cash=known(money(0)))
                plan_ref=rr('SupplyCommitmentPlan','full')
                add(plan_ref,organization_id=org,offer_ref=offer,order_proposal_ref=proposal,purpose='full_order',available_at=point(0),
                    effective_window=window,lines=[{'order_line_key':'line-1','delivery':delivery,'source_location_ref':origin,
                        'stock_uses':[{'batch_ref':rr('ProductBatch','actual-stock'),'quantity':measured(2,'panel')}],
                        'resource_uses':[{'resource_ref':pool,'window_ref':delivery_window,'rate_per_product_unit':measured(1,'delivery-unit'),
                            'source':'delivery'}],'working_capital':known(money(Decimal(100)*scale))}])
                profile=rr('SupplyFormationProfile','formation')
                add(profile,organization_id=org,offer_ref=offer,order_proposal_ref=proposal,effective_window=window,
                    algorithm_code='sourced_order_commitment_v1',policy='evaluate',on_conflict='reject',currency=known('HKD'),
                    required_counterparty_ids=known([contractor_id]),counterpart_action_ids=['CONTRACTOR-A05'],allowed_terms_refs=[terms],
                    full_plan_ref=plan_ref,partial_plans=[],revision_requirement_refs=[],permitted_quote_changes=[],reviewed_agreement_sha256=None,
                    commercial_rules=[{'order_line_key':'line-1','offer_line_key':'batch-1','scope':scope,'allowed_product_refs':[product],
                        'maximum_quantity':measured(2,'panel'),'minimum_unit_price':money(Decimal(90)*scale),'minimum_batch_price':money(Decimal(100)*scale),
                        'allowed_window_ref':delivery_window,'allowed_destination_refs':[destination],'required_service_refs':[service],
                        'prerequisite_refs':[],'allowed_fulfillment_modes':['stock']}],evidence_refs=[basis,native])
                assignment=next(o['assignments'][0] for o in organizations if o['organization_id']==contractor_id)
                buyer_function=deepcopy(assignment['function_ref']);buyer_grant=rr('Authorization','independent-buyer')
                objects.append({'ref':buyer_function,'value':deepcopy(assignment)})
                buyer_auth={'ref':buyer_grant,'organization_id':contractor_id,'actor_id':contractor_id,'function_ref':buyer_function,
                    'action_ids':['CONTRACTOR-A05'],'scopes':[scope],'readable_refs':[offer,proposal,terms],'tool_ids':[],
                    'basis_refs':[common],'validity':window}
                objects.append({'ref':buyer_grant,'value':buyer_auth});grants.append(deepcopy(buyer_auth))
                acceptance=rr('PartyAcceptance','initial-independent-buyer')
                add(acceptance,run_id=run_id,proposal_ref=proposal,offer_ref=offer,terms_ref=terms,scope=scope,party_id=contractor_id,
                    author_actor_id=contractor_id,author_function_ref=buyer_function,authorization_ref=buyer_grant,action_id='CONTRACTOR-A05',
                    agreement_sha256=order_agreement_digest(proposed),choice='accept',status='active',created_at=point(0),validity=window)
                own_assignment=next(o['assignments'][0] for o in organizations if o['organization_id']==org)
                function=deepcopy(own_assignment['function_ref'])
                objects.append({'ref':function,'value':deepcopy(own_assignment)})
                authority=rr('Authorization','supplier')
                grant={'ref':authority,'organization_id':org,'actor_id':org,'function_ref':function,'action_ids':['SUPPLIER-A04'],
                    'scopes':[scope],'readable_refs':[],'tool_ids':[],'basis_refs':[common],'validity':window}
                objects.append({'ref':authority,'value':grant});candidate=rr('CandidateSet','offer')
                objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':point(tick),
                    'candidates':[{'ref':offer,'permitted_choices':['accept','reject']}],'search_profile_ref':rr('Profile','explicit-offer')}})
                visible=[r['ref'] for r in objects];grant['readable_refs']=visible;grants.append(deepcopy(grant))
                context={'run_id':run_id,'actor_id':org,'function_ref':function,'authorization_refs':[authority],'operation_id':tag,
                    'contract_ref':ref('ActionContract','SUPPLIER-A04'),'task_ref':rr('DecisionTask','order'),'scope':scope,
                    'business_time':point(tick),'read_token':tag+'-read','visible_refs':visible,'candidate_set_ref':candidate,'execution_mode':'rule'}
                inputs={'order_proposal_ref':proposal,'offer_ref':offer,'counterpart_acceptance_refs':[acceptance],
                    'inventory_ref':inventory,'capacity_ref':capacity,'funding_ref':funding,'formation_profile_ref':profile}
                plan=SupplierOrderNativePlan.model_validate({'organization_id':org,'project_id':project,'tick':tick,
                    'context':context,'action_input':inputs,'objects':objects,'native_evidence_ref':native,
                    'utility':{'value':'0.8' if org==supplier_ids[0] else '0.6','unit':'score','basis_ref':basis},
                    'probability':{'value':'1','unit':'probability','basis_ref':basis},'max_prior_selections':1 if org==supplier_ids[0] else None,
                    'require_native_award':case['require_native_award']})
                for row in plan.objects:
                    value=deepcopy(row['value'])
                    if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
                    SupplierOrderActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
                plans.append(plan.model_dump(mode='json'))
    if with_quote:
        from integration.supplier_order_native_quote_development import extend_quote_plan
        scales={(r['project_id'],r['tick']):Decimal(r['business_money_scale']) for r in cases}
        plans=[SupplierOrderNativePlan.model_validate(extend_quote_plan(p,grants=grants,
            factory_unit_cost=format(Decimal(80)*scales[(p['project_id'],p['tick'])],'f'))).model_dump(mode='json') for p in plans]
    if with_product:
        from integration.supplier_order_native_product_development import extend_product_plan
        plans=[SupplierOrderNativePlan.model_validate(extend_product_plan(p,grants=grants)).model_dump(mode='json') for p in plans]
    if with_product_substitution:
        from integration.supplier_order_native_substitution_development import extend_substitution_plan
        plans=[SupplierOrderNativePlan.model_validate(extend_substitution_plan(p,grants=grants)).model_dump(mode='json') for p in plans]
    if with_screening:
        from integration.supplier_order_native_screening_development import extend_screening_plan
        plans=[SupplierOrderNativePlan.model_validate(extend_screening_plan(p,grants=grants)).model_dump(mode='json') for p in plans]
        for plan in plans:plan['decline_after_prior_declines']=decline_after_prior_declines
    contractor=None;cplans=None
    if with_contractor:
        from integration.contractor_supply_native_development import contractor_plans
        # Supplier willingness and Contractor preferences are separate. The
        # original selector only chooses among currently accepted actual quotes.
        for plan in plans:plan['max_prior_selections']=None
        cplans=contractor_plans(plans,organizations=organizations,grants=grants,
            procurement_limits={(r['project_id'],r['tick']):r['procurement_limit'] for r in cases},
            substitution_permitted=contractor_substitution_permitted)
    if first_decline_stage is not None:
        first,=[p for p in plans if p['organization_id']==supplier_ids[0] and p['project_id']=='supply-first' and p['tick']==1]
        quote=first['quote'];product=quote['product']
        step={'quote':quote,'product':product,'screening':product['screening'] if product else None}[first_decline_stage]
        # Independent current business inputs, not injected decisions/results.
        if first_decline_stage=='product':
            requirement,=[r['value'] for r in step['objects'] if r['ref']==step['action_input']['requirement_refs'][0]]
            requirement['allowed_factory_ids']=known(['different-explicit-factory'])
        else:
            field='screening_profile_ref' if first_decline_stage=='screening' else 'pricing_profile_ref'
            profile,=[r['value'] for r in step['objects'] if r['ref']==step['action_input'][field]]
            profile['policy']='decline_new_work' if first_decline_stage=='screening' else 'decline_new_quotes'
    if decline_all_quotes:
        for plan in plans:
            step=plan['quote']
            profile,=[r['value'] for r in step['objects'] if r['ref']==step['action_input']['pricing_profile_ref']]
            profile['policy']='decline_new_quotes'
        _write(directory,'initial-all-quote-policy.json',{'policy':'decline_new_quotes',
            'boundary':'Independent authorized initial business policy for all declared quote profiles. Original processors decide; no result, offer acceptance or native state is prefilled.'})
    if organization_actor_ids is not None:
        plans=_initial_actor_sources(plans,actors)
        organizations=_initial_actor_sources(organizations,actors)
        grants=_initial_actor_sources(grants,actors)
        if cplans is not None:cplans=_initial_actor_sources(cplans,actors)
        _write(directory,'initial-organization-actors.json',{'organization_actor_ids':actors,
            'boundary':'Explicit initial identity configuration before source sealing. Native agent IDs and legal parties are organizations; actor ownership is checked by the original authorization registry. Not a runtime identity migration.'})
    if cplans is not None:
        contractor={'version':'1',**_write(directory,'contractor-supply-input.json',{
            'schema_version':'contractor-supply-input.v1','run_id':run_id,'plans':cplans})}
    source=_write(directory,'supplier-order-input.json',{'schema_version':'supplier-order-native-input.v1','run_id':run_id,'plans':plans})
    if additional_project_windows:
        _write(directory,'initial-supply-windows.json',{'currency':'HKD','source_windows':cases,
            'boundary':'Independent initial commercial views and future source availability. Additional windows require an actual earlier native award; they create no project, contract, order, inventory reservation or payment.'})
    settings=SupplierOrderNativeSettings.model_validate({'version':'1','policy_version':'explicit-supply-order-v1',**source,'contractor':contractor,
        'allow_saved_recovery':allow_saved_recovery,
        'continue_unstarted_actions_on_error':continue_unstarted_actions_on_error,
        'authority':{'runtime_id':run_id,'version':'1','organization_snapshot':{'schema_version':'organization.v2','run_id':run_id,
            'organizations':organizations,'authorizations':grants}}})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':{
        'run_id':run_id,'micro_supplier_order_scope':True,'micro_contractor_supply_scope':with_contractor,
        'query_saved_supply_on_error':query_saved_supply_on_error,
        'native_proposals':[{'role':r,'operation':'decide_monthly_operation'} for r in set(roles.values())]
            +([] if with_contractor else [{'role':'Contractor','operation':'select_supplier'}]),
        'native_decisions':[{'role':r,'decision_type':'monthly_enterprise_operation'} for r in set(roles.values())]
            +([] if with_contractor else [{'role':'Contractor','decision_type':'contractor_supplier_selection'}])}})
    flags={'contract_negotiation_started':True,'contract_negotiation_recommendation_recorded':True,
        'contractor_contract_decision':'accept_terms','owner_contract_decision_recorded':True,'owner_contract_accepted':True}
    initial=[]
    for project in ('supply-first','supply-followup'):
        first=project=='supply-first'
        initial.append({'project_id':project,'name':project,'project_type':'building','region':'Hong Kong','owner_id':owner_id,
            'initial_budget':1000,'contract_sum':1000,'current_stage':'contract_award','selected_contractor_id':contractor_id,
            'flags':{**flags,'contract_signed':first},'contracts':[{'contractor_id':contractor_id,'contract_sum':1000,'signed_tick':0}] if first else [],
            'engagements':[{'engagement_id':'initial-supply-first-main','project_id':project,'agent_id':contractor_id,
                'role':'Contractor','status':'active','start_stage':'contract_award','joined_at_tick':0,
                'resource_allocation':0.8,'contractual_obligation':True}] if first else []})
    request=SimulationCreateRequest.model_validate({'agent_source':'explicit','agents':[{'agent_id':org,'name':org,'role':role,
        'region':'Hong Kong','enterprise_type':'explicit_synthetic','total_resource_capacity':10,
        'occupied_resource':0.8 if role=='Contractor' else 0} for org,role in roles.items()],
        'initial_projects':initial,'enable_project_generation':False,'use_prior_network_edges':False,'ticks':2,'random_seed':42})
    _write(directory,'macro-request.json',request.model_dump(mode='json'))
    quote_note=('本包显式启用 A03：独立收到的询价、已确认产品提议、每件 80 HKD 工厂成本和 25% 加成均为合成假设。'
        '原 A03 实际执行计价及容量方法后，A04 核对全部报价行、付款条款、现有库存/容量与独立提供的 200 HKD 提议一致。'
        '私有交接 Evidence 由实际 A03 任务/结果/来源生成；没有正式报价登记回执，也不改写独立条款。'
        if with_quote else '默认仅执行 A04，报价未声称来自本窗口 A03。')
    product_note=('本包显式启用 A02：同一收到的询价、工厂/用途/材料约束及目录属性证据均为合成假设，未声明独立设计检查。'
        '原 A02 实际调用兼容性方法；原 A02→A03 交接核对保存结果、完整产品行、原询价、授权和真实结果证据。'
        'A03 保留独立提供的产品提议及确认状态，A02 不产生专业批准或正式产品登记。'
        if with_product else '本窗口未执行 A02，已有产品提议是独立合成来源。')
    screening_note=('本包显式启用 A01：生产能力、factory_supply 功能权限、10 production-unit 产能及每容量时点 1 panel 生产率为独立合成来源，'
        '与 A03/A04 交付资源池及宏观规范化资源分开。原 A01 实算容量，原 A01→A02 交接核对实际完整响应与独立收到的同一询价。'
        '收到询价的 Evidence 只观察本次真实读取的合成输入，不是宏观正式收件回执；A01 不产生订单或资源预留。'
        if with_screening else '本窗口未执行 A01，询价为独立收到的合成输入。')
    contractor_note=('本包显式启用 CONTRACTOR-A05，取代原生选供规则；不再使用下述默认原生选供配置。'
        '本窗口明确关闭供应商 A 的中选后拒单策略，两供应商均继续接受。承包商初始偏好 A/B，并明确配置较早本机构中选后优先级惩罚 2。'
        '实际 A03 报价和 A04 接单支持独立收到的完整条款，经原 A05 验证后返回原生选供；后续 A05 读取本机构真实反馈后选择 B。'
        'A05 的主合同采购额度、收货/检验/付款/绑定权限及初始独立供应商签署视图是明确合成输入；初始作者授权不冒充本次 A03 签署。'
        '不披露供应商成本、库存、资金或策略；只对照准确报价行和付款规则。宏观选供不产生详细订单、正式供货合同、承诺占用或付款。'
        if with_contractor else '默认承包商选供使用原宏观实现，不计 CONTRACTOR-A05 微观覆盖。')
    extra_note=('\n以上两时点时序及 200 HKD 报价说明针对默认 supply-first / supply-followup。'
        'initial-supply-windows.json 另列的窗口仅为共享宿主预先提供微观资料，不在本子包预置对应项目或合同；'
        '具体交期、报价比例及采购限额按各窗口明确输入，供应商初始现金保持 1000 HKD。'
        '追加窗口必须由原宏观先产生本轮实际签约事件，后续真实请求才能执行；缺该事件保持未决。\n'
        if additional_project_windows else '')
    decline_note=('首项目供应商 A 在 '+first_decline_stage+' 阶段使用明确的独立拒绝业务来源；原处理器实际拒绝后，'
        '返回原生拒绝供货，停止后续阶段。后续项目的原 A01—A04 读取较早真实拒绝事件；不把拒绝记成中选或占用。'
        if first_decline_stage is not None else '')
    if decline_after_prior_declines is not None:
        decline_note+='\n已启用 --decline-after-prior-declines：原 A01 读取本机构严格较早的实际拒绝，达到显式次数阈值时按私有策略拒绝新增需求。接受、中选、缺结果及未解决事项不计拒绝；原商业来源和旧结果不改写。\n'
    actor_note=('\n--organization-actor-ids declares the initial organization-to-actor mapping '
        'recorded in initial-organization-actors.json. Native agents and business parties keep their '
        'organization IDs. Original grants bind each executing actor, including inquiry reception, '
        'private predecessor access and the independent buyer. Existing saved sources are never migrated.\n'
        if organization_actor_ids is not None else '')
    _write_launch_files(directory,assembly_hook='integration.supplier_order_native:configure_assembly',
        source_note='Explicit synthetic Supplier A04 order proposals, independent buyer acceptances, product/stock/cash/capacity sources and selection preference; normalized macro resources are not physical stock or cash. Only actual native requests, selected-supplier events and original micro results are observed.',
        readme_override='''# 原供应商微观接单与原生供货选择

运行 `& './run.ps1'`。实际 Supplier.consider_supply_order 请求执行原 SUPPLIER-A04 和原容量方法；最终确认复用同一结果。
默认承包商选供应商显式使用原 ContractorAgent.select_supplier，再确认同一提案；启用 --with-contractor 时改用原微观 A05。
两项目从明确的合成合同确认阶段开始：首项目已有签订记录及占用 0.8 的承包商委任，与企业初始占用一致；后续项目由原生命周期在时点 1 签订，时点 2 选择供应商。
所有具体产品、报价、已收订单提议、独立买方预先同意条款、库存、资金、容量、生产率、交期和比较指标均为明确合成来源，不由宏观规范化资源推导。
买方预先条款同意仅为显式初始假设，不是将未来承包商选中结果伪装成已签署回执。
默认供应商 A 配置较早一次实际被选中后拒绝新接单，B 不启用该策略；--with-contractor 的独立窗口关闭该拒单策略。真实本组织反馈经原事件、提案、最终确认和微观结果核对。
原生选供仅代表项目供货安排/就绪，不创建细粒度 SupplyOrder、库存预留、资金支付或第二套正式账本。库存和资金的时点快照是独立假设，不能据选中自动扣减。
部分接受、修订或未知结果保留未决状态，不冒充完整接受或原生规则兜底。真实资料、其他分支及 C3 履约继续接线。
'''+quote_note+'\n'+product_note+'\n'+screening_note+'\n'+contractor_note+'\n'+decline_note+'\n'+extra_note+
        '\n--allow-saved-recovery enables queries of the original in-process completed terminal result; '
        '--query-saved-supply-on-error returns it to the still-open native call after technical interruption. '
        'No missing-result replay, unstarted stage, engine restart, formal order or payment. Both flags default off.\n'
        '\n--with-product-substitution requires --with-quote --with-product and declares an independent initial '
        'alternate catalogue code and versioned deviation. Original A02/A03/A04 preserve that deviation. '
        'With --with-contractor, original A05 reads independent requirement-level substitution permission; '
        '--withhold-contractor-substitution-permission leaves its needs_information result unresolved. '
        'Initial commercial assent is separate from this permission; neither is a product approval or delivery receipt.\n'
        '\n--continue-unstarted-actions-on-error defaults off. It continues once only when the original worker '
        'proves the same registered action has not started preparation, within the still-open original native call. '
        'Earlier actions and source producers are not rerun. Started preparation, missing results and changed '
        'sources/authority stay unresolved. Independent of saved-result recovery; no engine/process restart.\n'+actor_note)
    return {'status':'synthetic_supplier_order_bundle_unverified','directory':str(directory),'plans':len(plans)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--with-quote',action='store_true',help='Run original A03 before original A04 with a private exact-offer evidence check')
    parser.add_argument('--with-product',action='store_true',help='Run original A02 and its original authorized handoff before A03; requires --with-quote')
    parser.add_argument('--with-screening',action='store_true',help='Run original A01 and its original authorized handoff before A02; requires --with-product')
    parser.add_argument('--with-contractor',action='store_true',help='Run original Contractor A05 on actual accepted quotes and own feedback; requires --with-quote')
    parser.add_argument('--first-decline-stage',choices=['screening','product','quote'],help='Explicit first Supplier negative business inputs; may compose original micro Contractor selection')
    parser.add_argument('--decline-after-prior-declines',type=int)
    parser.add_argument('--allow-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-supply-on-error',action='store_true')
    parser.add_argument('--with-product-substitution',action='store_true')
    parser.add_argument('--withhold-contractor-substitution-permission',action='store_true')
    parser.add_argument('--continue-unstarted-actions-on-error',action='store_true')
    parser.add_argument('--organization-actor-ids',type=json.loads,
        help='Initial JSON mapping of organization IDs to distinct actor IDs; never applied to runtime history')
    args=parser.parse_args(argv);print(json.dumps(build_bundle(args.output,run_id=args.run_id,with_quote=args.with_quote,
        with_product=args.with_product,with_screening=args.with_screening,with_contractor=args.with_contractor,
        first_decline_stage=args.first_decline_stage,allow_saved_recovery=args.allow_saved_recovery,
        decline_after_prior_declines=args.decline_after_prior_declines,
        query_saved_supply_on_error=args.query_saved_supply_on_error,
        with_product_substitution=args.with_product_substitution,
        contractor_substitution_permitted=not args.withhold_contractor_substitution_permission,
        continue_unstarted_actions_on_error=args.continue_unstarted_actions_on_error,
        organization_actor_ids=args.organization_actor_ids)))


if __name__=='__main__':main()
