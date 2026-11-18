"""Authenticate own actual native approval outcomes before later private reads."""
import json
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from integration.government_history_authority import authorize_government_history


def project_approval_event(observation,organization_roles):
    from copy import deepcopy
    if (not observation.committed or organization_roles.get(observation.agent_id)!='Government'
            or observation.event_type not in {'approval_approved','approval_rejected'}):return {}
    decision=observation.data.get('individual_decision',{});factors=decision.get('decision_factors',{})
    if factors.get('micro_action_id')!='GOV-A07':return {}
    data={k:deepcopy(observation.data[k]) for k in ('reviewer_id','result') if k in observation.data}
    data.update({k:deepcopy(decision[k]) for k in ('action_type','accepted') if k in decision})
    for k in ('micro_action_id','micro_task_key','micro_result_sha256','review_micro_task_key',
            'review_micro_result_sha256','native_government_scope','proposal_response_sha256'):
        if k in decision:data[k]=deepcopy(decision[k])
        elif k in factors:data[k]=deepcopy(factors[k])
    return {observation.agent_id:{'event_type':observation.event_type,'tick':observation.tick,
        'project_id':observation.project_id,'agent_id':observation.agent_id,'committed':True,'data':data}}


def prior_approval_decisions(assembly,*,organization_id,tick,read_guard,
        include_current=False,decision_task_key=None,organizations=None):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    if not callable(read_guard):raise TaskConflict('Approval memory requires its original engine guard')
    if type(include_current) is not bool or (decision_task_key is not None
            and (not isinstance(decision_task_key,str) or not decision_task_key)):
        raise TaskConflict('Approval outcome selection requires explicit current-time policy and original key')
    with read_guard():
        assembly._validate_components();client,engine=assembly.client,assembly.engine
        if client.organization_roles.get(organization_id)!='Government' or type(tick) is not int or engine.current_tick!=tick:
            raise TaskConflict('Approval memory changes its own organization or native clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id);origins=[]
        for entry in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=entry['payload']
            if payload['event_type'] not in {'approval_approved','approval_rejected'}:continue
            if payload['tick']>tick or (payload['tick']==tick and not include_current):continue
            if decision_task_key is not None and payload['data'].get('micro_task_key')!=decision_task_key:continue
            project=engine.projects.get(payload['project_id'])
            events=[] if project is None else [e for e in project.event_log if e['event_id']==entry['event_id']]
            if len(events)!=1:raise TaskConflict('Approval memory lost its original event')
            event=events[0];expected=project_approval_event(AgentObservationV1.model_validate(event),client.organization_roles)
            if (event['agent_id']!=organization_id or event['data'].get('reviewer_id')!=organization_id
                    or organization_id not in expected or task_digest(payload)!=task_digest(expected[organization_id])):
                raise TaskConflict('Approval memory substitutes its original event or private recipient')
            data=payload['data'];scope={'project_id':project.project_id,'tick':event['tick'],'purpose':'design_approval'}
            if event['data']['individual_decision'].get('decision_factors',{}).get('decision_error'):continue
            proposal=[t['output'] for t in tasks if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='decide_approval' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_government_scope')==scope]
            final=[t['output'] for t in tasks if t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='government_design_approval' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_government_scope')==scope]
            if len(proposal)!=1 or len(final)!=1:raise TaskConflict('Approval memory lost original proposal/final')
            proposal,final=proposal[0],final[0]
            fields=('micro_action_id','micro_task_key','micro_result_sha256','review_micro_task_key',
                'review_micro_result_sha256','native_government_scope')
            if (data.get('native_government_scope')!=scope or data.get('proposal_response_sha256')!=task_digest(proposal)
                    or final['data'].get('proposal_response_sha256')!=task_digest(proposal)
                    or any(data.get(k)!=proposal['factors'].get(k) or data.get(k)!=final['data'].get(k) for k in fields)
                    or proposal['accepted']!=final['decision'] or proposal['accepted']!=data.get('accepted')
                    or proposal['action_type']!=final['action_type'] or proposal['action_type']!=data.get('action_type')
                    or (event['event_type']=='approval_approved')!=proposal['accepted']):
                raise TaskConflict('Approval memory substitutes its actual confirmed micro proposal')
            for action,key,sha,choice in [('GOV-A04','review_micro_task_key','review_micro_result_sha256','assess'),
                    ('GOV-A07','micro_task_key','micro_result_sha256',
                        'approve' if proposal['accepted'] else 'defer_by_procedure')]:
                rows=[t for t in tasks if t['identity']['purpose']=='action' and t['identity']['action_id']==action
                    and t['state']=='output_formed' and TaskIdentity(**t['identity']).key==data.get(key)]
                if (len(rows)!=1 or rows[0]['output_sha256']!=data.get(sha) or task_digest(rows[0]['output'])!=data.get(sha)
                        or rows[0]['output']['kind']!='completed' or rows[0]['output']['payload']['choice']!=choice):
                    raise TaskConflict('Approval memory lost its completed original review/decision')
                table={'GOV-A04':'government_review_results','GOV-A07':'government_decision_results'}[action]
                with client.tasks._lock:
                    raw=client.tasks._db.execute('SELECT record FROM '+table+' WHERE task_key=?',(data[key],)).fetchone()
                saved=None if raw is None else json.loads(raw[0])
                if (saved is None or saved['record_sha256']!=task_digest({k:v for k,v in saved.items() if k!='record_sha256'})
                        or saved['identity']!=rows[0]['identity'] or saved['result']!=rows[0]['output']
                        or saved['result_sha256']!=data[sha] or saved['audit'].get('result_sha256')!=data[sha]
                        or saved['audit'].get('input_sha256')!=rows[0]['identity']['input_sha256']
                        or saved['source_reading_sha256']!=task_digest(saved['source_reading'])):
                    raise TaskConflict('Approval memory lost its original saved review/decision sources')
                authorize_government_history(assembly,TaskIdentity(**rows[0]['identity']),
                    organizations=organizations,tick=tick,saved=saved)
            origins.append({'event_id':event['event_id'],'project_id':project.project_id,'tick':event['tick'],
                'organization_id':organization_id,'accepted':data['accepted'],'action_type':data['action_type'],
                **{k:data[k] for k in ('micro_task_key','micro_result_sha256','review_micro_task_key','review_micro_result_sha256')},
                'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final)})
        from integration.government_completion_native_feedback import own_completion_outcomes
        origins.extend(own_completion_outcomes(assembly,organization_id=organization_id,tick=tick,
            include_current=include_current,decision_task_key=decision_task_key,organizations=organizations))
        if len({r['event_id'] for r in origins})!=len(origins):raise TaskConflict('Approval memory repeats one original event')
        return sorted(origins,key=lambda r:(r['tick'],r['project_id'],r['event_id']))
