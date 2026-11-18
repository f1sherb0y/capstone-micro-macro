"""Declare private index policies and original applicability metadata before execution."""
from copy import deepcopy
from pathlib import Path
from integration.professional_monthly_development import build_bundle as monthly_foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.qs_monthly_cost_market import MonthlyCostPlan,QSCostMarketApplication
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference


def build_bundle(directory,*,run_id,material_price_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'outreach-foundation';monthly_foundation(foundation,run_id=run_id,ticks=3)
    authority=read(foundation/'assembly-host.json')['settings']['authority'];document=read(foundation/'professional-monthly-input.json')
    plans=[];grants=[]
    for seed in document['plans']:
        if seed['role']!='QS':continue
        org,tick=seed['organization_id'],seed['tick'];context=deepcopy(seed['context']);tag=org+'-cost-index-'+str(tick)
        objects=[deepcopy(r) for r in seed['objects'] if r['ref']['kind'] in
            {'Evidence','ClockProfile','Authorization','FunctionAssignment','Organization','CandidateSet'}]
        basis=next(r['value']['basis_refs'][0] for r in objects if r['ref']==context['function_ref'])
        grant=next(r['value'] for r in objects if r['ref']==context['authorization_refs'][0]);window=grant['validity']
        rr=lambda kind:ref(kind,tag)
        strategy,policy,observation,source,app=map(rr,['Strategy','MonthlyCostPolicy','MonthlyCostObservation','PriceSource','PriceApplicability'])
        common={'scope':context['scope'],'available_at':context['business_time'],'effective_window':window,'evidence_refs':[basis]}
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**value}})
        add(strategy,{**common,'organization_id':org,'author_actor_id':context['actor_id'],'author_function_ref':context['function_ref'],
            'author_authority_ref':context['authorization_refs'][0],'choice_order':['register_source','ignore'],
            'opportunity_order':[],'source_order':[source],'preparation_ref':None,'ignore_reason':'No eligible original simulation index',
            'monthly_cost_policy_ref':policy,'monthly_cost_observation_ref':observation})
        metadata=[ref('Region','simulation_global_'+str(tick)),ref('DeliveryScope','native_model_scope_not_delivery_'+str(tick)),
            ref('MeasurementRule','dimensionless_index_no_conversion_'+str(tick)),ref('CostScope','native_material_index_only_'+str(tick))]
        for identity in metadata:add(identity,common)
        applicability={'ref':app,**common,'evidence_refs':[seed['native_evidence_ref']],'price_source_ref':source,'price_time':context['business_time'],
            'region_ref':metadata[0],'delivery_scope_ref':metadata[1],'measurement_rule_ref':metadata[2],
            'included_scope_refs':[metadata[3]],'excluded_scope_refs':[]}
        add(source,{**common,'recipient_ids':[context['actor_id']],'permission':{'state':'known','value':True},'confidentiality':'authorized_private',
            'source_kind':'index','observation_ref':seed['native_evidence_ref'],'applicability':{'state':'known','value':applicability},
            'limitations':['Native simulation-global dimensionless material index only; no regional price, tender benchmark, currency, delivery or actual project cost.']})
        measure=lambda value,unit:{'value':value,'unit':unit,'basis_ref':basis}
        add(policy,{'organization_id':org,'scope':context['scope'],'authority_ref':context['authorization_refs'][0],'effective_window':window,
            'baseline_material_index':measure('1','index'),'pressure_threshold':measure('0.1','ratio'),
            'minimum_relative_change':measure('0.01','ratio'),'maximum_updates':1,'evidence_refs':[basis]})
        add(observation,{'organization_id':org,'scope':context['scope'],'as_of':context['business_time'],'material_index':None,
            'prior_own_outcomes':None,'registered_indices':None,'evidence_refs':[seed['native_evidence_ref']]})
        candidate=next(r['value'] for r in objects if r['ref']==context['candidate_set_ref'])
        candidate['candidates']=[{'ref':source,'permitted_choices':['register_source']}]
        grant['action_ids']=['QS-A01'];grant['readable_refs']=[r['ref'] for r in objects]
        context['visible_refs']=deepcopy(grant['readable_refs']);grants.append(deepcopy(grant))
        action_input={'scope':context['scope'],'strategy_ref':strategy,'opportunity_refs':[],'price_source_refs':[source],'research_authority_ref':None}
        for r in objects:
            value=deepcopy(r['value'])
            if r['ref']==seed['native_evidence_ref']:value['content_hash']='0'*64
            if r['ref']==observation:value.update(material_index={'value':'1','unit':'index','basis_ref':seed['native_evidence_ref']},prior_own_outcomes=[],registered_indices=[])
            QSCostMarketApplication.COMPONENTS['QS'][0].SOURCE_SCHEMAS().validate_projection(Reference.model_validate(r['ref']),value)
        plans.append(MonthlyCostPlan.model_validate({'organization_id':org,'role':'QS','tick':tick,'context':context,'action_input':action_input,
            'objects':objects,'native_evidence_ref':seed['native_evidence_ref'],'observation_ref':observation}).model_dump(mode='json'))
    authority['organization_snapshot']['authorizations']=grants
    sources=_write(directory,'qs-cost-market-input.json',{'schema_version':QSCostMarketApplication.INPUT_SCHEMA,'run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    native=read(foundation/'native-host.json')
    for field,operation in [('native_proposals','decide_monthly_operation'),('native_decisions','monthly_enterprise_operation')]:
        for role in ('Architect','Engineer'):native['settings'][field].append({'role':role,'operation' if field=='native_proposals' else 'decision_type':operation})
    _write(directory,'native-host.json',native)
    macro=read(foundation/'macro-request.json');macro['macro_environment']['material_price_index']=material_price_index
    # Original supported initial-project entry. An unappointed design-stage
    # background case leaves a three-month observation window; no design
    # completion, appointment, project cost or lifecycle result is prefilled.
    macro['initial_projects'][0].update(project_id='monthly-design-background',current_stage='design',
        name='Initial unappointed design background; no detailed project work claimed')
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.qs_monthly_cost_market:configure_assembly',readme_override=__doc__)
