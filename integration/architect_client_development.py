"""Independent internal client-follow-up tasks; actual relationships stay unbound."""
from copy import deepcopy
from pathlib import Path
from integration.architect_portfolio_development import build_bundle as foundation
from integration.architect_client_relationship import ClientRelationshipPlan
from integration.architect_portfolio_native import PortfolioCompositionSettings
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.verify_tender_closed_loop import read
from integration.architect_learning_actions import ArchitectLearningActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,market_demand_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    base=directory/'portfolio-foundation';foundation(base,run_id=run_id,market_demand_index=market_demand_index)
    settings=read(base/'assembly-host.json')['settings'];authority=settings['professional']['authority'];snapshot=authority['organization_snapshot']
    original=read(base/'portfolio-input.json')['plans'];plans=[]
    permitted=[o['organization_id'] for o in snapshot['organizations'] if o['assignments'][0]['role'] in {'Owner','Engineer','QS'}]
    def retag(v,old,new):
        if isinstance(v,str):return v.replace(old,new)
        if isinstance(v,list):return [retag(x,old,new) for x in v]
        if isinstance(v,dict):return {k:retag(x,old,new) for k,x in v.items()}
        return v
    for org in sorted({p['organization_id'] for p in original}):
        for tick in (1,2,3):
            seed=deepcopy(next(p for p in original if p['organization_id']==org and p['tick']==min(tick,2)))
            old=seed['context']['operation_id'];tag=org+'-client-followup-'+str(tick);seed=retag(seed,old,tag)
            context=seed['context'];now={**context['business_time'],'offset':tick};context['business_time']=now
            objects=[r for r in seed['objects'] if r['ref']['kind'] not in {'MonthlyPortfolioPolicy','MonthlyPortfolioObservation'}]
            for r in objects:
                for key in ('as_of','available_at','authored_at'):
                    if key in r['value'] and r['ref']['kind'] in {'CandidateSet','Strategy','Capability','ArchitectLearningState','ArchitectLearningDecision'}:r['value'][key]=deepcopy(now)
            decision,=[r['value'] for r in objects if r['ref']['kind']=='ArchitectLearningDecision']
            decision.update(monthly_portfolio_policy_ref=None,monthly_portfolio_observation_ref=None,
                interpretation='Original A12 maintains explicitly authorized private client/consultant follow-up records from actual selected collaboration.')
            grant,=[r['value'] for r in objects if r['ref']==context['authorization_refs'][0]];window=grant['validity']
            task=ref('ClientRelationshipTask',tag);obs=ref('ClientRelationshipObservation',tag);basis=ref('Evidence',tag+'-independent-internal-task')
            def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**deepcopy(value)}})
            assumptions={'purpose':'internal_selected_client_and_consultant_followup_record','allowed_party_ids':permitted,
                'responsible_actor_id':context['actor_id'],'private_review_weight':'0.8','minimum_priority':'0.8','review_interval_ticks':2,
                'external_contact_consent':'unknown','meaning':'Private record and review agenda only; no delivery, current detailed terms or client satisfaction assumed.'}
            add(basis,{'source_kind':'synthetic','basis_kind':'assumed','locator':'independent-initial-authorized-private-client-followup-task-policy',
                'content_hash':task_digest(assumptions),'effective_window':window})
            measure=lambda v,u:{'value':v,'unit':u,'basis_ref':basis}
            add(task,{'organization_id':org,'scope':context['scope'],'authority_ref':grant['ref'],'responsible_actor_id':context['actor_id'],
                'effective_window':window,'permitted':known(True),'allowed_party_roles':['Owner','Engineer','QS'],'allowed_party_ids':permitted,
                'private_review_weight':measure('0.8','ratio'),'minimum_priority':measure('0.8','priority'),'minimum_free_ratio':measure('0.2','ratio'),
                'review_interval_ticks':2,'purpose':assumptions['purpose'],
                'external_contact_consent':{'state':'unknown','reason_code':'no_external_contact_authorization_or_receipt','missing_refs':[]},'evidence_refs':[basis]})
            add(obs,{'organization_id':org,'scope':context['scope'],'as_of':now,'market_demand':None,'native_free_ratio':None,
                'parties':None,'prior_own_outcomes':None,'evidence_refs':[seed['native_evidence_ref']]})
            decision.update(monthly_client_task_ref=task,monthly_client_observation_ref=obs)
            for r in objects:
                if r['ref']==seed['native_evidence_ref']:r['value'].update(locator='actual-strictly-prior-own-A03-selected-team-parties-and-confirmed-private-followup-records',content_hash=None)
            grant['readable_refs']=[r['ref'] for r in objects];context['visible_refs']=deepcopy(grant['readable_refs']);snapshot['authorizations'].append(deepcopy(grant))
            for r in objects:
                value=deepcopy(r['value'])
                if r['ref']==seed['native_evidence_ref']:value['content_hash']='0'*64
                if r['ref']==obs:value.update(market_demand=measure('0','index'),native_free_ratio=measure('1','ratio'),parties=[],prior_own_outcomes=[])
                ArchitectLearningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(r['ref']),value)
            plans.append(ClientRelationshipPlan.model_validate({'organization_id':org,'role':'Architect','tick':tick,'context':context,
                'action_input':seed['action_input'],'objects':objects,'native_evidence_ref':seed['native_evidence_ref'],'observation_ref':obs}).model_dump(mode='json'))
    sources=_write(directory,'client-relationship-input.json',{'schema_version':'architect-client-relationship-input.v1','run_id':run_id,'plans':plans})
    settings['monthly']={'authority':authority,**sources};settings=PortfolioCompositionSettings.model_validate(settings)
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',read(base/'native-host.json'))
    macro=read(base/'macro-request.json');macro['ticks']=3;_write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.architect_client_relationship:configure_assembly',readme_override=__doc__)
