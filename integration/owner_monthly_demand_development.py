"""Declare an Owner mandate for global demand analysis; bind only actual observations."""
from copy import deepcopy
from pathlib import Path
from integration.professional_monthly_development import build_bundle as monthly_foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.owner_monthly_demand import MonthlyOwnerDemandPlan,OwnerMonthlyDemandApplication
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest
from src.actions.registry import ActionRegistry
from src.actions.processors import register_representative_processors


def build_bundle(directory,*,run_id,market_demand_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'monthly-foundation';monthly_foundation(foundation,run_id=run_id,ticks=2)
    authority=read(foundation/'assembly-host.json')['settings']['authority'];document=read(foundation/'professional-monthly-input.json')
    owner,=[o for o in authority['organization_snapshot']['organizations'] if o['organization_id']=='professional-owner']
    plans=[];grants=[];contract=register_representative_processors(ActionRegistry()).get('OWN-A01').contract
    for tick in (1,2):
        context=deepcopy(next(p['context'] for p in document['plans'] if p['tick']==tick));org=owner['organization_id'];tag=org+'-monthly-demand-'+str(tick)
        rr=lambda kind:ref(kind,tag)
        scope={'kind':'organization','ref':ref('Organization',org,'monthly-demand-'+str(tick)),'coverage_refs':[]}
        basis=ref('Evidence',tag+'-mandate');native=ref('Evidence',tag+'-actual-observation');function=rr('FunctionAssignment');grant_ref=rr('Authorization')
        now=context['business_time'];window={'start':{**now,'offset':1},'end':{**now,'offset':3},'bounds':'closed_open'}
        assignment={'role':'Owner','function_ref':function,'configuration_version':'1','basis_refs':[basis]};owner['assignments'].append(deepcopy(assignment))
        context.update(actor_id=owner['actor_id'],function_ref=function,authorization_refs=[grant_ref],operation_id=tag,
            contract_ref=ref('ActionContract','OWN-A01'),task_ref=rr('DecisionTask'),scope=scope,read_token=tag+'-read',candidate_set_ref=rr('CandidateSet'))
        objective,capacity,signal,source,observation=map(rr,['OwnerObjective','ManagementCapacity','DemandObservation','Observation','MonthlyOwnerDemandObservation'])
        policy={'organization_id':org,'scope':'simulation-global demand analysis only','threshold':'1','threshold_unit':'index',
            'screening_requirement':'0.1','capacity_unit':'native_resource','research_permitted':True,
            'private_case_and_finance_history_coverage':'unknown','formal_case_or_project_commitment_authorized':False}
        objects=[]
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**value}})
        add(basis,{'source_kind':'synthetic','basis_kind':'assumed','locator':'independently-declared-private-owner-global-demand-analysis-mandate',
            'content_hash':task_digest(policy),'effective_window':window})
        add(native,{'source_kind':'synthetic','basis_kind':'observed','locator':'actual-current-native-monthly-request-profile-and-earlier-confirmed-own-analysis',
            'content_hash':None,'effective_window':window})
        objects.append({'ref':function,'value':assignment});add(scope['ref'],{'evidence_refs':[basis]})
        add(objective,{'organization_id':org,'template':'investment_return','effective_window':window,'evidence_refs':[basis],
            'allowed_region_ids':known(['simulation_global']),'allowed_use_codes':known(['background_portfolio_demand']),
            'signal_rules':known([{'signal_code':'native_global_market_demand_index','comparison':'at_least',
                'threshold':{'value':'1','unit':'index','basis_ref':basis}}]),'maximum_observation_age':known(0),
            'new_signal_choice':known('propose'),'allow_reopen':known(False),'monthly_demand_observation_ref':observation})
        add(capacity,{'organization_id':org,'effective_window':window,'evidence_refs':[native,basis],'total':None,
            'screening_requirement':known({'value':'0.1','unit':'native_resource','basis_ref':basis}),'commitments':[]})
        add(source,{'evidence_refs':[native],'demand_ref':signal})
        add(signal,{'evidence_refs':[native,basis],'source_ref':source,'region_id':'simulation_global','use_code':'background_portfolio_demand',
            'signal_code':'native_global_market_demand_index','measure':None,'research_permitted':known(True),'observed_at':now,'learned_at':now,'effective_window':window})
        add(observation,{'organization_id':org,'scope':scope,'as_of':now,'current_market_index':None,'native_available_resource':None,
            'prior_own_outcomes':None,'private_case_and_finance_history_coverage':'unknown','evidence_refs':[native]})
        objects.append({'ref':context['candidate_set_ref'],'value':{'operation_id':tag,'scope':scope,'as_of':now,
            'candidates':[{'ref':source,'permitted_choices':['propose']}],'search_profile_ref':rr('Profile')}})
        grant={'ref':grant_ref,'organization_id':org,'actor_id':owner['actor_id'],'function_ref':function,'action_ids':['OWN-A01'],
            'scopes':[scope],'validity':window,'readable_refs':[],'tool_ids':[],'basis_refs':[basis]}
        objects.append({'ref':grant_ref,'value':grant});grant['readable_refs']=[r['ref'] for r in objects]
        context['visible_refs']=deepcopy(grant['readable_refs']);grants.append(deepcopy(grant))
        action_input={'scope_ref':scope,'objective_ref':objective,'observations':[signal],'opportunity_refs':[],'existing_case_refs':[],'capacity_ref':capacity}
        contract.validate_input(action_input)
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']==native:value['content_hash']='0'*64
            if row['ref']==signal:value['measure']=known({'value':'1','unit':'index','basis_ref':native})
            if row['ref']==capacity:value['total']=known({'value':'0','unit':'native_resource','basis_ref':native})
            if row['ref']==observation:value.update(current_market_index={'value':'1','unit':'index','basis_ref':native},
                native_available_resource={'value':'0','unit':'native_resource','basis_ref':native},prior_own_outcomes=[])
            OwnerMonthlyDemandApplication.COMPONENTS['Owner'][0].SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
        plans.append(MonthlyOwnerDemandPlan.model_validate({'organization_id':org,'role':'Owner','tick':tick,'context':context,'action_input':action_input,
            'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    authority['organization_snapshot']['authorizations']=grants
    sources=_write(directory,'owner-monthly-demand-input.json',{'schema_version':OwnerMonthlyDemandApplication.INPUT_SCHEMA,'run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    native=read(foundation/'native-host.json')
    for field,operation in [('native_proposals','decide_monthly_operation'),('native_decisions','monthly_enterprise_operation')]:
        native['settings'][field]=[{'role':role,'operation' if field=='native_proposals' else 'decision_type':operation} for role in ('Architect','Engineer','QS')]
    _write(directory,'native-host.json',native)
    macro=read(foundation/'macro-request.json');macro['macro_environment']['market_demand_index']=market_demand_index
    macro['initial_projects'][0].update(project_id='owner-monthly-demand-background',current_stage='design',
        name='Initial unappointed design background; no detailed project work claimed')
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.owner_monthly_demand:configure_assembly',readme_override=__doc__)
