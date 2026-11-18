"""One initially tendering project: original bids, signature, supply and payment handling.

Every possible buyer's private commercial views are declared before runtime.
Actual native selection alone chooses which original sources may be consumed.
"""
from copy import deepcopy
import argparse,json
from pathlib import Path

from integration.contractor_tender_formation_development import build_bundle as build_tender,configure_assembly
from integration.contractor_tender_development import _write,_write_launch_files
from integration.financing_professional_development import _merge_snapshot
from integration.supplier_order_native_development import build_bundle as build_supply
from integration.progress_payment_development import shared_initial_sources
from integration.native_lifecycle_actions import NativeLifecycleInput


def build_bundle(directory,*,run_id,with_owner_award=False,max_prior_owner_accepts=1,
        authorization_read_until_tick=None,contractor_ids=('dev-contractor-a','dev-contractor-b')):
    directory=Path(directory).resolve()
    # Keep the original sealed sub-bundle as provenance; final root is authored once.
    directory.mkdir(parents=True,exist_ok=False)
    child=directory/'tender';build_tender(child,run_id=run_id,with_owner_award=with_owner_award,
        max_prior_owner_accepts=max_prior_owner_accepts,contractor_ids=contractor_ids)
    read=lambda folder,name:json.loads((folder/name).read_bytes())
    config=read(child,'assembly-host.json');native=read(child,'native-host.json');request=read(child,'macro-request.json')
    formation=config['settings']['formation'];snapshot=deepcopy(formation['authority']['organization_snapshot'])
    initial,=request['initial_projects'];project=initial['project_id'];owner=initial['owner_id']
    buyers=sorted({p['organization_id'] for p in read(child,'contractor-formation-input.json')['plans']})
    suppliers=('actual-supplier-a','actual-supplier-b');supply_plans=[];contractor_plans=[];payment_plans=[]
    for buyer in buyers:
        folder=directory/('supply-for-'+buyer)
        build_supply(folder,run_id=run_id,with_quote=True,with_product=True,with_screening=True,with_contractor=True,
            owner_id=owner,contractor_id=buyer,supplier_ids=suppliers,clock_id='dev-clock',source_namespace=buyer,
            additional_project_windows=({'project_id':project,'tick':9,'delivery_start':10,'delivery_end':11,
                'business_money_scale':'0.1','procurement_limit':'30','require_native_award':True},))
        settings=read(folder,'assembly-host.json')['settings']
        branch=settings['authority']['organization_snapshot']
        for org in branch['organizations']:
            old=next((o for o in snapshot['organizations'] if o['organization_id']==org['organization_id']),None)
            if old is not None:org['public_location']=deepcopy(old['public_location'])
        snapshot=_merge_snapshot(snapshot,branch)
        plans=read(folder,'supplier-order-input.json')['plans']
        for plan in plans:
            if plan['project_id']==project:
                plan['contractor_id']=buyer;supply_plans.append(plan)
        contractor_plans.extend(p for p in read(folder,'contractor-supply-input.json')['plans'] if p['project_id']==project)
        for tick in [11,12]:
            branch,payment=shared_initial_sources(run_id=run_id,project_id=project,organization_snapshot=snapshot,
                owner_id=owner,contractor_id=buyer,clock_id='dev-clock',tick=tick,source_namespace=buyer,
                authorization_read_until_tick=authorization_read_until_tick)
            snapshot=_merge_snapshot(snapshot,branch)
            for plan in payment['plans']:
                plan['native_contractor_id']=buyer;payment_plans.append(plan)
        # Only Supplier profiles are adopted; no preexisting contracts or bids from this child.
        if buyer==buyers[0]:
            request['agents'].extend(a for a in read(folder,'macro-request.json')['agents'] if a['role']=='Supplier')
    authority={**formation['authority'],'organization_snapshot':snapshot}
    from src.organization.registry import OrganizationSnapshot,OrganizationRegistry
    checked=OrganizationSnapshot.model_validate(snapshot);registry=OrganizationRegistry(run_id)
    for organization in checked.organizations:registry.register(organization)
    for grant in checked.authorizations:registry.authorize(grant)
    formation['authority']=authority
    config['settings']['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']['authority']=authority
    contractor=_write(directory,'contractor-supply-input.json',{'schema_version':'contractor-supply-input.v1','run_id':run_id,'plans':contractor_plans})
    source=_write(directory,'supplier-order-input.json',{'schema_version':'supplier-order-native-input.v1','run_id':run_id,'plans':supply_plans})
    config['settings']['supplier']={'version':'1','policy_version':'actual-tender-supply-v1','authority':authority,
        **source,'contractor':{'version':'1',**contractor}}
    document=NativeLifecycleInput.model_validate({'schema_version':'native-lifecycle-actions-input.v1',
        'run_id':run_id,'source_declaration':'independent_inputs_not_native_execution_proof',
        'plans':payment_plans})
    payment_file=_write(directory,'lifecycle-input.json',document.model_dump(mode='json'))
    config['settings']['lifecycle']={'version':'1','policy_version':'actual-tender-payment-positions-v1',**payment_file}
    request['ticks']=12
    # A tender-stage initial project has prior design inputs. This is an
    # explicit independent scenario assumption, never a runtime quality result.
    initial['performance']['design_quality']=0.9
    for agent in request['agents']:
        if agent['role']=='Supplier':agent.update(financial_capacity=1,management_capability=1)
    native['settings'].update(micro_supplier_order_scope=True,micro_contractor_supply_scope=True)
    for role in ['Supplier']:
        native['settings']['native_proposals'].append({'role':role,'operation':'decide_monthly_operation'})
        native['settings']['native_decisions'].append({'role':role,'decision_type':'monthly_enterprise_operation'})
    _write(directory,'macro-request.json',request);_write(directory,'native-host.json',native);_write(directory,'assembly-host.json',config)
    _write(directory,'initial-business-sources.json',{'possible_buyers':buyers,'project_id':project,
        'supply_tick':9,'payment_position_ticks':[11,12],'supplier_price_HKD':'20','independent_procurement_limit_HKD':'30',
        'initial_design_quality':0.9,'initial_design_quality_source':'independent_synthetic_tender_stage_assumption',
        'future_submission_or_selection_or_signature_predeclared':False})
    _write_launch_files(directory,assembly_hook='integration.contractor_tender_formation_development:configure_assembly',
        readme_override=__doc__)
    return {'status':'initial-tender-fulfillment-sources-unverified','run_id':run_id,'possible_buyers':buyers}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--run-id',required=True)
    p.add_argument('--with-owner-award',action='store_true')
    p.add_argument('--max-prior-owner-accepts',type=int,default=1)
    args=p.parse_args(argv);print(json.dumps(build_bundle(args.output,run_id=args.run_id,
        with_owner_award=args.with_owner_award,max_prior_owner_accepts=args.max_prior_owner_accepts)))


if __name__=='__main__':main()
