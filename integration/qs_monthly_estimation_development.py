"""Declare private review policy and initial own mandate; no decided or executed result."""
from copy import deepcopy
from pathlib import Path
from integration.professional_monthly_development import build_bundle as foundation_bundle
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.qs_monthly_estimation import MonthlyEstimationPlan,QSMonthlyEstimationApplication
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference


def build_bundle(directory,*,run_id,material_price_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'outreach-foundation';foundation_bundle(foundation,run_id=run_id,ticks=2)
    authority=read(foundation/'assembly-host.json')['settings']['authority']
    plans=[];grants=[];project_id='qs-own-initial-design'
    for seed in read(foundation/'professional-monthly-input.json')['plans']:
        if seed['role']!='QS':continue
        org,tick=seed['organization_id'],seed['tick'];context=deepcopy(seed['context'])
        tag=org+'-estimation-'+str(tick);context['contract_ref']=ref('ActionContract','QS-A12')
        context.update(operation_id=tag,task_ref=ref('DecisionTask',tag),read_token=tag+'-read')
        objects=[deepcopy(r) for r in seed['objects'] if r['ref']['kind'] in
            {'Evidence','ClockProfile','Authorization','FunctionAssignment','Organization','CandidateSet'}]
        grant=next(r['value'] for r in objects if r['ref']==context['authorization_refs'][0])
        basis=grant['basis_refs'][0];window=deepcopy(grant['validity'])
        rr=lambda kind:ref(kind,tag)
        strategy,state,decision,capability,policy,observation=map(rr,[
            'Strategy','QSLearningState','QSLearningDecision','Capability','MonthlyEstimationPolicy','MonthlyEstimationObservation'])
        common={'scope':context['scope'],'available_at':context['business_time'],'effective_window':window,'evidence_refs':[basis]}
        authored={**common,'author_actor_id':context['actor_id'],'author_organization_id':org,
            'author_function_ref':context['function_ref'],'author_authority_ref':grant['ref'],
            'author_action_id':'QS-A12','authored_at':context['business_time']}
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**value}})
        add(strategy,{**authored,'organization_id':org,'learning_state_ref':state,'decision_profile_ref':decision,
            'judgments':[],'effect':'future_business_judgments_only'})
        add(state,{**common,'organization_id':org,'strategy_ref':strategy,'capability_ref':capability,'learning_profile_ref':None,
            'received_feedback_refs':[],'applied_feedback_refs':[],'execution_refs':[],'coverage':'unknown','as_of':context['business_time'],
            'forecast_refs':[],'outcome_refs':[],'applied_error_pair_keys':[]})
        add(capability,{**authored,'organization_id':org,'verified_capability_codes':[],'qualification_refs':[],'status':'unknown'})
        add(decision,{**authored,'organization_id':org,'strategy_ref':strategy,'actor_id':context['actor_id'],
            'function_ref':context['function_ref'],'authority_ref':grant['ref'],'business_key':tag,'choice':'record_feedback',
            'feedback_refs':[],'interpretation':'Evaluate the actual monthly sources; no participation or estimate is prefilled.',
            'assessment_ref':None,'training_profile_ref':None,'forecast_ref':None,'outcome_ref':None,'error_result_ref':None,
            'monthly_estimation_policy_ref':policy,'monthly_estimation_observation_ref':observation})
        measure=lambda value,unit:{'value':value,'unit':unit,'basis_ref':basis}
        add(policy,{'organization_id':org,'scope':context['scope'],'authority_ref':grant['ref'],'effective_window':window,
            'baseline_material_index':measure('1','index'),'minimum_relative_change':measure('0.05','ratio'),
            'minimum_free_ratio':measure('0.2','ratio'),'maximum_updates':1,'authorized_project_ids':[project_id],
            'purpose':'private_future_index_sensitivity_only','evidence_refs':[basis]})
        add(observation,{'organization_id':org,'scope':context['scope'],'as_of':context['business_time'],'material_index':None,
            'native_free_ratio':None,'own_project_evidence':None,'prior_own_outcomes':None,'evidence_refs':[seed['native_evidence_ref']]})
        candidate=next(r['value'] for r in objects if r['ref']==context['candidate_set_ref'])
        candidate.update(operation_id=tag,candidates=[{'ref':strategy,'permitted_choices':['record_feedback']}])
        grant['action_ids']=['QS-A12'];grant['readable_refs']=[r['ref'] for r in objects]
        context['visible_refs']=deepcopy(grant['readable_refs']);grants.append(deepcopy(grant))
        inputs={'scope':context['scope'],'strategy_ref':strategy,'forecast_refs':[],'outcome_refs':[],'feedback_refs':[],
            'comparability_result_ref':None,'learning_profile_ref':None}
        plans.append(MonthlyEstimationPlan.model_validate({'organization_id':org,'role':'QS','tick':tick,'context':context,
            'action_input':inputs,'objects':objects,'native_evidence_ref':seed['native_evidence_ref'],'observation_ref':observation}).model_dump(mode='json'))
        # Validate static types, without calculating or prefilling a judgment.
        for row in objects:
            if row['ref'] in [observation,seed['native_evidence_ref']]:continue
            QSMonthlyEstimationApplication.COMPONENTS['QS'][0].SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),row['value'])
    authority['organization_snapshot']['authorizations']=grants
    sources=_write(directory,'qs-estimation-input.json',{'schema_version':QSMonthlyEstimationApplication.INPUT_SCHEMA,'run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    native=read(foundation/'native-host.json')
    for field,operation in [('native_proposals','decide_monthly_operation'),('native_decisions','monthly_enterprise_operation')]:
        for role in ('Architect','Engineer'):native['settings'][field].append({'role':role,'operation' if field=='native_proposals' else 'decision_type':operation})
    _write(directory,'native-host.json',native)
    macro=read(foundation/'macro-request.json');macro['macro_environment']['material_price_index']=material_price_index
    macro['initial_projects']=[{'project_id':project_id,'name':'Declared initial own QS design estimate reference',
        'project_type':'building','region':'Hong Kong','owner_id':'professional-owner','initial_budget':1000,
        'current_stage':'design','selected_qs_id':'professional-qs'}]
    _write(directory,'source-policy.json',{'schema_version':'qs-monthly-estimation-source-policy.v1','organization_id':'professional-qs',
        'authorized_project_ids':[project_id],'initial_mandate_and_private_read_permission':'Declared synthetic initial own QS mandate; only its native planned-cost events may be read.',
        'reference_estimate_source':'Original design-state planned_cost; no incurred cost or frozen forecast is asserted.',
        'formula':'private sensitivity = original own planned_cost * accepted material index / independently declared baseline index',
        'publication':'Adopt only after exact own native monthly execution and original micro result have been confirmed.'})
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.qs_monthly_estimation:configure_assembly',readme_override=__doc__)
