"""Native new tender through closure, then actual Owner consumes its settlement.

Independent initial assessment sources retain cash and unresolved obligations.
Only the frozen native project generator supplies the later opportunity.
"""
from copy import deepcopy
import argparse,json
from pathlib import Path

from integration.tender_closeout_development import build_bundle as build_closeout
from integration.contractor_tender_formation_development import configure_assembly
from integration.owner_opportunity_native_development import build_bundle as build_opportunity
from integration.owner_opportunity_native import OwnerOpportunitySettings
from integration.contractor_tender_development import _write,_write_launch_files
from src.organization.registry import OrganizationSnapshot,OrganizationRegistry


def build_bundle(directory,*,run_id,with_owner_award=False,max_prior_owner_accepts=1,with_government_completion=False,
        authorization_read_until_tick=None):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    child=directory/'closeout';build_closeout(child,run_id=run_id,with_owner_award=with_owner_award,
        max_prior_owner_accepts=max_prior_owner_accepts,with_government_completion=with_government_completion,
        authorization_read_until_tick=authorization_read_until_tick)
    followup=directory/'opportunity';build_opportunity(followup,run_id=run_id,
        max_prior_initiations=999,max_prior_final_accounts=1)
    read=lambda folder,name:json.loads((folder/name).read_bytes())
    request=read(child,'macro-request.json');native=read(child,'native-host.json');config=read(child,'assembly-host.json')
    settings=config['settings'];authority=deepcopy(settings['formation']['authority'])
    snapshot=authority['organization_snapshot'];project,=request['initial_projects']
    independent=read(followup,'assembly-host.json')['settings']
    # Adopt this independent professional author, without the child's projects,
    # other organizations, native decisions, roles or any live execution result.
    architect='finance-architect'
    organization=next(o for o in independent['authority']['organization_snapshot']['organizations'] if o['organization_id']==architect)
    snapshot['organizations'].append(deepcopy(organization))
    request['agents'].append(next(a for a in read(followup,'macro-request.json')['agents'] if a['agent_id']==architect))
    document=read(followup,'owner-opportunity-input.json')
    policy,=document['policies'];policy.update(organization_id=project['owner_id'],
        cost_organization_id=project['selected_qs_id'],schedule_organization_id=architect)
    source=_write(directory,'owner-opportunity-input.json',document)
    settings['opportunity']=OwnerOpportunitySettings.model_validate({**independent,**source,'authority':authority}).model_dump(mode='json')
    checked=OrganizationSnapshot.model_validate(snapshot);registry=OrganizationRegistry(run_id)
    for org in checked.organizations:registry.register(org)
    for grant in checked.authorizations:registry.authorize(grant)
    settings['formation']['authority']=authority;settings['supplier']['authority']=authority
    if with_government_completion:settings['government']['authority']=authority
    settings['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']['authority']=authority
    # Original max_active_projects excludes closed projects. Therefore no new
    # candidate is generated while this original tender is still active.
    # Match the existing supplied-agent generation path, whose original
    # validator forbids generation under agent_source='explicit'.
    request.update(agent_source='default',enable_project_generation=True,target_project_count=2,max_active_projects=1,ticks=25)
    routes=native['settings'];routes['micro_owner_opportunity_scope']=True
    routes['native_proposals']=[r for r in routes['native_proposals'] if (r['role'],r['operation'])!=('Owner','evaluate_project_opportunity')]
    routes['native_decisions']=[r for r in routes['native_decisions'] if (r['role'],r['decision_type']) not in
        {('Owner','owner_project_opportunity'),('Owner','owner_project_initiation')}]
    routes['native_proposals'].append({'role':'Architect','operation':'decide_monthly_operation'})
    routes['native_decisions'].append({'role':'Architect','decision_type':'monthly_enterprise_operation'})
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    request=SimulationCreateRequest.model_validate(request).model_dump(mode='json')
    _write(directory,'macro-request.json',request);_write(directory,'native-host.json',native);_write(directory,'assembly-host.json',config)
    _write(directory,'initial-followup-sources.json',{'project_id':project['project_id'],'native_max_active_projects':1,
        'max_prior_final_accounts':1,'initial_native_projects':1,'future_opportunity_or_settlement_predeclared':False,
        'private_funding_after_settlement':'Original independent assessment cash; never increased by aggregate settlement.',
        'schedule_author_organization_id':architect,'source_declaration':'independent_inputs_not_native_execution_proof'})
    _write_launch_files(directory,assembly_hook='integration.contractor_tender_formation_development:configure_assembly',
        allow_native_project_generation=True,allow_native_initial_projects_with_generation=True,readme_override=__doc__)
    return {'status':'initial-tender-closeout-followup-sources-unverified','run_id':run_id}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--run-id',required=True)
    p.add_argument('--with-owner-award',action='store_true')
    p.add_argument('--max-prior-owner-accepts',type=int,default=1)
    p.add_argument('--with-government-completion',action='store_true')
    args=p.parse_args(argv);print(json.dumps(build_bundle(args.output,run_id=args.run_id,
        with_owner_award=args.with_owner_award,max_prior_owner_accepts=args.max_prior_owner_accepts,
        with_government_completion=args.with_government_completion)))


if __name__=='__main__':main()
