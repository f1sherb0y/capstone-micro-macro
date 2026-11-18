"""Declare complete native tender-to-closeout and original private settlement consumers.

Independent future communication inputs are not debts, cash or native outcomes.
Reviewer assignment and approval can use the original micro Government workers;
the native lifecycle retains ownership of actual completion and settlement.
"""
from copy import deepcopy
import argparse,json
from pathlib import Path

from integration.tender_fulfillment_development import build_bundle as build_fulfillment
from integration.contractor_tender_formation_development import configure_assembly
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.financing_professional_development import _merge_snapshot
from integration.final_account_discussion_development import shared_initial_sources
from integration.final_account_learning_development import add_settlement_learning
from integration.progress_payment_development import shared_initial_sources as payment_sources
from integration.native_lifecycle_actions import NativeLifecycleInput
from src.organization.registry import OrganizationSnapshot,OrganizationRegistry


def build_bundle(directory,*,run_id,review_ticks=(21,22,23,24),with_owner_award=False,max_prior_owner_accepts=1,
        with_government_completion=False,authorization_read_until_tick=None,
        contractor_ids=('dev-contractor-a','dev-contractor-b')):
    ticks=tuple(review_ticks)
    if not ticks or any(type(t) is not int or t<13 for t in ticks) or ticks!=tuple(sorted(set(ticks))):
        raise ValueError('Closeout review windows must be distinct increasing initial ticks after procurement/payment')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    child=directory/'fulfillment';build_fulfillment(child,run_id=run_id,with_owner_award=with_owner_award,
        max_prior_owner_accepts=max_prior_owner_accepts,
        authorization_read_until_tick=authorization_read_until_tick,contractor_ids=contractor_ids)
    read=lambda n:json.loads((child/n).read_bytes())
    request=read('macro-request.json');native=read('native-host.json');config=read('assembly-host.json')
    settings=config['settings'];formation=settings['formation'];authority=formation['authority']
    snapshot=deepcopy(authority['organization_snapshot'])
    project,=request['initial_projects'];owner=project['owner_id'];qs=project['selected_qs_id']
    buyers=read('initial-business-sources.json')['possible_buyers']
    document=json.loads(Path(settings['lifecycle']['file_path']).read_bytes())
    for buyer in buyers:
        # Latest declared review tick requires construction to have ended by
        # tick max(ticks)-4 in the unchanged native stage sequence.
        for tick in range(13,max(ticks)-3):
            branch,plans=payment_sources(run_id=run_id,project_id=project['project_id'],organization_snapshot=snapshot,
                owner_id=owner,contractor_id=buyer,clock_id='dev-clock',tick=tick,source_namespace=buyer,
                authorization_read_until_tick=authorization_read_until_tick)
            for plan in plans['plans']:plan['native_contractor_id']=buyer
            snapshot=_merge_snapshot(snapshot,branch);document['plans'].extend(plans['plans'])
        for tick in ticks:
            namespace=buyer+'-t'+str(tick)
            branch,plans,_=shared_initial_sources(run_id=run_id,project_id=project['project_id'],organization_snapshot=snapshot,
                owner_id=owner,contractor_id=buyer,qs_id=qs,clock_id='dev-clock',with_owner_response=True,
                with_contractor_response=True,review_tick=tick,source_namespace=namespace)
            branch,plans=add_settlement_learning(snapshot=branch,document=plans)
            for plan in plans['plans']:plan['native_contractor_id']=buyer
            snapshot=_merge_snapshot(snapshot,branch)
            document['plans'].extend(plans['plans'])
    from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
    government=EnterpriseAgentProfile(agent_id='actual-closeout-government',name='Independent native completion reviewer',
        role='Government',region='Hong Kong',enterprise_type='regulator',
        management_capability=1,policy_adaptability=1,supervision_capability=1)
    government_basis=ref('Evidence','actual-closeout-government-initial-profile')
    snapshot['organizations'].append({'organization_id':government.agent_id,'actor_id':government.agent_id,
        'source_ids':['synthetic:initial-native-completion-government'],
        'public_description':'Independent initial native Government profile; no micro action or approval is predeclared.',
        'public_location':known(government.region),'members':[],'evidence_refs':[government_basis],
        'assignments':[{'role':'Government','function_ref':ref('FunctionAssignment','actual-closeout-government-native-review'),
            'configuration_version':'1','basis_refs':[government_basis]}]})
    if with_government_completion:
        from integration.government_intake_development import build_bundle as build_regulatory_sources
        regulatory=build_regulatory_sources(directory/'government-sources',run_id=run_id,
            with_approval=True,completion=True,with_feedback=True,sources_only=True,
            owner_id=owner,agency_ids=(government.agent_id,),clock_id='dev-clock',
            owner_function_id=owner+'-closeout-regulatory-function',
            organization_locations={owner:next(o['public_location'] for o in snapshot['organizations']
                if o['organization_id']==owner)},
            project_ids=(project['project_id'],),intake_ticks=(20,),approval_ticks=(22,))
        settings['government']=regulatory['settings']
        snapshot=_merge_snapshot(snapshot,regulatory['settings']['authority']['organization_snapshot'])
    checked=OrganizationSnapshot.model_validate(snapshot);registry=OrganizationRegistry(run_id)
    for org in checked.organizations:registry.register(org)
    for grant in checked.authorizations:registry.authorize(grant)
    authority={**authority,'organization_snapshot':snapshot}
    formation['authority']=authority;settings['supplier']['authority']=authority
    if with_government_completion:settings['government']['authority']=authority
    settings['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']['authority']=authority
    document=NativeLifecycleInput.model_validate(document)
    settings['lifecycle'].update(_write(directory,'lifecycle-input.json',document.model_dump(mode='json')))
    request['agents'].append(government.model_dump(mode='json'))
    request['ticks']=max(ticks)+2
    for operation in (['decide_monthly_operation'] if with_government_completion
            else ['decide_monthly_operation','consider_review_assignment','decide_approval']):
        native['settings']['native_proposals'].append({'role':'Government','operation':operation})
    for kind in (['monthly_enterprise_operation'] if with_government_completion
            else ['monthly_enterprise_operation','government_review_assignment','government_completion_approval']):
        native['settings']['native_decisions'].append({'role':'Government','decision_type':kind})
    if with_government_completion:
        native['settings'].update(micro_government_intake_scope=True,micro_government_approval_scope=True,
            native_government_approval_transport=False)
    _write(directory,'macro-request.json',request);_write(directory,'native-host.json',native);_write(directory,'assembly-host.json',config)
    _write(directory,'initial-closeout-sources.json',{'project_id':project['project_id'],'possible_buyers':buyers,
        'review_ticks':ticks,'payment_ticks':list(range(11,max(ticks)-3)),
        'government_behavior':'original_micro_intake_review_decision' if with_government_completion else 'original_native_rules',
        'government_initial_windows':{'assignment_tick':20,'approval_ticks':[22]} if with_government_completion else None,
        'government_material_boundary':'Independent initial received synthetic document, case, rules and authority; no physical inspection or detailed permit inferred.',
        'source_declaration':'independent_inputs_not_native_execution_proof',
        'government_identity_source':{'ref':government_basis,'profile':government.model_dump(mode='json')},
        'new_initial_final_account_project_created':False,'future_completion_or_settlement_predeclared':False})
    description=__doc__+('\nOriginal GOV-A02/A12/A04/A07 use independent initial received document, case, rules and authority. '
        'The declared assignment/approval windows do not prove execution; no physical inspection or detailed permit is inferred.\n'
        if with_government_completion else '\nGovernment assignment and approval use original native rules.\n')
    _write_launch_files(directory,assembly_hook='integration.contractor_tender_formation_development:configure_assembly',readme_override=description)
    return {'status':'initial-tender-closeout-sources-unverified','run_id':run_id,'review_ticks':ticks}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--run-id',required=True)
    p.add_argument('--with-owner-award',action='store_true')
    p.add_argument('--max-prior-owner-accepts',type=int,default=1)
    p.add_argument('--with-government-completion',action='store_true')
    args=p.parse_args(argv);print(json.dumps(build_bundle(args.output,run_id=args.run_id,
        with_owner_award=args.with_owner_award,max_prior_owner_accepts=args.max_prior_owner_accepts,
        with_government_completion=args.with_government_completion)))


if __name__=='__main__':main()
