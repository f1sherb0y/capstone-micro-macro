"""Declare independent public screening facts before original monthly requests."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.contractor_monthly_native import ContractorMonthlyPlan
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
from integration.verify_tender_closed_loop import ROOT
from src.actions.contracts.common import Reference


def build_bundle(directory,*,run_id,market_demand_index=1.2,ticks=2):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    source=ROOT/'tests/fixtures/roles/contractor_screening.v1.json';original=json.loads(source.read_bytes())
    clock=ref('ClockProfile','fixture-clock');basis_source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    organizations=[];grants=[];plans=[]
    for organization in ('monthly-contractor-a','monthly-contractor-b'):
        actor=organization+'-actor';assignments=[]
        for tick in range(1,ticks+1):
            tag=organization+'-'+str(tick)
            def bind(value):
                if isinstance(value,list):return [bind(v) for v in value]
                if isinstance(value,dict):
                    if set(value)=={'kind','id','version'}:
                        if value['kind']=='ClockProfile':return deepcopy(value)
                        identity=organization if value['id']=='fixture-contractor' else 'monthly-owner' if value['id']=='fixture-owner' else organization+'-'+value['id']
                        return {**value,'id':identity,'version':'monthly-'+str(tick)}
                    result={k:bind(v) for k,v in value.items()}
                    if set(value)=={'clock_ref','offset'} and value['offset']==1:result['offset']=tick
                    return result
                return actor if value=='fixture-contractor-actor' else value
            objects=bind([r for r in original['objects'] if r['ref']['kind'] not in {'Invitation','Requirement'}]);inputs=bind(original['input'])
            scope=next(r['value']['scope'] for r in objects if r['ref']['kind']=='ProcurementPackage')
            now={'clock_ref':clock,'offset':tick};validity={'start':{'clock_ref':clock,'offset':0},'end':{'clock_ref':clock,'offset':100},'bounds':'closed_open'}
            basis=bind(ref('Evidence','synthetic-basis'));native=ref('Evidence',tag+'-native');observation=ref('OutreachObservation',tag)
            function=ref('FunctionAssignment',tag);grant_ref=ref('Authorization',tag);candidates=ref('CandidateSet',tag)
            def put(reference,**fields):objects.append({'ref':reference,'value':{'ref':reference,**fields}})
            put(basis,source_kind='synthetic',basis_kind='assumed',locator='independent-initial-contractor-public-dossier-and-private-disclosures',content_hash=basis_source_hash,effective_window=validity)
            put(native,source_kind='synthetic',basis_kind='observed',locator='actual-native-monthly-input-and-own-earlier-results',content_hash=None,effective_window=validity)
            put(observation,organization_id=organization,scope=scope,as_of=now,market_demand=None,prior_outreach_count=None,evidence_refs=[native])
            profile=next(r['value'] for r in objects if r['ref']['kind']=='OpportunityScreeningProfile')
            profile['outreach_limits']={'observation_ref':observation,'minimum_market_demand':{'value':'1','unit':'index','basis_ref':basis},'maximum_prior_outreach':1}
            profile['evidence_refs'].append(native)
            objects.append({'ref':candidates,'value':{'operation_id':tag,'scope':scope,'as_of':now,
                'candidates':[{'ref':inputs['package_ref'],'permitted_choices':['participate','decline','clarify']}],
                'search_profile_ref':ref('Profile',tag)}})
            visible=[row['ref'] for row in objects]
            context={'run_id':run_id,'actor_id':actor,'function_ref':function,'authorization_refs':[grant_ref],
                'operation_id':tag,'contract_ref':ref('ActionContract','CONTRACTOR-A01'),'task_ref':ref('DecisionTask',tag),
                'scope':scope,'business_time':now,'read_token':tag+'-read','visible_refs':visible,'candidate_set_ref':candidates,'execution_mode':'rule'}
            grants.append({'ref':grant_ref,'organization_id':organization,'actor_id':actor,'function_ref':function,'action_ids':['CONTRACTOR-A01'],
                'scopes':[scope],'readable_refs':visible,'tool_ids':[],'basis_refs':[basis],'validity':validity})
            assignments.append({'role':'Contractor','function_ref':function,'configuration_version':'1','basis_refs':[basis]})
            for row in objects:
                value=deepcopy(row['value'])
                if row['ref']==native:value['content_hash']='0'*64
                if row['ref']==observation:value.update(market_demand={'value':'0','unit':'index','basis_ref':native},prior_outreach_count=0)
                gba_contractor_screening_source_schemas().validate_projection(Reference.model_validate(row['ref']),value)
            plans.append(ContractorMonthlyPlan.model_validate({'organization_id':organization,'role':'Contractor','tick':tick,
                'context':context,'action_input':inputs,'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
        organizations.append({'organization_id':organization,'actor_id':actor,'source_ids':['synthetic:monthly-screening:'+organization],
            'public_description':'Explicit initial synthetic public dossier and independent current qualification/resource/commitment disclosures, not a real bid or macro-derived physical stock.',
            'public_location':{'state':'known','value':'Hong Kong'},'members':[],'evidence_refs':assignments[0]['basis_refs'],'assignments':assignments})
    organizations.append({'organization_id':'monthly-owner','actor_id':'monthly-owner-actor','source_ids':['synthetic:monthly-owner'],
        'public_description':'Original aggregate initial case owner; no formal money clearance inferred.','public_location':{'state':'known','value':'Hong Kong'},'members':[],
        'evidence_refs':[ref('Evidence','monthly-owner-assumptions')],
        'assignments':[{'role':'Owner','function_ref':ref('FunctionAssignment','monthly-owner-function'),'configuration_version':'1','basis_refs':[ref('Evidence','monthly-owner-assumptions')]}]})
    sources=_write(directory,'contractor-monthly-input.json',{'schema_version':'contractor-monthly-input.v1','run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':{'runtime_id':run_id,'version':'1','organization_snapshot':{
        'schema_version':'organization.v2','run_id':run_id,'organizations':organizations,'authorizations':grants}},**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':{'run_id':run_id,'native_proposals':[{'role':'Owner','operation':'decide_monthly_operation'}],
            'native_decisions':[{'role':'Owner','decision_type':'monthly_enterprise_operation'}]}})
    from integration.bootstrap import enable_gba_imports
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    macro=SimulationCreateRequest.model_validate({'agent_source':'explicit','ticks':ticks,'random_seed':42,'enable_project_generation':False,'use_prior_network_edges':False,
        'macro_environment':{'market_demand_index':market_demand_index},'agents':[{'agent_id':o['organization_id'],'name':o['organization_id'],
            'role':'Owner' if o['organization_id']=='monthly-owner' else 'Contractor','region':'Hong Kong','enterprise_type':'explicit_synthetic','total_resource_capacity':10} for o in organizations],
        'initial_projects':[{'project_id':'monthly-final-account','name':'Independent initial aggregate final-account case','project_type':'building','region':'Hong Kong',
            'owner_id':'monthly-owner','initial_budget':1000,'current_stage':'final_account'}]})
    _write(directory,'macro-request.json',macro.model_dump(mode='json'))
    _write_launch_files(directory,assembly_hook='integration.contractor_monthly_native:configure_assembly',readme_override=__doc__)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--market-demand-index',type=float,default=1.2);a=p.parse_args(argv);build_bundle(a.output,run_id=a.run_id,market_demand_index=a.market_demand_index)


if __name__=='__main__':main()
