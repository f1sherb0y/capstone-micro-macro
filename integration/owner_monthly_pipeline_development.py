"""Enable original generation and declare a private post-screen review limit."""
from pathlib import Path
from integration.owner_opportunity_native_development import build_bundle as opportunity_bundle
from integration.owner_monthly_pipeline import OwnerPipelineSettings
from integration.contractor_tender_development import _write, _write_launch_files
from integration.verify_tender_closed_loop import read


def build_bundle(directory,*,run_id,maximum_prior_screens_before_portfolio_review):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'foundation'
    opportunity_bundle(foundation,run_id=run_id,max_prior_initiations=999,random_seed=1)
    source=read(foundation/'assembly-host.json')
    settings=OwnerPipelineSettings.model_validate({'opportunity':source['settings'],
        'pipeline':{'organization_id':'finance-owner-a','minimum_market_demand':'0.5',
            'maximum_prior_screens_before_portfolio_review':maximum_prior_screens_before_portfolio_review,
            'authorized_ticks':[1,2],'purpose':'review_received_native_candidates_only'}})
    _write(directory,'assembly-host.json',{**source,'settings':settings.model_dump(mode='json')})
    native=read(foundation/'native-host.json')
    for field,operation,key in [('native_proposals','decide_monthly_operation','operation'),
            ('native_decisions','monthly_enterprise_operation','decision_type')]:
        native['settings'][field]=[r for r in native['settings'][field] if (r['role'],r[key])!=('Owner',operation)]
    _write(directory,'native-host.json',native)
    _write(directory,'macro-request.json',read(foundation/'macro-request.json'))
    _write(directory,'source-policy.json',{'origin':'explicit-independent-private-policy',
        'source':'Original generation and original own received opportunity assessment; no replay or replacement candidates',
        'policy':settings.pipeline.model_dump(mode='json'),
        'initial_private_portfolio':'Unchanged original opportunity template: independent cash, restriction, old unpaid debt, management load and professional forecasts',
        'boundary':'Completed native internal screens affect only an independently declared future investment appetite limit; no native cash, credit or reserve mutation'})
    _write_launch_files(directory,assembly_hook='integration.owner_monthly_pipeline:configure_assembly',
        allow_native_project_generation=True,readme_override=__doc__)
