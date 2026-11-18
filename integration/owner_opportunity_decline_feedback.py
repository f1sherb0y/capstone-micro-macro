"""Authenticate own native non-initiation outcomes; never count private candidates as events."""
from copy import deepcopy
import json

from integration.bank_financing_private import checked_result
from integration.owner_opportunity_native_feedback import project_owner_opportunity_event, authorize_owner_history
from integration.owner_opportunity_preparation import preparation_origin
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest


def prior_owner_declines(assembly,*,organization_id,tick,read_guard,workers,organizations=None):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    if not callable(read_guard):raise TaskConflict('Owner decline history requires its original source guard')
    with read_guard():
        assembly._validate_components();engine,client=assembly.engine,assembly.client
        agent=engine.agents.get(organization_id)
        if (client.organization_roles.get(organization_id)!='Owner' or agent is None or agent.role!='Owner'
                or type(tick) is not int or engine.current_tick!=tick or client.simulation_id!=engine.simulation_id):
            raise TaskConflict('Owner decline history changes its own original identity, run or clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id)
        with client.tasks._lock:
            records=[json.loads(v) for v, in client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ?',('owner_opportunity_native_request:%',))]
        origins=[]
        for row in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=row['payload']
            if payload['event_type']!='project_opportunity_declined' or payload['tick']>=tick:continue
            actual=[e for e in engine.events.events if e.event_id==row['event_id']]
            if len(actual)!=1:raise TaskConflict('Owner decline history lost its unique actual native event')
            event=actual[0];original=event.model_dump(mode='json')
            expected=project_owner_opportunity_event(AgentObservationV1.model_validate(original),client.organization_roles)
            if (event.agent_id!=organization_id or event.project_id is not None
                    or organization_id not in expected or payload!=expected[organization_id]):
                raise TaskConflict('Owner decline history substitutes an event, project or private recipient')
            data=payload['data'];scope=data.get('native_owner_opportunity_scope');action=data.get('micro_action_id')
            if (action not in workers or not isinstance(scope,dict) or scope.get('owner_id')!=organization_id
                    or scope.get('tick')!=event.tick or data.get('individual_accepted') is not False
                    or data.get('individual_action')!='defer_project'):
                raise TaskConflict('Owner decline event lacks its exact original no-initiation decision')
            proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='evaluate_project_opportunity' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_owner_opportunity_scope')==scope]
            finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='owner_project_opportunity' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_owner_opportunity_scope')==scope]
            technical=[r for r in records if r.get('state')=='formed' and r.get('scope')==scope]
            if len(proposals)!=1 or len(finals)!=1 or len(technical)!=1:
                raise TaskConflict('Owner decline history lost original proposal, confirmation or invocation')
            proposal,final,record=proposals[0],finals[0],technical[0]
            fields=('micro_action_id','micro_task_key','micro_result_sha256','native_owner_opportunity_scope')
            if (proposal['accepted'] is not False or proposal['action_type']!='initiate_project'
                    or final['decision'] is not False or final['action_type']!='defer_project'
                    or any(data.get(k)!=proposal['factors'].get(k) or data.get(k)!=final['data'].get(k) for k in fields)
                    or final['data'].get('proposal_response_sha256')!=task_digest(proposal)
                    or record['proposal_response_sha256']!=task_digest(proposal)
                    or record['record_sha256']!=task_digest({k:v for k,v in record.items() if k!='record_sha256'})):
                raise TaskConflict('Owner decline substitutes its original proposal or bounded confirmation')
            identity=TaskIdentity(**record['identity']);saved=checked_result(workers[action],identity)
            invocation=InvocationSnapshotStore(client.tasks).get(identity)
            authorize_owner_history(saved,invocation,organizations=organizations,tick=tick)
            choice=saved['result']['payload']['choice'];stage=record.get('terminal_stage','investment')
            if (identity.organization_id!=organization_id or identity.run_id!=client.run_id or identity.action_id!=action
                    or identity.key!=data['micro_task_key'] or saved['result_sha256']!=data['micro_result_sha256']
                    or record['result_sha256']!=saved['result_sha256']
                    or invocation['context']!=record['context'] or invocation['action_input']!=record['action_input']
                    or (action=='OWN-A01' and (choice!='ignore' or stage!='observation'))
                    or (action=='OWN-A16' and (choice!='no_proposal' or stage!='proposal'))
                    or (action=='OWN-A03' and (choice not in {'reject','authorize_preparation','study_more'} or stage!='investment'))):
                raise TaskConflict('Owner decline history changes its original deciding micro result or stage')
            observed=record['observed']['native_context'] if action in {'OWN-A01','OWN-A16'} else record['observed']
            request=record['native_request'];op=request['inputs']['opportunity']
            native={'kind':'Evidence','id':organization_id+'-'+task_digest(scope)+'-actual-native-opportunity','version':'1'}
            evidence=[r['projection'] for r in saved['source_reading'] if r['ref']==native]
            if (len(evidence)!=1 or evidence[0]['content_hash']!=task_digest(observed)
                    or observed['scope']!=scope or observed['native_request_sha256']!=task_digest(request)
                    or observed['opportunity']!=op or task_digest(op)!=scope.get('opportunity_sha256')
                    or proposal['data']!={'selected_concept':op}
                    or any(data.get(k)!=op[k] for k in ('region','project_type','budget','planned_duration'))):
                raise TaskConflict('Owner decline history substitutes its original current candidate or evidence')
            study={}
            if action=='OWN-A03' and choice=='study_more':
                from integration.owner_opportunity_study import prior_study_authorization
                study={'study_authorization':prior_study_authorization(record,saved,workers.get('OWN-A02'),InvocationSnapshotStore(client.tasks),
                    organizations=organizations,tick=tick,service_workers=workers)}
            if action=='OWN-A03' and choice=='authorize_preparation':
                study={'preparation_authorization':preparation_origin(saved,invocation,organizations=organizations,worker=workers[action])}
            origins.append({'event_id':event.event_id,'tick':event.tick,'organization_id':organization_id,
                'native_owner_opportunity_scope':deepcopy(scope),'opportunity':deepcopy(op),
                'micro_action_id':action,'micro_choice':choice,'micro_task_key':identity.key,
                'micro_result_sha256':saved['result_sha256'],'source_event_sha256':task_digest(original),
                'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final),**study})
        if len({r['event_id'] for r in origins})!=len(origins):raise TaskConflict('Owner decline history repeats an event')
        return sorted(origins,key=lambda r:(r['tick'],r['event_id']))
