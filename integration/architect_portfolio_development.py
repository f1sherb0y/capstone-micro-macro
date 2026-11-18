"""Predeclare private portfolio policy; real selections and monthly results stay unbound."""
from copy import deepcopy
from pathlib import Path
from integration.professional_intake_development import build_bundle as foundation
from integration.professional_intake_native import ProfessionalIntakeSettings
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.architect_portfolio_native import PortfolioPlan,PortfolioCompositionSettings,ArchitectPortfolioApplication
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.actions.registry import ActionRegistry
from src.actions.processors import register_representative_processors


def build_bundle(directory,*,run_id,market_demand_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    base=directory/'professional-foundation'
    foundation(base,run_id=run_id,with_owner=True,with_confirmation=True,with_opportunity=True)
    professional=read(base/'assembly-host.json')['settings'];authority=deepcopy(professional['authority'])
    original=read(base/'professional-input.json');plans=[];grants=authority['organization_snapshot']['authorizations']
    registry=register_representative_processors(ActionRegistry())
    for org in ('professional-architect','professional-architect-b'):
        seed=next(p for p in original['plans'] if p['organization_id']==org and p['tick']==1)['opportunity']
        for tick in (1,2):
            tag=org+'-portfolio-'+str(tick);rr=lambda kind:ref(kind,tag)
            context=deepcopy(seed['context']);scope={'kind':'organization','ref':ref('Organization',org),'coverage_refs':[]}
            now={**context['business_time'],'offset':tick};auth=rr('Authorization');action='ARCHITECT-A12'
            context.update(contract_ref=ref('ActionContract',action),scope=scope,business_time=now,
                operation_id=tag,read_token=tag+'-read',task_ref=rr('DecisionTask'),candidate_set_ref=rr('CandidateSet'),authorization_refs=[auth])
            # Reuse the original clock and original role assignment unchanged.
            objects=[deepcopy(r) for r in seed['objects'] if r['ref']['kind'] in {'Evidence','ClockProfile','FunctionAssignment'}
                and r['value'].get('content_hash','not-evidence') is not None]
            basis=next(r['value']['basis_refs'][0] for r in objects if r['ref']==context['function_ref'])
            oldgrant=next(r['value'] for r in seed['objects'] if r['ref'] in seed['context']['authorization_refs']);window=deepcopy(oldgrant['validity'])
            def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**deepcopy(value)}})
            native=rr('Evidence');add(native,{'source_kind':'synthetic','basis_kind':'observed',
                'locator':'actual-own-confirmed-native-selections-and-earlier-monthly-execution','content_hash':None,'effective_window':window})
            strategy,capability,state,decision,policy,observation=map(rr,['Strategy','Capability','ArchitectLearningState','ArchitectLearningDecision','MonthlyPortfolioPolicy','MonthlyPortfolioObservation'])
            authored={'scope':scope,'available_at':now,'effective_window':window,'author_actor_id':context['actor_id'],
                'author_organization_id':org,'author_function_ref':context['function_ref'],'author_authority_ref':auth,
                'author_action_id':action,'authored_at':now,'evidence_refs':[basis]}
            add(scope['ref'],{'evidence_refs':[basis]})
            add(strategy,{**authored,'organization_id':org,'learning_state_ref':state,'decision_profile_ref':decision,
                'judgments':[],'effect':'future_business_judgments_only'})
            add(capability,{**authored,'organization_id':org,'verified_capability_codes':[],'qualification_refs':[],'status':'unknown'})
            add(state,{'scope':scope,'available_at':now,'effective_window':window,'evidence_refs':[basis],
                'organization_id':org,'strategy_ref':strategy,'capability_ref':capability,'learning_profile_ref':None,
                'received_feedback_refs':[],'applied_feedback_refs':[],'execution_refs':[],'coverage':'unknown','as_of':now})
            add(decision,{**authored,'strategy_ref':strategy,'organization_id':org,'actor_id':context['actor_id'],
                'function_ref':context['function_ref'],'authority_ref':auth,'business_key':tag,'choice':'record_feedback','feedback_refs':[],
                'interpretation':'Original A12 computes a private selection portfolio from actual runtime observations.',
                'assessment_ref':None,'training_profile_ref':None,'monthly_portfolio_policy_ref':policy,'monthly_portfolio_observation_ref':observation})
            measure=lambda value,unit:{'value':value,'unit':unit,'basis_ref':basis}
            add(policy,{'organization_id':org,'scope':scope,'authority_ref':auth,'effective_window':window,
                'permitted_regions':['Hong Kong'],'minimum_market_demand':measure('1','index'),'minimum_free_ratio':measure('0.2','ratio'),
                'use':'private_selection_portfolio_only','evidence_refs':[basis]})
            add(observation,{'organization_id':org,'scope':scope,'as_of':now,'market_demand':None,'native_free_ratio':None,
                'selected_entries':None,'prior_own_outcomes':None,'evidence_refs':[native]})
            candidate=deepcopy(next(r['value'] for r in seed['objects'] if r['ref']==seed['context']['candidate_set_ref']))
            candidate.update(operation_id=tag,scope=scope,as_of=now,candidates=[{'ref':strategy,'permitted_choices':['record_feedback']}])
            # CandidateSet contains no ref field in its closed schema.
            objects.append({'ref':context['candidate_set_ref'],'value':candidate})
            grant=deepcopy(oldgrant);grant.update(ref=auth,action_ids=[action],scopes=[scope],readable_refs=[])
            objects.append({'ref':auth,'value':grant})
            grant['readable_refs']=[r['ref'] for r in objects];context['visible_refs']=deepcopy(grant['readable_refs']);grants.append(deepcopy(grant))
            from src.actions.contracts.domain import CandidateSet
            from src.actions.contracts.common import ActionContext
            CandidateSet.model_validate(candidate).check_context(ActionContext.model_validate(context),registry.get(action).contract.choices)
            action_input={'scope':scope,'strategy_ref':strategy,'capability_ref':capability,'learning_profile_ref':None,'feedback_refs':[]}
            registry.get(action).contract.validate_input(action_input)
            for row in objects:
                value=deepcopy(row['value'])
                if row['ref']==native:value['content_hash']='0'*64
                if row['ref']==observation:value.update(market_demand=measure('0','index'),native_free_ratio=measure('1','ratio'),selected_entries=[],prior_own_outcomes=[])
                ArchitectPortfolioApplication.COMPONENTS['Architect'][0].SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
            plans.append(PortfolioPlan.model_validate({'organization_id':org,'role':'Architect','tick':tick,'context':context,
                'action_input':action_input,'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    professional['authority']=authority
    sources=_write(directory,'portfolio-input.json',{'schema_version':'architect-monthly-portfolio-input.v1','run_id':run_id,'plans':plans})
    monthly=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    settings=PortfolioCompositionSettings(professional=ProfessionalIntakeSettings.model_validate(professional),monthly=monthly)
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    native=read(base/'native-host.json')
    for field in ('native_proposals','native_decisions'):native['settings'][field]=[r for r in native['settings'][field] if r['role']!='Architect']
    _write(directory,'native-host.json',native)
    macro=read(base/'macro-request.json');macro['macro_environment']['market_demand_index']=market_demand_index
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.architect_portfolio_native:configure_assembly',readme_override=__doc__)
