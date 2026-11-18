"""Supported native scene plus independently declared private A02 benchmark dossier."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.contractor_monthly_strategy import MonthlyContractorStrategyPlan
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.commercial_actions import CommercialActionAssembler
from integration.contractor_bid_actions import ContractorBidActionAssembler
from integration.bootstrap import enable_gba_imports
from src.actions.contracts.common import Reference
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_schemas
from src.coordination.tasks import task_digest

ROOT=Path(__file__).resolve().parents[1]


def build_bundle(directory,*,run_id,material_price_index=1.2,ticks=2):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    source=ROOT/'integration/examples/role_contract_contractor_bid_host.json'
    seed=json.loads(source.read_bytes())['settings']['source_settings']
    original=json.loads((ROOT/'integration/examples/role_contract_contractor_bid_invocation.json').read_bytes())
    org='v2-publication-contractor';actor=original['context']['actor_id'];clock=original['context']['business_time']['clock_ref']
    organizations=deepcopy(seed['organization_snapshot']['organizations']);grants=[];plans=[]
    own=next(o for o in organizations if o['organization_id']==org);immutable_sources={}
    for tick in range(1,ticks+1):
        tag='monthly-strategy-'+str(tick)
        def bind(value):
            if isinstance(value,list):return [bind(v) for v in value]
            if isinstance(value,dict):
                if set(value)=={'kind','id','version'}:
                    return deepcopy(value) if value['kind'] in {'ClockProfile','ActionContract','FunctionAssignment','Evidence','Project','WorkScope'} else {**value,'version':'strategy-'+str(tick)}
                if set(value)=={'clock_ref','offset'}:return {**deepcopy(value),'offset':max(0,value['offset']-12)}
                return {k:bind(v) for k,v in value.items()}
            return value
        objects=bind(seed['source_projection']['objects']);qcontext=bind(original['context']);now={'clock_ref':clock,'offset':tick}
        qcontext.update(run_id=run_id,execution_mode='rule',operation_id=tag+'-bid',read_token=tag+'-bid-read',task_ref=ref('DecisionTask',tag+'-bid'),business_time=now)
        candidate=next(r['value'] for r in objects if r['ref']==qcontext['candidate_set_ref']);candidate.update(operation_id=qcontext['operation_id'],as_of=now)
        for row in objects:
            if row['ref']['kind']=='ContractorCapacity':row['value']['as_of']=now
        native_bid=ref('Evidence',tag+'-actual-bid-policy')
        window={'start':{'clock_ref':clock,'offset':0},'end':{'clock_ref':clock,'offset':100},'bounds':'closed_open'}
        objects.append({'ref':native_bid,'value':{'ref':native_bid,'source_kind':'synthetic','basis_kind':'observed','locator':'actual-monthly-request-and-confirmed-prior-private-strategy','content_hash':None,'effective_window':window}})
        pricing_ref=bind(original['action_input']['pricing_profile_ref']);pricing=next(r['value'] for r in objects if r['ref']==pricing_ref);pricing['markup_fraction']=None
        qinput={k:bind(original['action_input'][k]) for k in ('pricing_profile_ref','capacity_ref','cost_refs','allowed_method_refs')}
        qcontext['visible_refs']=[r['ref'] for r in objects]
        for row in objects:
            if row['ref']['kind']=='Authorization':
                row['value']['readable_refs']=deepcopy(qcontext['visible_refs']);grants.append(deepcopy(row['value']))
        scope={'kind':'organization','ref':ref('Organization',org,'monthly-strategy-'+str(tick)),'coverage_refs':[]}
        basis=ref('Evidence',tag+'-independent-policy');native=ref('Evidence',tag+'-actual-native')
        function=ref('FunctionAssignment',tag);grant_ref=ref('Authorization',tag);profile_ref=ref('ContinuationProfile',tag)
        state_ref=ref('ContinuationState',tag);basis_ref=ref('ContinuationBasis',tag);policy_ref=ref('MonthlyBidStrategyPolicy',tag)
        observation=ref('MonthlyBidStrategyObservation',tag);rule=ref('LearningMethod',tag+'-private-risk-rule');candidates=ref('CandidateSet',tag)
        original_observation=ref('Observation',tag+'-actual-native-observation')
        own['assignments'].append({'role':'Contractor','function_ref':function,'configuration_version':'1','basis_refs':[basis]})
        rows=[]
        def put(reference,**fields):rows.append({'ref':reference,'value':{'ref':reference,**deepcopy(fields)}})
        put(basis,source_kind='synthetic',basis_kind='assumed',locator='independently-authorized-future-private-material-risk-markup-policy',
            content_hash=task_digest({'threshold':'1.05','base':'0.20','increment':'0.05','dossier_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}),effective_window=window)
        put(native,source_kind='synthetic',basis_kind='observed',locator='actual-current-native-monthly-request-and-confirmed-own-prior-execution',content_hash=None,effective_window=window)
        put(clock,**{k:v for k,v in next(r['value'] for r in objects if r['ref']==clock).items() if k!='ref'})
        for row in objects:
            if row['ref'] in next(r['value'] for r in objects if r['ref']==clock)['evidence_refs']:rows.append(deepcopy(row))
        put(scope['ref'],evidence_refs=[basis])
        put(function,role='Contractor',function_ref=function,configuration_version='1',basis_refs=[basis])
        rows[-1]['value'].pop('ref')
        common={'evidence_refs':[basis],'scope':scope,'available_at':now,'effective_window':window}
        authored={**common,'author_actor_id':actor,'author_organization_id':org,'author_function_ref':function,
            'author_authority_ref':grant_ref,'author_action_id':'CONTRACTOR-A12','authored_at':now}
        put(state_ref,**common,organization_id=org,run_id=run_id,contract_refs=[],commitment_refs=[],resource_calendar_ref=None,
            material_refs=[],obligation_refs=[],observation_refs=[original_observation],work_record_refs=[],document_refs=[],responsibility_refs=[],
            execution_refs=[],applied_observation_refs=[],coverage='unknown',as_of=now)
        put(basis_ref,**authored,organization_id=org,state_ref=state_ref,permitted={'state':'unknown','reason_code':'no_commercial_transition_requested','missing_refs':[]},
            allowed_choices=['record_lesson'],contract_refs=[],protection_task_refs=[],material_plan_ref=ref('MaterialDispositionPlan',tag+'-not-requested'),effect='proposal_then_actual_core_transition')
        put(rule,**authored,organization_id=org,calculation_method_ref=ref('Method','micro.contractor.monthly_material_risk_rule'),supported={'state':'known','value':True},
            outcome_catalog={'dimensionless_material_risk':'future_private_markup_policy'},effect='future_private_lesson_only')
        put(profile_ref,**authored,organization_id=org,state_ref=state_ref,actor_id=actor,function_ref=function,authority_ref=grant_ref,basis_ref=basis_ref,
            business_key=tag,choice='record_lesson',retain_resource_refs=[],release_candidate_refs=[],readiness_refs=[],transfer_plan_ref=None,
            source_refs=[original_observation],learning_method_ref=rule,lesson_assessment_ref=None,note='Private forward-looking rule, not statistical learning or commercial transition',
            monthly_bid_policy_ref=policy_ref,monthly_bid_observation_ref=observation)
        put(policy_ref,organization_id=org,scope=scope,authority_ref=grant_ref,effective_window=window,
            material_index_threshold={'value':'1.05','unit':'index','basis_ref':basis},base_markup='0.20',risk_markup_increment='0.05',evidence_refs=[basis])
        put(observation,organization_id=org,scope=scope,as_of=now,material_index=None,prior_own_outcomes=None,evidence_refs=[native])
        put(original_observation,**{**authored,'evidence_refs':[native]},recipient_organization_id=org,event_key=None,original_source_ref=native,
            source_sha256=None,observed_at=now,received_at=now,outcome_code='actual_native_material_index_observation',verified=None)
        put(candidates,operation_id=tag,scope=scope,as_of=now,candidates=[{'ref':rule,'permitted_choices':['record_lesson']}],search_profile_ref=ref('Profile',tag))
        rows[-1]['value'].pop('ref')
        visible=[r['ref'] for r in rows]+[grant_ref]
        grant={'ref':grant_ref,'organization_id':org,'actor_id':actor,'function_ref':function,'action_ids':['CONTRACTOR-A12'],'scopes':[scope],
            'readable_refs':visible,'tool_ids':[],'basis_refs':[basis],'validity':window}
        rows.append({'ref':grant_ref,'value':grant});grants.append(deepcopy(grant))
        context={'run_id':run_id,'actor_id':actor,'function_ref':function,'authorization_refs':[grant_ref],'operation_id':tag,
            'contract_ref':ref('ActionContract','CONTRACTOR-A12'),'task_ref':ref('DecisionTask',tag),'scope':scope,'business_time':now,
            'read_token':tag+'-read','visible_refs':visible,'candidate_set_ref':candidates,'execution_mode':'rule'}
        for row in rows:
            value=deepcopy(row['value'])
            if row['ref']==native:value['content_hash']='0'*64
            if row['ref']==observation:value.update(material_index={'value':'1','unit':'index','basis_ref':native},prior_own_outcomes=[])
            if row['ref']==original_observation:value.update(event_key='validation-only',source_sha256='0'*64,verified={'state':'known','value':True})
            commercial_continuation_schemas().validate_projection(Reference.model_validate(row['ref']),value)
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']==native_bid:value['content_hash']='0'*64
            if row['ref']==pricing_ref:value['markup_fraction']='0.20'
            ContractorBidActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
        for row in [*rows,*objects]:
            key=task_digest(row['ref']);digest=task_digest(row['value'])
            if key in immutable_sources and immutable_sources[key]!=digest:
                raise ValueError('Private scenario changes the immutable source '+str(row['ref']))
            immutable_sources[key]=digest
        plans.append(MonthlyContractorStrategyPlan.model_validate({'organization_id':org,'role':'Contractor','tick':tick,'context':context,
            'action_input':{'profile_ref':profile_ref},'objects':rows,'native_evidence_ref':native,'observation_ref':observation,
            'bid':{'context':qcontext,'action_input':qinput,'objects':objects,'native_evidence_ref':native_bid}}).model_dump(mode='json'))
    sources=_write(directory,'contractor-monthly-strategy-input.json',{'schema_version':'contractor-monthly-strategy-input.v1','run_id':run_id,'plans':plans})
    owner={'organization_id':'strategy-owner','actor_id':'strategy-owner-actor','source_ids':['synthetic:private-strategy-benchmark-owner'],
        'public_description':'Independent initial benchmark project owner; no tender publication or detailed relationship is inferred.',
        'public_location':{'state':'known','value':'Hong Kong'},'members':[],'evidence_refs':[ref('Evidence','strategy-owner-declared-initial-profile')],
        'assignments':[{'role':'Owner','function_ref':ref('FunctionAssignment','strategy-owner'),'configuration_version':'1','basis_refs':[ref('Evidence','strategy-owner-declared-initial-profile')]}]}
    settings=ProfessionalMonthlySettings.model_validate({'authority':{'runtime_id':run_id,'version':'1','organization_snapshot':{
        'schema_version':'organization.v2','run_id':run_id,'organizations':organizations+[owner],'authorizations':grants}},**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':{'run_id':run_id,
        'native_proposals':[{'role':role,'operation':'decide_monthly_operation'} for role in ('Owner','Architect')],
        'native_decisions':[{'role':role,'decision_type':'monthly_enterprise_operation'} for role in ('Owner','Architect')]}})
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    macro=SimulationCreateRequest.model_validate({'agent_source':'explicit','ticks':ticks,'random_seed':42,'enable_project_generation':False,'use_prior_network_edges':False,
        'macro_environment':{'material_price_index':material_price_index},'agents':[{'agent_id':o['organization_id'],'name':o['organization_id'],
            'role':'Contractor' if o['organization_id']==org else 'Architect','region':'Hong Kong','enterprise_type':'explicit_synthetic','total_resource_capacity':10} for o in organizations]
            +[{'agent_id':'strategy-owner','name':'strategy-owner','role':'Owner','region':'Hong Kong','enterprise_type':'explicit_synthetic','total_resource_capacity':10}],
        'initial_projects':[{'project_id':original['context']['scope']['ref']['id'],'name':'Independent private bid benchmark, no published tender','project_type':'building',
            'region':'Hong Kong','owner_id':'strategy-owner','initial_budget':1000,'current_stage':'design'}]})
    _write(directory,'macro-request.json',macro.model_dump(mode='json'));_write_launch_files(directory,assembly_hook='integration.contractor_monthly_strategy:configure_assembly',readme_override=__doc__)
