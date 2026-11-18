"""Initial independent contract terms for the original native negotiation loop."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

from integration.bootstrap import enable_gba_imports
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.contractor_formation_native import ContractorFormationPlan,ContractorFormationNativeSettings
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_formation_objects import ContractorFormationTermsView,contractor_agreement_digest,contractor_formation_schemas
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,max_prior_accept_terms=1,organization_ids=None,clock_id=None,followup_ticks=(2,),
        with_owner_award=False,max_prior_owner_accepts=1,max_prior_owner_payment_delays=None,with_payment_project=False,
        random_seed=42,max_prior_construction_suspensions=None,with_suspension_project=False,
        suspension_project_design_quality=0.0):
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    role_names=('Owner','Contractor','QS','Bank','Architect','Engineer','Government','Supplier')
    participants=organization_ids or {role:'terms-'+role.lower() for role in role_names}
    if (set(participants)!=set(role_names) or len(set(participants.values()))!=len(role_names)
            or any(not isinstance(org,str) or not org.strip() for org in participants.values())):
        raise ValueError('Contract terms need eight distinct explicitly declared role identities')
    if (not followup_ticks or any(type(t) is not int or t<2 for t in followup_ticks)
            or list(followup_ticks)!=sorted(set(followup_ticks))):
        raise ValueError('Followup contract source ticks must be distinct increasing integers from two')
    if max_prior_owner_payment_delays is not None and (type(max_prior_owner_payment_delays) is not int or max_prior_owner_payment_delays<1):
        raise ValueError('Contractor delay preference must be an explicit positive request count')
    if type(random_seed) is not int:raise ValueError('Development random seed must be an explicit integer')
    if max_prior_construction_suspensions is not None and (type(max_prior_construction_suspensions) is not int or max_prior_construction_suspensions<1):
        raise ValueError('Suspension preference requires an explicit positive event count')
    if (type(suspension_project_design_quality) not in {int,float} or not 0<=suspension_project_design_quality<=1
            or not with_suspension_project and suspension_project_design_quality!=0):
        raise ValueError('Initial design quality requires an explicit suspension source project and a bounded score')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]/'integration/examples'
    raw_host=json.loads((root/'role_contract_contractor_formation_accept_host.json').read_bytes())
    raw_source=raw_host['settings']['source_settings'];raw_invocation=json.loads((root/'role_contract_contractor_formation_accept_invocation.json').read_bytes())
    roles={org:role for role,org in participants.items()}
    owner,contractor=participants['Owner'],participants['Contractor'];clock=ref('ClockProfile',clock_id or run_id+'-monthly-clock')
    point=lambda n:{'clock_ref':clock,'offset':n}
    common=ref('Evidence',run_id+'-initial-declarations')
    declaration_hash=task_digest({'original_template_sha256':hashlib.sha256((root/'role_contract_contractor_formation_accept_host.json').read_bytes()).hexdigest(),
        'run_id':run_id,'projects':['terms-first','terms-followup'],'currency':'HKD','native_contract_sum':'100',
        'timeline_shift':-9,'native_month_is_explicit_template_tick':True,
        'counterparty_acceptances':[],'max_prior_accept_terms':max_prior_accept_terms,
        'max_prior_owner_payment_delays':max_prior_owner_payment_delays,'with_payment_project':with_payment_project,
        'max_prior_construction_suspensions':max_prior_construction_suspensions,
        'with_suspension_project':with_suspension_project,'suspension_project_design_quality':suspension_project_design_quality,
        'initial_participants':participants,'clock_ref':clock,'followup_ticks':list(followup_ticks)})
    plans=[];snapshot=None
    for project,tick in [('terms-first',1)]+[('terms-followup',tick) for tick in followup_ticks]:
        tag=project+'-t'+str(tick)
        identities={'v2-fixture-contractor-actor':contractor,'v2-fixture-owner-actor':owner,
            'v2-fixture-contractor':contractor,'v2-fixture-owner':owner,'synthetic-HK':'Hong Kong',
            'synthetic-v2-contractor-formation-accept-01':run_id}
        def transform(value):
            if isinstance(value,str):return identities.get(value,value)
            if isinstance(value,list):return [transform(v) for v in value]
            if not isinstance(value,dict):return value
            if set(value)=={'kind','id','version'}:
                kind=value['kind'];name=value['id']
                if kind=='ActionContract':return deepcopy(value)
                if kind=='ClockProfile':return deepcopy(clock)
                if kind=='Evidence':return deepcopy(common)
                if kind=='Project':return ref(kind,contractor+'-other-business' if name.endswith('-other-project') else project)
                if kind=='WorkScope':return ref(kind,contractor+'-other-work' if name.endswith('-other-work') else project+'-work')
                if kind=='FunctionAssignment':return ref(kind,(owner if name.endswith('-owner-function') else contractor)+'-formation-function')
                if kind=='Organization':return ref(kind,identities.get(name,name))
                if kind in {'ResourcePool','ResourceCommitment','FundingSource'}:
                    return ref(kind,contractor+'-'+name.removeprefix('v2-formation-accept-'),tag)
                return ref(kind,tag+'-'+name.removeprefix('v2-formation-accept-'))
            if set(value)=={'clock_ref','offset'}:return point(max(0,value['offset']-9))
            return {k:transform(v) for k,v in value.items()}
        objects=transform(raw_source['source_projection']['objects']);context=transform(raw_invocation['context'])
        inputs=transform(raw_invocation['action_input']);inputs['counterpart_acceptance_refs']=[]
        objects=[r for r in objects if r['ref']['kind']!='PartyAcceptance']
        native=ref('Evidence',tag+'-actual-native-negotiation')
        objects.append({'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'actual-native-contract-terms-request-and-own-prior-negotiations','content_hash':None,'effective_window':None}})
        by_kind=lambda kind:next(row['value'] for row in objects if row['ref']['kind']==kind)
        for kind in ('ContractorCapacity','FundingPosition','FundingSource'):by_kind(kind)['as_of']=point(tick)
        basis=by_kind('Evidence');basis.update(locator='explicit-initial-contract-terms-cash-crew-and-old-obligation-declarations',content_hash=declaration_hash)
        by_kind('ClockProfile')['tick_unit']='month'
        terms=by_kind('ContractTerms');profile=by_kind('ContractFormationProfile')
        # Final identities/time precede the reviewed agreement digest. No
        # runtime terms, methods or saved decisions are renamed or resealed.
        profile['reviewed_agreement_sha256']=contractor_agreement_digest(ContractorFormationTermsView.model_validate(terms))
        profile['evidence_refs'].append(native)
        profile['note']='Independent Contractor terms decision only; counterpart consent, signature, reservation and payment remain separate.'
        change=ref('ContractChangeRequest',tag+'-review-price-before-further-acceptance')
        objects.append({'ref':change,'value':{'ref':change,'evidence_refs':[common],
            'scope':context['scope'],'available_at':point(0),'effective_window':deepcopy(terms['effective_window']),
            'offer_ref':terms['offer_ref'],'terms_ref':terms['ref'],'bid_ref':terms['bid_ref'],
            'allowed':known(True),'changed_field_codes':['price'],'stage':'acceptance','satisfied':known(True)}})
        context.update(run_id=run_id,operation_id=tag+'-CONTRACTOR-A04',task_ref=ref('DecisionTask',tag),
            business_time=point(tick),read_token=tag+'-read',execution_mode='rule',visible_refs=[row['ref'] for row in objects])
        candidates=by_kind('CandidateSet');candidates.update(operation_id=context['operation_id'],as_of=point(tick))
        candidates['candidates'].append({'ref':change,'permitted_choices':['revise']})
        for row in objects:
            if row['ref']['kind']=='Authorization':row['value']['readable_refs']=deepcopy(context['visible_refs'])
        initial=transform(raw_source['organization_snapshot']);initial['run_id']=run_id
        initial['authorizations']=[deepcopy(row['value']) for row in objects if row['ref']['kind']=='Authorization']
        for organization in initial['organizations']:
            organization.update(source_ids=['synthetic:'+organization['organization_id']],public_location=known('Hong Kong'),
                public_description='Explicit initial synthetic contract terms; no counterpart acceptance, signature or cash execution.')
        if snapshot is None:snapshot=initial
        else:
            from integration.financing_professional_development import _merge_snapshot
            snapshot=_merge_snapshot(snapshot,initial)
        # All closed source schemas are checked before a native engine exists.
        schemas=contractor_formation_schemas()
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']==native:value['content_hash']='0'*64
            schemas.validate_projection(Reference.model_validate(row['ref']),value)
        plan=ContractorFormationPlan.model_validate({'organization_id':contractor,'project_id':project,'tick':tick,
            'context':context,'action_input':inputs,'objects':objects,'native_evidence_ref':native,
            'history_revision_change_refs':[change],'max_prior_accept_terms':max_prior_accept_terms,
            'max_prior_owner_payment_delays':max_prior_owner_payment_delays,
            'max_prior_construction_suspensions':max_prior_construction_suspensions,
            'native_contract_currency':'HKD','utility':{'value':'0.7','unit':'score','basis_ref':common},
            'probability':{'value':'1','unit':'probability','basis_ref':common}})
        plans.append(plan.model_dump(mode='json'))
    declared={organization['organization_id'] for organization in snapshot['organizations']}
    for organization,role in roles.items():
        if organization in declared:continue
        snapshot['organizations'].append({'organization_id':organization,'actor_id':organization,'source_ids':['synthetic:'+organization],
            'public_description':'Explicit background native participant; no micro business action is claimed.',
            'public_location':known('Hong Kong'),'members':[],'evidence_refs':[common],
            'assignments':[{'role':role,'function_ref':ref('FunctionAssignment',organization+'-native-function'),
                'configuration_version':'1','basis_refs':[common]}]})
    source=_write(directory,'contractor-formation-input.json',{'schema_version':'contractor-formation-input.v1','run_id':run_id,'plans':plans})
    owner_settings=None
    if with_owner_award:
        from integration.owner_award_native_development import build_owner_sources
        owner_settings,snapshot=build_owner_sources(directory,run_id=run_id,formation_plans=plans,snapshot=snapshot,
            max_prior_accepts=max_prior_owner_accepts)
    settings=ContractorFormationNativeSettings.model_validate({'version':'1','policy_version':'explicit-contract-terms-v1',**source,
        'authority':{'runtime_id':run_id,'version':'1','organization_snapshot':snapshot},'owner':owner_settings})
    request={'agent_source':'explicit','enable_project_generation':False,'use_prior_network_edges':False,
        'random_seed':random_seed,'ticks':3,
        'agents':[{'agent_id':org,'name':org,'role':role,'region':'Hong Kong','enterprise_type':'explicit_synthetic',
            'total_resource_capacity':10,'financial_capacity':1,'management_capability':1,'payment_reliability':1,'decision_speed':1}
            for org,role in roles.items()],
        'initial_projects':[{'project_id':project,'name':project,'project_type':'building','region':'Hong Kong',
            'owner_id':owner,'initial_budget':200,'contract_sum':100,'current_stage':'contract_award',
            'selected_contractor_id':contractor,'selected_qs_id':participants['QS'],
            'performance':{'planned_duration':20},
            'flags':({'contract_negotiation_started':True} if project=='terms-first' else {}),
            'bids':[{'contractor_id':contractor,'contractor_name':contractor,'bid_price':100,'expected_profit':20,'risk_level':0.1}]}
            for project in ('terms-first','terms-followup')]}
    if with_payment_project:
        project='terms-existing-construction'
        request['initial_projects'].append({'project_id':project,'name':project,'project_type':'building','region':'Hong Kong',
            'owner_id':owner,'initial_budget':2000000,'contract_sum':1000000,'current_stage':'construction',
            'selected_contractor_id':contractor,'contracts':[{'contractor_id':contractor,'contract_sum':1000000,
                'source':'explicit-existing-contract-not-current-micro-signature'}],
            'engagements':[{'engagement_id':project+'-existing-contractor','project_id':project,'agent_id':contractor,
                'role':'Contractor','status':'active','start_stage':'construction','joined_at_tick':0,'resource_allocation':1}],
            'flags':{'last_costed_progress':0.25},'performance':{'actual_progress':0.25,'planned_progress':0.25,
                'planned_duration':60,'overall_quality':1,'defect_rate':0,'safety_risk':0,'variation_risk':0,'claim_risk':0}})
        next(a for a in request['agents'] if a['agent_id']==contractor)['occupied_resource']=1
        next(a for a in request['agents'] if a['agent_id']==owner)['payment_reliability']=0
    if with_suspension_project:
        project='terms-existing-suspension'
        request['initial_projects'].append({'project_id':project,'name':project,'project_type':'building','region':'Hong Kong',
            'owner_id':owner,'initial_budget':2000,'contract_sum':1000,'current_stage':'construction',
            'selected_contractor_id':contractor,'contracts':[{'contractor_id':contractor,'contract_sum':1000,'signed_tick':0,
                'source':'explicit-initial-contract-not-current-micro-signature'}],
            'engagements':[{'engagement_id':project+'-existing-contractor','project_id':project,'agent_id':contractor,
                'role':'Contractor','status':'active','start_stage':'construction','joined_at_tick':0,
                'resource_allocation':1,'contractual_obligation':True}],
            'flags':{'last_costed_progress':0},'performance':{'actual_progress':0,'planned_progress':0,
                'design_quality':suspension_project_design_quality,'overall_quality':suspension_project_design_quality,
                'defect_rate':1-suspension_project_design_quality,'planned_duration':60,'variation_risk':0,'claim_risk':0}})
        actor=next(a for a in request['agents'] if a['agent_id']==contractor)
        actor['occupied_resource']=actor.get('occupied_resource',0)+1
    request=SimulationCreateRequest.model_validate(request)
    _write(directory,'macro-request.json',request.model_dump(mode='json'))
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':{
        'run_id':run_id,'micro_contractor_formation_scope':True,
        'micro_owner_award_scope':with_owner_award,
        'native_proposals':[{'role':role,'operation':'decide_monthly_operation'} for role in roles.values()]+([] if with_owner_award else [{'role':'Owner','operation':'decide_contract_award'}]),
        'native_decisions':[{'role':role,'decision_type':'monthly_enterprise_operation'} for role in roles.values()]+([] if with_owner_award else [{'role':'Owner','decision_type':'owner_contract_award'}])}})
    _write(directory,'input-provenance.json',{'schema_version':'native-contract-terms-initial-input.v1','run_id':run_id,
        'initial_selected_bids':['terms-first','terms-followup'],'initial_negotiation_open':['terms-first'],
        'counterpart_acceptances':[],'native_contract_sum_currency':'HKD','template_tick_maps_to_native_month':True,
        'with_owner_award':with_owner_award,'max_prior_owner_accepts':max_prior_owner_accepts,
        'max_prior_owner_payment_delays':max_prior_owner_payment_delays,'with_payment_project':with_payment_project,
        'max_prior_construction_suspensions':max_prior_construction_suspensions,'with_suspension_project':with_suspension_project,
        'suspension_project_initial_quality':{'design_quality':suspension_project_design_quality,
            'overall_quality':suspension_project_design_quality,'defect_rate':1-suspension_project_design_quality},
        'suspension_scene':'Optional explicitly existing signed contract, dated Contractor engagement and aggregate initial quality. '
            'These are independent synthetic initial facts, not current inspection/work evidence or a prewritten suspension. '
            'Only the unchanged native lifecycle can emit project_suspended; its empty data carries no detailed cause or fault attribution.',
        'random_seed':random_seed,
        'payment_scene':'Optional declared existing construction, contract, progress, engagement and native Owner payment reliability 0. '
            'Actual requests/delays must be emitted by the unchanged native engine; counts are not cash, outstanding debt or QS certificates.',
        'initial_participants':participants,'clock_ref':clock,
        'limits':['Selected bids, detailed terms, qualification, physical crew, cash restrictions, old liabilities and forecasts are independent synthetic initial sources.',
            'The first negotiation is initially open; subsequent negotiation posture events must be emitted by the original native engine.',
            ('Owner award uses original OWN-A10 with actual earlier Contractor acceptance and independently reviewed complete agreement; no acceptance is prewritten.'
                if with_owner_award else 'Native accepted terms are a negotiation posture, not the detailed effective agreement, resource reservation or payment. Owner final award remains explicit original native behavior.'),
            'Only initial ContractFormationProfile review digests are calculated; saved results and original examples remain untouched.']})
    readme='''# 原 Contractor A04 与签约前条款判断

运行 `& ./run.ps1`。两个已选承包商的项目、首项目已开启谈判、原投标及详细条款都是明确合成初始输入，不计本轮投标或业主选择成果。
真实 decide_contract_terms 请求触发原 A04 容量/现金方法；同一原结果交原 contract_negotiation 有界决定，宏观记录实际谈判姿态。
后轮只读严格较早的本承包商原事件及原微观结果、提案和确认。显式累计接受次数偏好可要求价格复核，原 A04 返回 revise，再由宏观记录 request_revision；不由历史推导新债务或资源占用。
双方接受、签署、生效和细粒度承诺分开；没有预置对方接受。
新微观细化输入不能扩展宏观合同粒度；有效合同、标准资源占用和项目阶段只由原宏观维护，不建立第二套账本。
'''
    readme+=('已启用原 OWN-A10：业主只接收较早真实 Contractor A04 接受及原生谈判事件，核对完整协议和独立签署权限，再实算本业主管理资源与授权预算。提案和最终决定复用同一结果，未满足条件不映射为无条件接受。可按较早本业主实际授标反馈及预声明偏好要求后续价格修订；拒绝不冒充修订。宏观仍独占正式签约与标准资源占用，不据此宣称详细协议全部生效或已经付款。\n'
        if with_owner_award else '业主最终授标仍用明确的原宏观路由，不计 OWN-A10 微观覆盖。\n')
    readme+='\n可选 --max-prior-owner-payment-delays N：按本承包商严格较早、当前业主的实际延迟请求数，要求复核独立允许的价格变更；默认关闭。请求与延迟事件只计一次，不认定仍未付款、欠款余额或现金减少。--with-payment-project 仅提供既有施工/合同/进度/占用及业主付款可靠度 0 的独立合成来源，延迟仍由原宏观随机规则实际产生；可用 --max-prior-accept-terms 999 隔离观察该偏好。\n'
    readme+='\n--max-prior-construction-suspensions N 默认关闭；只把本承包商较早真实施工暂停作为后续新条款的私有价格复核偏好，原 A04 仍核对独立允许的变更。--with-suspension-project 提供明确初始既有合同、承包商委任及设计质量，--suspension-project-design-quality 可声明 0—1 初始质量；暂停必须由原宏观实际执行。事件没有详细原因、责任、计量或现金信息，不归责供应商/业主、不释放资源、不免除债务，不等于 A12 完整收尾。\n'
    _write_launch_files(directory,assembly_hook='integration.contractor_formation_native:configure_assembly',readme_override=readme)
    return {'status':'contract_terms_source_candidate','directory':str(directory),'run_id':run_id}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-id',required=True);parser.add_argument('--max-prior-accept-terms',type=int,default=1)
    parser.add_argument('--with-owner-award',action='store_true')
    parser.add_argument('--max-prior-owner-accepts',type=int,default=1)
    parser.add_argument('--max-prior-owner-payment-delays',type=int)
    parser.add_argument('--with-payment-project',action='store_true')
    parser.add_argument('--random-seed',type=int,default=42)
    parser.add_argument('--max-prior-construction-suspensions',type=int)
    parser.add_argument('--with-suspension-project',action='store_true')
    parser.add_argument('--suspension-project-design-quality',type=float,default=0.0)
    args=parser.parse_args(argv);print(json.dumps(build_bundle(args.output,run_id=args.run_id,max_prior_accept_terms=args.max_prior_accept_terms,
        with_owner_award=args.with_owner_award,max_prior_owner_accepts=args.max_prior_owner_accepts,
        max_prior_owner_payment_delays=args.max_prior_owner_payment_delays,with_payment_project=args.with_payment_project,
        random_seed=args.random_seed,max_prior_construction_suspensions=args.max_prior_construction_suspensions,
        with_suspension_project=args.with_suspension_project,
        suspension_project_design_quality=args.suspension_project_design_quality)))


if __name__=='__main__':main()
