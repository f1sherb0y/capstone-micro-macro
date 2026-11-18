"""Own native creation is appetite feedback, never a new cash/debt/reservation fact."""
from copy import deepcopy
import json

from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest
from src.coordination.invocations import InvocationSnapshotStore


def project_owner_opportunity_event(observation,organization_roles):
    if (not observation.committed or organization_roles.get(observation.agent_id)!='Owner'
            or observation.event_type not in {'project_opportunity_initiated','project_opportunity_declined'}):return {}
    factors=observation.data.get('decision_factors',{})
    action=factors.get('micro_action_id')
    if action not in {'OWN-A01','OWN-A03','OWN-A16'} or (action in {'OWN-A01','OWN-A16'}
            and observation.event_type!='project_opportunity_declined'):return {}
    data={k:deepcopy(observation.data[k]) for k in ('owner_id','region','project_type','budget','planned_duration')
        if k in observation.data}
    for k in ('micro_action_id','micro_task_key','micro_result_sha256','native_owner_opportunity_scope',
            'individual_accepted','individual_action'):
        if k in factors:data[k]=deepcopy(factors[k])
    return {observation.agent_id:{'event_type':observation.event_type,'tick':observation.tick,
        'project_id':observation.project_id,'agent_id':observation.agent_id,'committed':True,'data':data}}


