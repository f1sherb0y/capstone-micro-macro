"""Predeclare two-role method policies; leave actual monthly observations unbound."""
from copy import deepcopy
from pathlib import Path
from integration.professional_monthly_development import build_bundle as monthly_foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.professional_methods_native import COMPONENTS,MonthlyMethodPlan
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.actions.registry import ActionRegistry
from src.actions.processors import register_representative_processors


def build_bundle(directory,*,run_id,regulatory_pressure_index,ticks=2):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'outreach-foundation';monthly_foundation(foundation,run_id=run_id,ticks=ticks)
    authority=read(foundation/'assembly-host.json')['settings']['authority']
    document=read(foundation/'professional-monthly-input.json');plans=[];grants=[]
    registry=register_representative_processors(ActionRegistry())
    for seed in document['plans']:
        if seed['role'] not in COMPONENTS:continue
        org,role,tick=seed['organization_id'],seed['role'],seed['tick'];context=deepcopy(seed['context'])
        tag=org+'-monthly-methods-'+str(tick);action=role.upper()+'-A12';context['contract_ref']=ref('ActionContract',action)
        # Keep only actual scope, clock, author and declared evidence metadata;
        # the old invitation, service capacity and A01 policy are not A12 facts.
        objects=[deepcopy(r) for r in seed['objects'] if r['ref']['kind'] in
            {'Evidence','ClockProfile','Authorization','FunctionAssignment','Organization','CandidateSet'}]
        basis=next(r['value']['basis_refs'][0] for r in objects if r['ref']==context['function_ref'])
        grant=next(r['value'] for r in objects if r['ref']==context['authorization_refs'][0]);window=grant['validity']
        rr=lambda kind:ref(kind,tag)
        strategy,capability,state,decision,policy,observation=map(rr,['Strategy','Capability',role+'LearningState',role+'LearningDecision','MonthlyMethodPolicy','MonthlyMethodObservation'])
        authored={'scope':deepcopy(context['scope']),'available_at':context['business_time'],'effective_window':window,
            'author_actor_id':context['actor_id'],'author_organization_id':org,'author_function_ref':context['function_ref'],
            'author_authority_ref':context['authorization_refs'][0],'author_action_id':action,'authored_at':context['business_time'],'evidence_refs':[basis]}
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**value}})
        add(strategy,{**authored,'organization_id':org,'learning_state_ref':state,'decision_profile_ref':decision,
            'judgments':[],'effect':'future_business_judgments_only'})
        add(capability,{**authored,'organization_id':org,'verified_capability_codes':[],'qualification_refs':[],'status':'unknown'})
        state_value={'scope':context['scope'],'available_at':context['business_time'],'effective_window':window,'evidence_refs':[basis],
            'organization_id':org,'strategy_ref':strategy,'capability_ref':capability,'learning_profile_ref':None,
            'received_feedback_refs':[],'applied_feedback_refs':[],'execution_refs':[],'coverage':'unknown','as_of':context['business_time']}
        if role=='Engineer':state_value.update(qualification_refs=[],applied_qualification_event_refs=[])
        add(state,state_value)
        decision_value={**authored,'strategy_ref':strategy,'organization_id':org,'actor_id':context['actor_id'],'function_ref':context['function_ref'],
            'authority_ref':context['authorization_refs'][0],'business_key':tag,'choice':'record_feedback','feedback_refs':[],
            'interpretation':'Monthly native observations are evaluated by original A12; no formal learning or training outcome is prefilled',
            'assessment_ref':None,'training_profile_ref':None,'monthly_method_policy_ref':policy,'monthly_method_observation_ref':observation}
        if role=='Engineer':decision_value.update(qualification_ref=None,qualification_update_basis_ref=None)
        add(decision,decision_value)
        measure=lambda value,unit:{'value':value,'unit':unit,'basis_ref':basis}
        add(policy,{'organization_id':org,'role':role,'scope':context['scope'],'authority_ref':context['authorization_refs'][0],
            'effective_window':window,'baseline_requirement':measure('0.4','native_capability_index'),
            'regulatory_pressure_weight':measure('0.5','ratio'),'minimum_shortfall':measure('0.05','native_capability_index'),
            'minimum_free_ratio':measure('0.2','ratio'),'maximum_prior_improvements':1,
            'method_focus':'Review design and approval checklists' if role=='Architect' else 'Review engineering design-review and constructability checklists',
            'evidence_refs':[basis],'design_review':None})
        add(observation,{'organization_id':org,'role':role,'scope':context['scope'],'as_of':context['business_time'],
            'regulatory_pressure':None,'native_capability':None,'native_free_ratio':None,'prior_own_outcomes':None,'design_results':None,'evidence_refs':[seed['native_evidence_ref']]})
        candidate=next(r['value'] for r in objects if r['ref']==context['candidate_set_ref'])
        candidate['candidates']=[{'ref':strategy,'permitted_choices':['record_feedback']}]
        grant['action_ids']=[action];grant['readable_refs']=[r['ref'] for r in objects]
        context['visible_refs']=deepcopy(grant['readable_refs']);grants.append(deepcopy(grant))
        action_input={'scope':context['scope'],'strategy_ref':strategy,'learning_profile_ref':None,'feedback_refs':[]}
        action_input.update(capability_ref=capability) if role=='Architect' else action_input.update(qualification_refs=[])
        registry.get(action).contract.validate_input(action_input)
        for r in objects:
            value=deepcopy(r['value'])
            if r['ref']==seed['native_evidence_ref']:value['content_hash']='0'*64
            if r['ref']==observation:
                value.update(regulatory_pressure={'value':'0','unit':'index','basis_ref':seed['native_evidence_ref']},
                    native_capability={'value':'0','unit':'native_capability_index','basis_ref':seed['native_evidence_ref']},
                    native_free_ratio={'value':'0','unit':'ratio','basis_ref':seed['native_evidence_ref']},prior_own_outcomes=[])
            COMPONENTS[role][0].SOURCE_SCHEMAS().validate_projection(Reference.model_validate(r['ref']),value)
        plans.append(MonthlyMethodPlan.model_validate({'organization_id':org,'role':role,'tick':tick,'context':context,
            'action_input':action_input,'objects':objects,'native_evidence_ref':seed['native_evidence_ref'],'observation_ref':observation}).model_dump(mode='json'))
    authority['organization_snapshot']['authorizations']=grants
    sources=_write(directory,'professional-methods-input.json',{'schema_version':'professional-monthly-methods-input.v1','run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    native=read(foundation/'native-host.json')
    for field,operation in [('native_proposals','decide_monthly_operation'),('native_decisions','monthly_enterprise_operation')]:
        native['settings'][field].append({'role':'QS','operation' if field=='native_proposals' else 'decision_type':operation})
    _write(directory,'native-host.json',native)
    macro=read(foundation/'macro-request.json');macro['macro_environment']['regulatory_pressure_index']=regulatory_pressure_index
    for agent in macro['agents']:
        if agent['role']=='Architect':agent['design_capability']=0.6
        if agent['role']=='Engineer':agent['technical_capability']=0.6
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.professional_methods_native:configure_assembly',readme_override=__doc__)
