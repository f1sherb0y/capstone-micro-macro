"""Fixed original monthly scenario with independently declared professional dossiers."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.professional_intake_development import build_bundle as build_foundation
from integration.professional_monthly_native import ProfessionalMonthlyPlan,ProfessionalMonthlySettings,COMPONENTS
from src.coordination.tasks import task_digest
from src.actions.contracts.common import Reference,walk_references


def build_bundle(directory,*,run_id,market_demand_index=1.2,minimum_market_demand='1',maximum_prior_outreach=1,ticks=2):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'foundation';build_foundation(foundation,run_id=run_id,with_opportunity=True)
    read=lambda name:json.loads((foundation/name).read_bytes())
    original_settings=read('assembly-host.json')['settings']
    original=json.loads(Path(original_settings['file_path']).read_bytes());authority=original_settings['authority']
    organizations={o['organization_id']:o for o in authority['organization_snapshot']['organizations']}
    monthly=[];grants=[];immutable_sources={}
    for role in COMPONENTS:
        original_plan=next(p for p in original['plans'] if p['role']==role and p['tick']==1)
        organization=original_plan['organization_id'];source=original_plan['opportunity'];old_tick=source['context']['business_time']['offset']
        for tick in range(1,ticks+1):
            tag=organization+'-monthly-'+str(tick)
            def bind(value):
                if isinstance(value,list):return [bind(v) for v in value]
                if isinstance(value,dict):
                    if set(value)=={'kind','id','version'}:
                        return deepcopy(value) if value['kind'] in {'ClockProfile','ActionContract'} else {**value,'version':'monthly-'+str(tick)}
                    result={k:bind(v) for k,v in value.items()}
                    if set(value)=={'clock_ref','offset'} and value['offset']==old_tick:result['offset']=tick
                    return result
                return value
            step=bind(source);context=step['context'];scope={'kind':'organization','ref':{**ref('Organization',organization),'version':'monthly-'+str(tick)},'coverage_refs':[]}
            def scopes(value):
                if isinstance(value,list):return [scopes(v) for v in value]
                if isinstance(value,dict):
                    if set(value)=={'kind','ref','coverage_refs'}:return deepcopy(scope)
                    return {k:scopes(v) for k,v in value.items()}
                return value
            step=scopes(step);context=step['context'];context.update(operation_id=tag,read_token=tag+'-read',task_ref=ref('DecisionTask',tag),candidate_set_ref=ref('CandidateSet',tag))
            objects=step['objects'];native=step['native_evidence_ref'];observation=ref('OutreachObservation',tag)
            original_clock=next(row for row in source['objects'] if row['ref']['kind']=='ClockProfile')
            for index,row in enumerate(objects):
                if row['ref']['kind']=='ClockProfile':objects[index]=deepcopy(original_clock)
            for basis_ref in original_clock['value']['evidence_refs']:
                objects.append(deepcopy(next(row for row in source['objects'] if row['ref']==basis_ref)))
            policy_ref=step['action_input']['capability_ref' if role=='Engineer' else 'strategy_ref']
            policy=next(o['value'] for o in objects if o['ref']==policy_ref)
            basis=next(o['ref'] for o in objects if o['ref']['kind']=='Evidence' and o['value']['content_hash'] is not None)
            objects.append({'ref':deepcopy(scope['ref']),'value':{'ref':deepcopy(scope['ref']),'evidence_refs':[basis]}})
            policy['outreach_limits']={'observation_ref':observation,'minimum_market_demand':{'value':str(minimum_market_demand),'unit':'index','basis_ref':basis},'maximum_prior_outreach':maximum_prior_outreach}
            objects.append({'ref':observation,'value':{'ref':observation,'organization_id':organization,'scope':deepcopy(scope),
                'as_of':deepcopy(context['business_time']),'market_demand':None,'prior_outreach_count':None,'evidence_refs':[native]}})
            for row in objects:
                if row['ref']['kind']=='CandidateSet':
                    row['ref']=deepcopy(context['candidate_set_ref']);row['value']['operation_id']=tag
                if row['ref']==native:row['value'].update(locator='actual-current-native-monthly-input-and-own-earlier-outcomes',content_hash=None)
            visible=[r['ref'] for r in objects];context['visible_refs']=deepcopy(visible)
            grant=next(o['value'] for o in objects if o['ref'] in context['authorization_refs'])
            grant.update(action_ids=[role.upper()+'-A01'],scopes=[deepcopy(scope)],readable_refs=deepcopy(visible));grants.append(deepcopy(grant))
            assignment=next(o['value'] for o in objects if o['ref']==context['function_ref'])
            organizations[organization]['assignments'].append(deepcopy(assignment))
            for row in objects:
                value=deepcopy(row['value'])
                if row['ref']==native:value['content_hash']='0'*64
                if row['ref']==observation:value.update(market_demand={'value':'0','unit':'index','basis_ref':native},prior_outreach_count=0)
                COMPONENTS[role][0].SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
                key=task_digest([organization,row['ref']]);digest=task_digest(value)
                if key in immutable_sources and immutable_sources[key]!=digest:
                    raise ValueError('Monthly scenario changes a source under its original immutable reference version')
                immutable_sources[key]=digest
            from src.actions.registry import ActionRegistry
            from src.actions.processors import register_representative_processors
            action=register_representative_processors(ActionRegistry()).get(role.upper()+'-A01').contract.validate_input(step['action_input'])
            if any(reference.model_dump(mode='json') not in visible for reference in walk_references(action)):
                raise ValueError('Monthly original A01 input references are not fully declared before execution')
            monthly.append(ProfessionalMonthlyPlan.model_validate({'organization_id':organization,'role':role,'tick':tick,
                'context':context,'action_input':step['action_input'],'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    authority['organization_snapshot'].update(organizations=list(organizations.values()),authorizations=grants)
    sources=_write(directory,'professional-monthly-input.json',{'schema_version':'professional-monthly-input.v1','run_id':run_id,'plans':monthly})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':{'run_id':run_id,'native_proposals':[{'role':'Owner','operation':'decide_monthly_operation'}],
            'native_decisions':[{'role':'Owner','decision_type':'monthly_enterprise_operation'}]}})
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    macro=read('macro-request.json');macro.update(ticks=ticks,random_seed=42,enable_project_generation=False,
        initial_projects=[{'project_id':'monthly-final-account','name':'Initial aggregate final-account case; not detailed clearance proof','project_type':'building','region':'Hong Kong',
            'owner_id':'professional-owner','initial_budget':1000,'current_stage':'final_account'}],
        macro_environment={**macro.get('macro_environment',{}),'market_demand_index':market_demand_index})
    _write(directory,'macro-request.json',SimulationCreateRequest.model_validate(macro).model_dump(mode='json'))
    _write_launch_files(directory,assembly_hook='integration.professional_monthly_native:configure_assembly',readme_override=__doc__)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--market-demand-index',type=float,default=1.2);p.add_argument('--minimum-market-demand',default='1');p.add_argument('--maximum-prior-outreach',type=int,default=1)
    a=p.parse_args(argv);build_bundle(a.output,run_id=a.run_id,market_demand_index=a.market_demand_index,minimum_market_demand=a.minimum_market_demand,maximum_prior_outreach=a.maximum_prior_outreach)


if __name__=='__main__':main()