def authorize_owner_history(saved, snapshot, *, organizations, tick):
    """Recheck present reading rights without changing the original invocation."""
    from src.actions.contracts.common import ActionContext, Reference
    from src.organization.registry import AccessDenied
    if organizations is None:
        raise TaskConflict('Owner history requires its current original organization authority')
    identity = TaskIdentity(**saved['identity'])
    context = ActionContext.model_validate(snapshot['context'])
    if (type(tick) is not int or tick < context.business_time.offset
            or identity.run_id != context.run_id or identity.role != 'Owner' or identity.purpose != 'action'
            or identity.action_id not in {'OWN-A01', 'OWN-A02', 'OWN-A03', 'OWN-A16'}
            or context.contract_ref.id != identity.action_id or snapshot['identity'] != saved['identity']
            or identity.context_sha256 != task_digest(snapshot['context'])
            or identity.input_sha256 != task_digest(snapshot['action_input'])
            or saved['record_sha256'] != task_digest({k: v for k, v in saved.items() if k != 'record_sha256'})
            or saved['result_sha256'] != task_digest(saved['result'])
            or saved['source_reading_sha256'] != task_digest(saved['source_reading'])
            or saved['result']['kind'] != 'completed'):
        raise TaskConflict('Owner history changes its original invocation, result or saved reading')
    current = context.model_copy(update={
        'business_time': context.business_time.model_copy(update={'offset': tick})}, deep=True)
    grants = organizations.grants(current, identity.action_id, 'Owner')
    readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in context.visible_refs}
    if (not grants or any(g.organization_id != identity.organization_id for g in grants)
            or any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading'])):
        raise AccessDenied('Owner history lost current permission for its original private sources')


def prior_owner_initiations(assembly,*,organization_id,tick,read_guard,organizations=None):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    if not callable(read_guard):raise TaskConflict('Owner opportunity history requires its original guard')
    with read_guard():
        assembly._validate_components();client,engine=assembly.client,assembly.engine
        if client.organization_roles.get(organization_id)!='Owner' or type(tick) is not int or engine.current_tick!=tick:
            raise TaskConflict('Owner opportunity history changes its own identity or native clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id);origins=[]
        for entry in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=entry['payload']
            if payload['event_type']!='project_opportunity_initiated' or payload['tick']>=tick:continue
            project=engine.projects.get(payload['project_id'])
            events=[] if project is None else [e for e in project.event_log if e['event_id']==entry['event_id']]
            if len(events)!=1:raise TaskConflict('Owner opportunity history lost its actual project creation')
            event=events[0];expected=project_owner_opportunity_event(AgentObservationV1.model_validate(event),client.organization_roles)
            if (project.owner_id!=organization_id or event['agent_id']!=organization_id or organization_id not in expected
                    or payload!=expected[organization_id] or event['data'].get('owner_id')!=organization_id):
                raise TaskConflict('Owner opportunity history substitutes its actual event or private recipient')
            data=payload['data'];scope=data['native_owner_opportunity_scope']
            if (scope['tick']!=event['tick'] or scope['owner_id']!=organization_id
                    or data.get('individual_accepted') is not True or data.get('individual_action')!='initiate_project'
                    or project.flags.get('created_tick')!=event['tick'] or project.initial_budget!=data['budget']
                    or project.region!=data['region'] or project.project_type!=data['project_type']):
                raise TaskConflict('Owner opportunity history changes its actual creation scope or project')
            proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='evaluate_project_opportunity' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_owner_opportunity_scope')==scope]
            finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='owner_project_opportunity' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_owner_opportunity_scope')==scope]
            micro=[t for t in tasks if t['identity']['purpose']=='action' and t['identity']['action_id']=='OWN-A03'
                and t['state']=='output_formed' and TaskIdentity(**t['identity']).key==data['micro_task_key']]
            if len(proposals)!=1 or len(finals)!=1 or len(micro)!=1:
                raise TaskConflict('Owner opportunity history lost its original proposal/final/investment')
            proposal,final=proposals[0],finals[0]
            fields=('micro_action_id','micro_task_key','micro_result_sha256','native_owner_opportunity_scope')
            if (proposal['accepted'] is not True or final['decision'] is not True
                    or proposal['action_type']!=final['action_type'] or final['action_type']!='initiate_project'
                    or final['data'].get('proposal_response_sha256')!=task_digest(proposal)
                    or any(data[k]!=proposal['factors'].get(k) or data[k]!=final['data'].get(k) for k in fields)
                    or micro[0]['output_sha256']!=data['micro_result_sha256']
                    or task_digest(micro[0]['output'])!=data['micro_result_sha256']
                    or micro[0]['output']['kind']!='completed' or micro[0]['output']['payload']['choice']!='invest'):
                raise TaskConflict('Owner opportunity history substitutes its confirmed original investment')
            with client.tasks._lock:
                raw=client.tasks._db.execute('SELECT record FROM owner_investment_results WHERE task_key=?',(data['micro_task_key'],)).fetchone()
                technical=[json.loads(v) for v, in client.tasks._db.execute(
                    'SELECT value FROM metadata WHERE key LIKE ?',('owner_opportunity_native_request:%',))]
            saved=None if raw is None else json.loads(raw[0])
            records=[r for r in technical if r.get('scope')==scope and r.get('state')=='formed']
            if (saved is None or len(records)!=1 or saved['record_sha256']!=task_digest({k:v for k,v in saved.items() if k!='record_sha256'})
                    or saved['identity']!=micro[0]['identity'] or saved['result']!=micro[0]['output']
                    or saved['result_sha256']!=data['micro_result_sha256']
                    or saved['source_reading_sha256']!=task_digest(saved['source_reading'])
                    or saved['audit'].get('input_sha256')!=micro[0]['identity']['input_sha256']
                    or saved['audit'].get('result_sha256')!=data['micro_result_sha256']):
                raise TaskConflict('Owner opportunity history lost its original investment sources/audit')
            record=records[0];op=record['native_request']['inputs']['opportunity']
            invocation=InvocationSnapshotStore(client.tasks).get(TaskIdentity(**micro[0]['identity']))
            authorize_owner_history(saved,invocation,organizations=organizations,tick=tick)
            native_ref={'kind':'Evidence','id':organization_id+'-'+task_digest(scope)+'-actual-native-opportunity','version':'1'}
            evidence=[r['projection'] for r in saved['source_reading'] if r['ref']==native_ref]
            if (record['record_sha256']!=task_digest({k:v for k,v in record.items() if k!='record_sha256'})
                    or record['identity']!=micro[0]['identity'] or record['result_sha256']!=data['micro_result_sha256']
                    or record['proposal_response_sha256']!=task_digest(proposal) or task_digest(op)!=scope['opportunity_sha256']
                    or record['context']!=invocation['context'] or record['action_input']!=invocation['action_input']
                    or record['observed']['scope']!=scope
                    or record['observed']['native_request_sha256']!=task_digest(record['native_request'])
                    or record['observed']['opportunity']!=op or len(evidence)!=1
                    or evidence[0]['content_hash']!=task_digest(record['observed'])
                    or proposal['data']!={'selected_concept':op}
                    or any(op[k]!=data[k] for k in ('region','project_type','budget','planned_duration'))):
                raise TaskConflict('Owner opportunity history changes its original opportunity or actual native consequence')
            origins.append({'event_id':event['event_id'],'project_id':project.project_id,'tick':event['tick'],
                'organization_id':organization_id,'native_owner_opportunity_scope':scope,
                'micro_task_key':data['micro_task_key'],'micro_result_sha256':data['micro_result_sha256'],
                'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final)})
        if len({r['event_id'] for r in origins})!=len(origins):raise TaskConflict('Owner history repeats an actual project creation')
        return sorted(origins,key=lambda r:(r['tick'],r['project_id'],r['event_id']))
