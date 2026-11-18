"""Reuse original independent quote dossiers; no order, stock or price result is prefilled."""
from copy import deepcopy
from pathlib import Path
from integration.supplier_order_native_development import build_bundle as quote_foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.supplier_monthly_prices import MonthlySupplierPricePlan,PrivatePriceQuotePlan
from integration.supplier_screening_actions import SupplierScreeningActionAssembler
from integration.supplier_quote_actions import SupplierQuoteActionAssembler
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,material_price_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'quote-foundation';quote_foundation(foundation,run_id=run_id,with_quote=True)
    settings=read(foundation/'assembly-host.json')['settings'];authority=deepcopy(settings['authority'])
    seeds=read(foundation/'supplier-order-input.json')['plans'];organizations={o['organization_id']:o for o in authority['organization_snapshot']['organizations']}
    plans=[];grants=[]
    for org in ('supply-a','supply-b'):
        seed=next(p for p in seeds if p['organization_id']==org and p['project_id']=='supply-first' and p['tick']==1)
        original=seed['quote'];assumed={task_digest(r['ref']) for r in original['objects'] if r['ref']['kind']=='Evidence' and r['value']['basis_kind']=='assumed'}
        for tick in (1,2):
            # One immutable product and independent cost/physical dossier. Fresh
            # read/observation versions prevent changing a published projection.
            def bind(value):
                if isinstance(value,list):return [bind(v) for v in value]
                if not isinstance(value,dict):return value
                if set(value)=={'kind','id','version'}:
                    if value['kind'] in {'ProductSpecification','Project','WorkScope','Location','DeliveryService','FunctionAssignment','ClockProfile'} or task_digest(value) in assumed:return deepcopy(value)
                    return {**value,'version':'price-monthly-'+str(tick)}
                return {k:bind(v) for k,v in value.items()}
            q=bind(original);qc=q['context'];now={**qc['business_time'],'offset':tick};tag=org+'-price-monitor-'+str(tick)
            qc.update(operation_id=tag+'-quote',business_time=now,read_token=tag+'-quote-read',task_ref=ref('DecisionTask',tag+'-quote'))
            for r in q['objects']:
                if r['ref']['kind'] in {'InventorySnapshot','SupplierCapacity'}:r['value']['as_of']=deepcopy(now)
                if r['ref']==q['action_input']['pricing_profile_ref']:r['value']['markup_rate']=None
                if r['ref']['kind']=='CandidateSet':r['value'].update(operation_id=qc['operation_id'],as_of=deepcopy(now))
            qgrant=next(r['value'] for r in q['objects'] if r['ref']==qc['authorization_refs'][0]);qgrant['readable_refs']=[r['ref'] for r in q['objects']]
            qc['visible_refs']=deepcopy(qgrant['readable_refs']);grants.append(deepcopy(qgrant))
            quote=PrivatePriceQuotePlan.model_validate({k:q[k] for k in ('context','action_input','objects','native_evidence_ref')})
            for r in quote.objects:
                v=deepcopy(r['value'])
                if r['ref']==quote.native_evidence_ref.model_dump(mode='json'):v['content_hash']='0'*64
                if r['ref']==quote.action_input['pricing_profile_ref']:v['markup_rate']=known('0.25')
                SupplierQuoteActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(r['ref']),v)
            owner=organizations[org];actor=owner['actor_id'];rr=lambda kind:ref(kind,tag)
            scope={'kind':'organization','ref':ref('Organization',org,'price-monthly-'+str(tick)),'coverage_refs':[]}
            basis=ref('Evidence',tag+'-private-policy');native=ref('Evidence',tag+'-actual-native');function=rr('FunctionAssignment');grant_ref=rr('Authorization')
            window={'start':{**now,'offset':1},'end':{**now,'offset':3},'bounds':'closed_open'}
            policy,observation,profile,market,capability,capacity=map(rr,['SupplierPriceMonitorPolicy','SupplierPriceMonitorObservation','SupplyScreeningProfile','MarketObservation','SupplierCapability','SupplierCapacity'])
            declared={'base_markup_rate':'0.25','risk_surcharge_rate':'0.05','material_index_threshold':'1.05',
                'scope':'private quote risk monitoring for one unchanged independent synthetic-panel product; no actual market unit cost inferred'}
            objects=[]
            def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**value}})
            add(basis,{'source_kind':'synthetic','basis_kind':'assumed','locator':'independently-authorized-private-quote-margin-and-initial-screening-metadata',
                'content_hash':task_digest(declared),'effective_window':window})
            add(native,{'source_kind':'synthetic','basis_kind':'observed','locator':'actual-native-material-index-current-original-A03-and-prior-confirmed-own-monitoring',
                'content_hash':None,'effective_window':window})
            assignment={'role':'Supplier','function_ref':function,'configuration_version':'1','basis_refs':[basis]}
            owner['assignments'].append(deepcopy(assignment));objects.append({'ref':function,'value':assignment})
            add(scope['ref'],{'evidence_refs':[basis]})
            unknown=lambda:{'state':'unknown','reason_code':'not_supplied_for_market_tracking','missing_refs':[]}
            add(capability,{'organization_id':org,'registration_region_id':known('Hong Kong'),'operating_region_ids':unknown(),
                'effective_window':window,'product_coverage':'unknown','products':[],'function_authority_refs':[],'evidence_refs':[basis]})
            add(capacity,{'organization_id':org,'as_of':now,'resource_coverage':'unknown','commitment_coverage':'unknown','resources':[],'commitments':[],'evidence_refs':[basis]})
            add(profile,{'organization_id':org,'effective_window':window,'policy':'evaluate','allow_limited_scope':False,'inquiry_priorities':[],
                'evidence_refs':[basis],'monthly_price_policy_ref':policy,'monthly_price_observation_ref':observation})
            add(market,{'scope':scope,'region_id':known('simulation_global'),'product_codes':known(['synthetic-panel']),
                'forecast_quantity':unknown(),'forecast_window':unknown(),'observed_at':now,'available_at':now,'evidence_refs':[native]})
            add(policy,{'organization_id':org,'scope':scope,'effective_window':window,'authority_ref':grant_ref,
                'base_markup_rate':'0.25','risk_surcharge_rate':'0.05','material_index_threshold':{'value':'1.05','unit':'index','basis_ref':basis},'evidence_refs':[basis]})
            add(observation,{'organization_id':org,'scope':scope,'as_of':now,'material_index':None,'current_original_quote':None,'prior_own_outcomes':None,'evidence_refs':[native]})
            context={**deepcopy(qc),'actor_id':actor,'function_ref':function,'authorization_refs':[grant_ref],'operation_id':tag,
                'contract_ref':ref('ActionContract','SUPPLIER-A01'),'task_ref':rr('DecisionTask'),'scope':scope,'business_time':now,
                'read_token':tag+'-read','candidate_set_ref':rr('CandidateSet')}
            objects.append({'ref':context['candidate_set_ref'],'value':{'operation_id':tag,'scope':scope,'as_of':now,
                'candidates':[{'ref':market,'permitted_choices':['track_market']}],'search_profile_ref':rr('Profile')}})
            grant={'ref':grant_ref,'organization_id':org,'actor_id':actor,'function_ref':function,'action_ids':['SUPPLIER-A01'],
                'scopes':[scope],'validity':window,'tool_ids':[],'basis_refs':[basis],'readable_refs':[]}
            objects.append({'ref':grant_ref,'value':grant});grant['readable_refs']=[r['ref'] for r in objects]
            context['visible_refs']=deepcopy(grant['readable_refs']);grants.append(deepcopy(grant))
            for r in objects:
                v=deepcopy(r['value'])
                if r['ref']==native:v['content_hash']='0'*64
                if r['ref']==observation:v.update(material_index={'value':'1','unit':'index','basis_ref':native},current_original_quote={},prior_own_outcomes=[])
                SupplierScreeningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(r['ref']),v)
            plans.append(MonthlySupplierPricePlan.model_validate({'organization_id':org,'role':'Supplier','tick':tick,'context':context,
                'action_input':{'inquiry_refs':[],'market_refs':[market],'capability_ref':capability,'capacity_ref':capacity,'screening_profile_ref':profile},
                'objects':objects,'native_evidence_ref':native,'observation_ref':observation,'quote':quote.model_dump(mode='json')}).model_dump(mode='json'))
    authority['organization_snapshot']['authorizations']=grants
    sources=_write(directory,'supplier-monthly-prices-input.json',{'schema_version':'supplier-monthly-prices-input.v1','run_id':run_id,'plans':plans})
    host=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':host.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':{'run_id':run_id,
        'native_proposals':[{'role':role,'operation':'decide_monthly_operation'} for role in ('Owner','Contractor')],
        'native_decisions':[{'role':role,'decision_type':'monthly_enterprise_operation'} for role in ('Owner','Contractor')]}})
    macro=read(foundation/'macro-request.json');macro['macro_environment']['material_price_index']=material_price_index
    macro['initial_projects']=[{'project_id':'supply-first','name':'Initial unappointed design background for private quotation; no order claimed',
        'project_type':'building','region':'Hong Kong','owner_id':'supply-owner','initial_budget':1000,'current_stage':'design'}]
    for agent in macro['agents']:agent['occupied_resource']=0
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.supplier_monthly_prices:configure_assembly',readme_override=__doc__)
