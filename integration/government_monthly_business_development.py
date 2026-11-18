"""Extend the existing regulatory scenario with independent monthly mandates."""
import argparse
from copy import deepcopy
from pathlib import Path
from integration.government_intake_development import build_bundle as build_regulatory_bundle
from integration.government_monthly_native import GovernmentMonthlyPlan
from integration.government_intake_native import GovernmentIntakeSettings
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.actions.contracts.government_feedback_objects import government_feedback_schemas


def build_bundle(directory,*,run_id,market_demand_index=1.2):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'foundation'
    build_regulatory_bundle(foundation,run_id=run_id,with_approval=True,with_feedback=True,with_monthly_feedback=True,
        completion=True,revision_first=True,monthly_feedback_ticks=(1,2,3,4),clock_id='government-monthly-clock')
    host=read(foundation/'assembly-host.json');settings=host['settings']
    document=read(foundation/'government-monthly-input.json')
    for plan in document['plans']:
        feedback=plan['feedback'];context=feedback['context'];objects=feedback['objects'];org=plan['organization_id']
        profile=next(r['value'] for r in objects if r['ref']==feedback['action_input']['observation_profile_ref'])
        basis=next(r['value'] for r in objects if r['ref']==context['function_ref'])['basis_refs'][0]
        window=next(r['value']['effective_window'] for r in objects if r['ref']==basis)
        tag=org+'-monthly-'+str(plan['tick']);policy=ref('MonthlyRegulatoryPolicy',tag);observation=ref('MonthlyRegulatoryObservation',tag)
        profile.update(monthly_policy_ref=policy,monthly_observation_ref=observation)
        objects.extend([{'ref':policy,'value':{'ref':policy,'organization_id':org,'scope':context['scope'],
            'actor_id':context['actor_id'],'function_ref':context['function_ref'],'authority_ref':context['authorization_refs'][0],
            'effective_window':window,'allowed_operations':['adjust_regulatory_focus','monitor_compliance','publish_guidelines','review_policy_feedback'],
            'minimum_demand_for_focus':{'value':'1','unit':'index','basis_ref':basis},'maximum_focus_operations':1,'maximum_guidance_operations':1,
            'guidance_principles':['An aggregate approval opinion is not a formal permit or physical inspection certificate',
                'Unknown safety, procurement and physical compliance evidence must remain unknown'], 'evidence_refs':[basis]}},
            {'ref':observation,'value':{'ref':observation,'organization_id':org,'scope':context['scope'],'as_of':context['business_time'],
                'market_demand':None,'prior_own_operations':None,'prior_own_approval_outcomes':None,'evidence_refs':[feedback['native_evidence_ref']]}}])
        context['visible_refs'].extend([policy,observation])
        grant=next(r['value'] for r in objects if r['ref']==context['authorization_refs'][0]);grant['readable_refs'].extend([policy,observation])
        authority_grant=next(g for g in settings['authority']['organization_snapshot']['authorizations'] if g['ref']==grant['ref'])
        authority_grant['readable_refs'].extend([policy,observation])
        GovernmentMonthlyPlan.model_validate(plan)
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']['kind']=='Evidence' and value.get('content_hash') is None:value['content_hash']='0'*64
            if row['ref']['kind']=='Feedback':value['event_source_sha256']='0'*64
            if row['ref']==observation:value.update(market_demand={'value':'0','unit':'index','basis_ref':feedback['native_evidence_ref']},prior_own_operations=[],prior_own_approval_outcomes=[])
            government_feedback_schemas().validate_projection(Reference.model_validate(row['ref']),value)
    settings['monthly'].update(_write(directory,'government-monthly-input.json',document))
    host['settings']=GovernmentIntakeSettings.model_validate(settings).model_dump(mode='json')
    _write(directory,'assembly-host.json',host)
    _write(directory,'native-host.json',read(foundation/'native-host.json'))
    macro=read(foundation/'macro-request.json');macro['macro_environment']['market_demand_index']=market_demand_index
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.government_intake_native:configure_assembly',readme_override=__doc__)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--market-demand-index',type=float,default=1.2);a=p.parse_args(argv)
    build_bundle(a.output,run_id=a.run_id,market_demand_index=a.market_demand_index)


if __name__=='__main__':main()
