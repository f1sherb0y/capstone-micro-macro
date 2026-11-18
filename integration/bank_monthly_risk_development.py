"""Declare a monthly risk policy before execution; actual case inputs remain unbound."""
from copy import deepcopy
from pathlib import Path

from integration.bank_financing_development import build_bundle as financing_bundle
from integration.bank_financing_native import BankFinancingSettings
from integration.bank_monthly_native import BankMonthlyPlan
from integration.contractor_tender_development import _write, _write_launch_files, ref
from integration.verify_tender_closed_loop import read


def build_bundle(directory, *, run_id, financing_condition_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'financing-foundation'
    financing_bundle(foundation,run_id=run_id,with_owner=True,feedback_followup=True,
        with_monthly_strategy=True,monthly_strategy_ticks=3,write_launch=False,
        owner_funding=[{'organization_id':owner,'actual_cash':'40000000','restricted_cash':'10000000'}
            for owner in ['finance-owner-a','finance-owner-b']])
    host=read(foundation/'assembly-host.json');settings=host['settings']
    document=read(foundation/'bank-monthly-strategy-input.json')
    for plan in document['plans']:
        context,objects=plan['context'],plan['objects'];org=plan['organization_id']
        space=next(r['value'] for r in objects if r['ref']==plan['action_input']['strategy_space_ref'])
        basis=plan['utility']['basis_ref'];window=space['effective_window']
        tag=org+'-monthly-risk-'+str(plan['tick'])
        policy,observation=ref('MonthlyBorrowerRiskPolicy',tag),ref('MonthlyBorrowerRiskObservation',tag)
        space.update(monthly_risk_policy_ref=policy,monthly_risk_observation_ref=observation)
        ratio=lambda value:{'value':value,'unit':'ratio','basis_ref':basis}
        objects.extend([{'ref':policy,'value':{'ref':policy,'organization_id':org,'scope':context['scope'],
            'authority_ref':context['authorization_refs'][0],'effective_window':window,'market_stress_weight':ratio('0.5'),
            'borrower_weakness_weight':ratio('0.25'),'monitoring_threshold':ratio('0.5'),'maximum_prior_monitoring':1,'evidence_refs':[basis]}},
            {'ref':observation,'value':{'ref':observation,'organization_id':org,'scope':context['scope'],'as_of':context['business_time'],
                'financing_condition':None,'received_cases':None,'prior_own_operations':None,'evidence_refs':[plan['native_evidence_ref']]}}])
        context['visible_refs'].extend([policy,observation])
        grant=next(r['value'] for r in objects if r['ref']==context['authorization_refs'][0]);grant['readable_refs'].extend([policy,observation])
        outer=next(g for g in settings['authority']['organization_snapshot']['authorizations'] if g['ref']==grant['ref'])
        outer['readable_refs'].extend([policy,observation])
        BankMonthlyPlan.model_validate(plan)
    settings['monthly_strategy'].update(_write(directory,'bank-monthly-strategy-input.json',document))
    host['settings']=BankFinancingSettings.model_validate(settings).model_dump(mode='json')
    _write(directory,'assembly-host.json',host);_write(directory,'native-host.json',read(foundation/'native-host.json'))
    macro=read(foundation/'macro-request.json')
    macro['macro_environment']['financing_condition_index']=financing_condition_index
    macro['ticks']=3
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.bank_financing_native:configure_assembly',readme_override=__doc__,
        allow_native_project_generation=True)
