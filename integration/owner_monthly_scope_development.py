"""Explicit private case/budget inputs; actual global signal and prior draft remain unbound."""
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.owner_monthly_scope import MonthlyOwnerScopePlan,OwnerMonthlyScopeApplication
from integration.professional_monthly_development import build_bundle as monthly_foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.verify_tender_closed_loop import ROOT,read
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,market_demand_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'monthly-foundation';monthly_foundation(foundation,run_id=run_id,ticks=2)
    authority=read(foundation/'assembly-host.json')['settings']['authority'];original=read(foundation/'professional-monthly-input.json')
    owner,=[o for o in authority['organization_snapshot']['organizations'] if o['organization_id']=='professional-owner']
    org=owner['organization_id'];project=org+'-scope-project';seed_path=ROOT/'tests/fixtures/roles/owner_proposal.v1.json';seed=read(seed_path)
    basis=ref('Evidence',org+'-scope-fixture-basis');function=ref('FunctionAssignment',org+'-private-scope')
    assignment={'role':'Owner','function_ref':function,'configuration_version':'1','basis_refs':[basis]};owner['assignments'].append(deepcopy(assignment))
    policy={'source':'independently-declared-initial-private-scope-research','project_id':project,'threshold':'1.05','threshold_unit':'index',
        'global_index_usage':'private_research_gate_not_regional_demand','review_cash':'100','committed_review_cash':'30','restricted_review_cash':'20',
        'cash_currency':'HKD','scale_bounds_m2':['100','200'],'uncertain_rights':'unresolved','template_sha256':hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        'continuation_policy':'compare_same_case_only_after_actual_own_preparation'}
    plans=[];grants=[];immutable={}
    dynamic={'DemandObservation','Observation','OwnerCase','ProposalCandidate','ProposalSpace','FundingPosition','Issue'}
    for tick in (1,2):
        original_context=deepcopy(next(p['context'] for p in original['plans'] if p['tick']==tick));clock=original_context['business_time']['clock_ref']
        point=lambda n:{'clock_ref':deepcopy(clock),'offset':n}
        window={'start':point(0),'end':point(100),'bounds':'closed_open'}
        def remap(value):
            if isinstance(value,list):return [remap(v) for v in value]
            if isinstance(value,dict):
                if set(value)=={'kind','id','version'}:
                    if value['kind']=='ClockProfile':return deepcopy(clock)
                    if value['kind']=='Organization':return ref('Organization',org)
                    return ref(value['kind'],org+'-scope-'+value['id'],'month-'+str(tick) if value['kind'] in dynamic else '1')
                return {k:remap(v) for k,v in value.items()}
            if value=='owner':return org
            if value=='owner-actor':return owner['actor_id']
            if value=='HK':return 'Hong Kong'
            return value
        objects=remap(seed['objects']);inputs=remap(seed['input']);native=ref('Evidence',org+'-scope-native-'+str(tick))
        for row in objects:
            kind=row['ref']['kind'];v=row['value']
            if 'effective_window' in v:v['effective_window']=deepcopy(window)
            if 'available_at' in v:v['available_at']=point(tick if kind in dynamic and kind!='Issue' else 0)
            if kind=='OwnerObjective':
                v['signal_rules']=known([{'signal_code':'native_global_market_demand_index','comparison':'at_least',
                    'threshold':{'value':'1.05','unit':'index','basis_ref':basis}}]);v['maximum_observation_age']=known(0)
            elif kind=='DemandObservation':
                v.update(signal_code='native_global_market_demand_index',measure=None,observed_at=point(tick),learned_at=point(tick),evidence_refs=[native,basis])
            elif kind=='OwnerCase':v['updated_at']=point(tick)
            elif kind=='FundingPosition':v['as_of']=point(tick)
            elif kind=='TimeWindow':v.update(start=point(2),end=point(20),bounds='closed_open')
        objects+=[{'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed','locator':'independent-current-private-scope-case-and-budget',
            'content_hash':task_digest(policy),'effective_window':window}},
            {'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed','locator':'actual-native-monthly-input-own-project-and-confirmed-prior-private-draft',
            'content_hash':None,'effective_window':window}}, {'ref':function,'value':deepcopy(assignment)}]
        signal,=[r['value'] for r in objects if r['ref']==inputs['demand_refs'][0]]
        objects.append({'ref':signal['source_ref'],'value':{'ref':signal['source_ref'],'demand_ref':signal['ref'],'evidence_refs':[native]}})
        scope={'kind':'organization','ref':ref('Organization',org),'coverage_refs':[]};tag=org+'-monthly-scope-'+str(tick)
        candidate_set=ref('CandidateSet',tag);grant_ref=ref('Authorization',tag);prior=ref('OwnerBrief',tag+'-confirmed-prior')
        purpose,=[r['ref'] for r in objects if r['ref']['kind']=='PurposeProfile']
        objects.append({'ref':candidate_set,'value':{'operation_id':tag,'scope':scope,'as_of':point(tick),
            'candidates':[{'ref':purpose,'permitted_choices':['propose','revise']}],'search_profile_ref':ref('Profile',tag)}})
        visible=[r['ref'] for r in objects]+[prior]
        grant={'ref':grant_ref,'organization_id':org,'actor_id':owner['actor_id'],'function_ref':function,'action_ids':['OWN-A16'],
            'scopes':[scope],'validity':window,'readable_refs':visible,'tool_ids':[],'basis_refs':[basis]}
        objects.append({'ref':grant_ref,'value':grant});visible.append(grant_ref);grant['readable_refs']=deepcopy(visible);grants.append(deepcopy(grant))
        context={**original_context,'actor_id':owner['actor_id'],'function_ref':function,'authorization_refs':[grant_ref],'scope':scope,
            'contract_ref':ref('ActionContract','OWN-A16'),'operation_id':tag,'task_ref':ref('DecisionTask',tag),'read_token':tag+'-read',
            'business_time':point(tick),'visible_refs':visible,'candidate_set_ref':candidate_set,'execution_mode':'rule'}
        prior_template={'ref':prior,'organization_id':org,'case_ref':inputs['case_ref'],'objective_ref':inputs['objective_ref'],'brief':None,
            'status':'active','available_at':point(max(0,tick-1)),'effective_window':window,'evidence_refs':[native]}
        schemas=OwnerMonthlyScopeApplication.COMPONENTS['Owner'][0].SOURCE_SCHEMAS()
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']==native:value['content_hash']='0'*64
            if row['ref']==signal['ref']:value['measure']=known({'value':'1','unit':'index','basis_ref':native})
            typed=schemas.validate_projection(Reference.model_validate(row['ref']),value)
            key=task_digest(row['ref']);digest=task_digest(typed.model_dump(mode='json'))
            if key in immutable and immutable[key]!=digest:raise ValueError('Initial private scope changed an immutable source version: '+str(row['ref']))
            immutable[key]=digest
        plans.append(MonthlyOwnerScopePlan.model_validate({'organization_id':org,'role':'Owner','project_id':project,'tick':tick,
            'context':context,'action_input':inputs,'objects':objects,'native_evidence_ref':native,'signal_ref':signal['ref'],
            'prior_brief_ref':prior,'prior_template':prior_template,'continuation_policy':policy['continuation_policy']}).model_dump(mode='json'))
    authority['organization_snapshot'].update(organizations=[owner],authorizations=grants)
    source=_write(directory,'owner-monthly-scope-input.json',{'schema_version':OwnerMonthlyScopeApplication.INPUT_SCHEMA,'run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**source})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':{'run_id':run_id,'native_proposals':[],'native_decisions':[]}})
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    macro=read(foundation/'macro-request.json');macro.update(agents=[a for a in macro['agents'] if a['agent_id']==org],
        ticks=2,random_seed=42,enable_project_generation=False,initial_projects=[{'project_id':project,'name':'Explicit own project for private scope research',
        'project_type':'building','region':'Hong Kong','owner_id':org,'initial_budget':1000,'current_stage':'design',
        'performance':{'design_quality':0.1,'information_quality':0.1}}],
        macro_environment={**macro.get('macro_environment',{}),'market_demand_index':market_demand_index})
    _write(directory,'macro-request.json',SimulationCreateRequest.model_validate(macro).model_dump(mode='json'))
    _write(directory,'source-policy.json',policy)
    _write_launch_files(directory,assembly_hook='integration.owner_monthly_scope:configure_assembly',readme_override=__doc__)
