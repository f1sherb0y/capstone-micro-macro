"""Declare one complete benchmark treasury before binding actual monthly observations."""
from copy import deepcopy
import hashlib
from pathlib import Path
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.owner_monthly_capacity import MonthlyOwnerCapacityPlan,OwnerMonthlyCapacityApplication
from integration.professional_monthly_development import build_bundle as monthly_foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.verify_tender_closed_loop import ROOT,read
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,financing_condition_index,actual_cash='100'):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    if actual_cash not in {'100','30'}:raise ValueError('Only explicitly declared sufficient/shortfall treasury controls are supported')
    foundation=directory/'monthly-foundation';monthly_foundation(foundation,run_id=run_id,ticks=2)
    authority=read(foundation/'assembly-host.json')['settings']['authority'];original=read(foundation/'professional-monthly-input.json')
    owner,=[o for o in authority['organization_snapshot']['organizations'] if o['organization_id']=='professional-owner'];org=owner['organization_id']
    seed_path=ROOT/'tests/fixtures/roles/owner_financing.v1.json';seed=read(seed_path);basis=ref('Evidence',org+'-capacity-assumptions')
    names={'owner':org,'owner-actor':owner['actor_id'],'bank':'declared-capacity-lender','bank-actor':'declared-capacity-lender',
        'bank-two':'declared-capacity-second-lender','bank-two-actor':'declared-capacity-second-lender'}
    policy={'source':'independently-declared-complete-synthetic-initial-private-treasury','cash':actual_cash,'restricted_cash':'10','currency':'HKD',
        'existing_debt_principal':'15','original_obligation_due':'20','original_obligation_paid':'5','remaining_obligation':'15',
        'proposed_use':'20','approved_future_nonbank_release':'100','future_forecast_not_actual_cash':'1000',
        'independent_environment_watch_threshold':'0.95','no_ledger_mutation':True,'seed_sha256':hashlib.sha256(seed_path.read_bytes()).hexdigest()}
    plans=[];grants=[];functions={};immutable={}
    for tick in (1,2):
        base=deepcopy(next(p['context'] for p in original['plans'] if p['tick']==tick));clock=base['business_time']['clock_ref'];point=lambda n:{'clock_ref':deepcopy(clock),'offset':n}
        window={'start':point(0),'end':point(40),'bounds':'closed_open'}
        def remap(value):
            if isinstance(value,list):return [remap(v) for v in value]
            if not isinstance(value,dict):return names.get(value,value) if isinstance(value,str) else value
            if set(value)=={'kind','id','version'}:
                kind=value['kind']
                if kind=='ClockProfile':return deepcopy(clock)
                if kind=='Method':return deepcopy(value)
                if kind=='Evidence':return deepcopy(basis)
                if kind=='Organization':return ref(kind,names.get(value['id'],value['id']))
                return ref(kind,org+'-capacity-'+value['id'],'1' if kind=='FunctionAssignment' else 'month-'+str(tick))
            if set(value)=={'clock_ref','offset'}:return point(max(0,value['offset']-10))
            return {k:remap(v) for k,v in value.items()}
        objects=remap(seed['objects']);inputs=remap(seed['input']);scope={'kind':'organization','ref':ref('Organization',org),'coverage_refs':[]}
        native=ref('Evidence',org+'-capacity-native-'+str(tick));observation=ref('MonthlyOwnerCapacityObservation',org+'-capacity-observation','month-'+str(tick))
        inputs.update(scope_ref=scope,offers=[])
        profile,=[r['value'] for r in objects if r['ref']==inputs['funding_profile_ref']]
        profile.update(scope_ref=scope,policy=known('own_funds'),application=None,revision_ref=None,question_refs=[],required_condition_refs=[],monthly_capacity_observation_ref=observation)
        for row in objects:
            kind=row['ref']['kind'];v=row['value']
            if 'effective_window' in v:v['effective_window']=deepcopy(window)
            if 'as_of' in v:v['as_of']=point(tick)
            if kind in {'Account','FundingSource'}:v['actual_cash']['value']['value']=actual_cash
            if kind in {'FundingApproval','FundingPurpose'}:v['scope_ref']=scope
            if kind=='FunctionAssignment':functions[task_digest(v['function_ref'])]=deepcopy(v)
        tag=org+'-capacity-'+str(tick);candidate=ref('CandidateSet',tag)
        objects+=[{'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed','locator':'independent-complete-initial-private-treasury-declaration','content_hash':task_digest(policy),'effective_window':window}},
            {'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed','locator':'actual-native-monthly-financing-index-and-confirmed-earlier-own-review','content_hash':None,'effective_window':window}},
            {'ref':observation,'value':{'ref':observation,'organization_id':org,'scope':scope,'as_of':point(tick),'actual_financing_index':None,
                'independent_watch_threshold':{'value':'0.95','unit':'index','basis_ref':basis},'private_portfolio_coverage':'complete_declared_synthetic_initial_portfolio','prior_own_reviews':None,'evidence_refs':[native]}},
            {'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':point(tick),'candidates':[],'search_profile_ref':ref('Profile',tag)}}]
        visible=[r['ref'] for r in objects]
        for row in objects:
            if row['ref']['kind']=='Authorization':
                row['value'].update(validity=window,readable_refs=deepcopy(visible))
                if row['value']['organization_id']==org:row['value']['scopes']=[scope,*row['value']['scopes']]
                grants.append(deepcopy(row['value']))
        owner_grant=next(r['value'] for r in objects if r['ref']==profile['authority_ref']);function=owner_grant['function_ref']
        context={**base,'actor_id':owner['actor_id'],'function_ref':function,'authorization_refs':[owner_grant['ref']],'operation_id':tag,
            'contract_ref':ref('ActionContract','OWN-A05'),'task_ref':ref('DecisionTask',tag),'scope':scope,'business_time':point(tick),
            'read_token':tag+'-read','visible_refs':visible,'candidate_set_ref':candidate,'execution_mode':'rule'}
        schemas=OwnerMonthlyCapacityApplication.COMPONENTS['Owner'][0].SOURCE_SCHEMAS()
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']==native:value['content_hash']='0'*64
            if row['ref']==observation:value.update(actual_financing_index={'value':'1','unit':'index','basis_ref':native},prior_own_reviews=[])
            typed=schemas.validate_projection(Reference.model_validate(row['ref']),value);key=task_digest(row['ref']);digest=task_digest(typed.model_dump(mode='json'))
            if key in immutable and immutable[key]!=digest:raise ValueError('Changed immutable initial treasury source: '+str(row['ref']))
            immutable[key]=digest
        plans.append(MonthlyOwnerCapacityPlan.model_validate({'organization_id':org,'role':'Owner','tick':tick,'context':context,'action_input':inputs,
            'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    owner['assignments']+=[v for v in functions.values() if v['role']=='Owner']
    organizations=[owner]
    for bank_id in ('declared-capacity-lender','declared-capacity-second-lender'):
        organizations.append({'organization_id':bank_id,'actor_id':bank_id,'source_ids':['synthetic:initial-counterparty:'+bank_id],
            'public_description':'Declared initial private financing counterparty, not an added native agent or current finance issuer.',
            'public_location':known('HK'),'members':[],'assignments':[v for v in functions.values() if v['role']=='Bank' and ('bank-two' in v['function_ref']['id'])==(bank_id.endswith('second-lender'))],'evidence_refs':[basis]})
    # Check the same authority identities before any native execution begins.
    from src.organization.models import Organization,Authorization
    from src.organization.registry import OrganizationRegistry
    registry=OrganizationRegistry(run_id)
    for organization in organizations:registry.register(Organization.model_validate(organization))
    for grant in grants:registry.authorize(Authorization.model_validate(grant))
    authority['organization_snapshot'].update(organizations=organizations,authorizations=grants)
    source=_write(directory,'owner-monthly-capacity-input.json',{'schema_version':OwnerMonthlyCapacityApplication.INPUT_SCHEMA,'run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**source})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':{'run_id':run_id,'native_proposals':[],'native_decisions':[]}})
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    macro=read(foundation/'macro-request.json');macro.update(agents=[a for a in macro['agents'] if a['agent_id']==org],ticks=2,random_seed=42,enable_project_generation=False,
        initial_projects=[{'project_id':org+'-capacity-background','name':'Existing background project; private treasury declaration is independent',
            'project_type':'building','region':'Hong Kong','owner_id':org,'initial_budget':1000,'current_stage':'design',
            'performance':{'design_quality':0.1,'information_quality':0.1}}],
        macro_environment={**macro.get('macro_environment',{}),'financing_condition_index':financing_condition_index})
    _write(directory,'macro-request.json',SimulationCreateRequest.model_validate(macro).model_dump(mode='json'));_write(directory,'source-policy.json',policy)
    _write_launch_files(directory,assembly_hook='integration.owner_monthly_capacity:configure_assembly',readme_override=__doc__)
