"""Current native monthly requests and authenticated own feedback operations."""
from copy import deepcopy
import json

from integration.bank_financing_private import checked_result
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest
from src.actions.contracts.government_monthly_objects import OPERATIONS
from integration.government_monthly_business import result_operation


def monthly_scope(assembly,request,*,purpose):
    assembly._validate_components();engine=assembly.engine;org=request.agent.agent_id
    if (request.agent.role!='Government' or assembly.client.organization_roles.get(org)!='Government'
            or org not in engine.agents or engine.agents[org].role!='Government'):
        raise TaskConflict('Monthly feedback changes its original own Government or project-free scope')
    scope={'organization_id':org,'tick':engine.current_tick}
    if purpose=='propose':
        if (request.operation!='decide_monthly_operation' or set(request.inputs)!={'macro_environment'}
                or request.inputs['macro_environment']!=engine.macro_environment.model_dump(mode='json')):
            raise TaskConflict('Monthly feedback needs its exact original current environment request')
    elif purpose=='decide':
        if (request.decision_type!='monthly_enterprise_operation' or request.tick!=engine.current_tick or request.project_id is not None
                or request.environment!=engine.macro_environment.model_dump(mode='json') or request.project not in (None,{})
                or request.decision_support.get('decision_factors',{}).get('native_monthly_feedback_scope')!=scope):
            raise TaskConflict('Monthly feedback final lost its current original request or proposal scope')
    else:raise TaskConflict('Unknown monthly feedback transport purpose')
    return scope


def project_monthly_feedback_event(observation,roles):
    data=observation.data
    if (not observation.committed or observation.event_type!='agent_operation'
            or roles.get(observation.agent_id)!='Government' or observation.project_id is not None
            or data.get('operation') not in OPERATIONS):
        return {}
    fields=('operation','label','description','available_resource','capability_update','decision_accepted',
        'decision_source','decision_process','decision_utility','decision_probability','decision_factors')
    bound={k:deepcopy(data[k]) for k in fields if k in data}
    return {observation.agent_id:{'event_type':'agent_operation','tick':observation.tick,
        'project_id':None,'agent_id':observation.agent_id,'committed':True,'data':bound}}


def prior_monthly_feedback(assembly,*,organization_id,tick,read_guard,worker,organizations=None):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    with read_guard():
        assembly._validate_components();engine,client=assembly.engine,assembly.client
        if client.organization_roles.get(organization_id)!='Government' or type(tick) is not int or tick!=engine.current_tick:
            raise TaskConflict('Monthly feedback history changes its current own organization or clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id)
        with client.tasks._lock:
            records=[json.loads(v) for v, in client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',
                ('government_monthly_native_request:%',))]
        origins=[]
        for row in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=row['payload']
            if (payload['event_type']!='agent_operation' or payload['tick']>=tick
                    or payload['data'].get('operation') not in OPERATIONS):continue
            events=[e for e in engine.events.events if e.event_id==row['event_id']]
            if len(events)!=1:raise TaskConflict('Monthly feedback history lost its actual native event')
            event=events[0];raw=event.model_dump(mode='json')
            expected=project_monthly_feedback_event(AgentObservationV1.model_validate(raw),client.organization_roles)
            if organization_id not in expected or expected[organization_id]!=payload:
                raise TaskConflict('Monthly feedback history substitutes its event or private recipient')
            scope={'organization_id':organization_id,'tick':event.tick}
            technical=[r for r in records if r.get('state')=='formed' and r.get('scope')==scope]
            if not technical:continue  # Native background work is not automatically micro coverage.
            proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='decide_monthly_operation' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_monthly_feedback_scope')==scope]
            finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='monthly_enterprise_operation' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_monthly_feedback_scope')==scope]
            if len(technical)!=1 or len(proposals)!=1 or len(finals)!=1:
                raise TaskConflict('Monthly feedback history lost its original micro/proposal/final')
            record,proposal,final=technical[0],proposals[0],finals[0];identity=TaskIdentity(**record['identity'])
            factors=proposal['factors'];data=payload['data']
            saved=checked_result(worker,identity);invocation=InvocationSnapshotStore(client.tasks).get(identity)
            from integration.government_history_authority import authorize_government_history
            authorize_government_history(assembly,identity,organizations=organizations,tick=tick,saved=saved)
            if (record['record_sha256']!=task_digest({k:v for k,v in record.items() if k!='record_sha256'})
                    or proposal['accepted'] is not True or final['decision'] is not True
                    or proposal['action_type']!=final['action_type'] or final['action_type']!=result_operation(saved)
                    or payload['data']['operation']!=result_operation(saved)
                    or factors.get('native_monthly_feedback_scope')!=scope or factors.get('micro_action_id')!='GOV-A12'
                    or final['data'].get('proposal_response_sha256')!=task_digest(proposal)
                    or record['proposal_response_sha256']!=task_digest(proposal)
                    or any(final['data'].get(k)!=v for k,v in factors.items())
                    or identity.organization_id!=organization_id or identity.key!=factors['micro_task_key']
                    or saved['result_sha256']!=factors['micro_result_sha256'] or record['result_sha256']!=saved['result_sha256']
                    or saved['result']['payload']['choice']!='record_feedback'
                    or invocation['context']!=record['context'] or invocation['action_input']!=record['action_input']):
                raise TaskConflict('Monthly feedback history changes its original deciding result or bounded confirmation')
            if (data.get('decision_accepted') is not True or data.get('decision_source')!='llm_agent'
                    or data.get('label')!=proposal['data']['label'] or data.get('description')!=proposal['data']['description']
                    or data.get('decision_utility')!=round(proposal['utility'],4)
                    or data.get('decision_probability')!=round(proposal['probability'],4)
                    or data.get('decision_process')!=engine.agent_registry.proposal_process_name(engine.agents[organization_id],'decide_monthly_operation')):
                raise TaskConflict('Monthly native operation does not match its original private proposal and final')
            native=[r['projection'] for r in saved['source_reading'] if r['ref']==record['native_evidence_ref']]
            if (len(native)!=1 or native[0]['content_hash']!=task_digest(record['observed'])
                    or record['observed']['native_request_sha256']!=task_digest(record['native_request'])
                    or record['observed']['scope']!=scope):
                raise TaskConflict('Monthly feedback history changes its actual original request evidence')
            memories=[m for m in engine.agents[organization_id].episodic_memory
                if m.get('tick')==event.tick and m.get('operation')==result_operation(saved)]
            if len(memories)>1 or (memories and any(memories[0].get(k)!=data.get(k)
                    for k in ('label','decision_factors','capability_update'))):
                raise TaskConflict('Monthly feedback history substitutes retained original native enterprise memory')
            origins.append({'event_id':event.event_id,'tick':event.tick,'organization_id':organization_id,
                'native_monthly_feedback_scope':scope,'micro_task_key':identity.key,
                'micro_result_sha256':saved['result_sha256'],'source_event_sha256':task_digest(raw),
                'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final),
                'capability_update':payload['data'].get('capability_update'),'native_memory_retained':bool(memories),
                'correlation':'own_agent_tick_operation_original_private_proposal_and_confirmation'})
            if result_operation(saved)!='review_policy_feedback':origins[-1]['operation']=result_operation(saved)
        if len({r['event_id'] for r in origins})!=len(origins):raise TaskConflict('Monthly feedback history repeats an event')
        return sorted(origins,key=lambda r:(r['tick'],r['event_id']))
