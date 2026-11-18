"""Recipient-scoped regulatory willingness; never a case filing or permit."""
from copy import deepcopy

from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from integration.government_history_authority import authorize_government_history


def project_government_event(observation,organization_roles):
    if (not observation.committed or not isinstance(organization_roles,dict)
            or organization_roles.get(observation.agent_id)!='Government'):
        return {}
    if observation.event_type!='regulatory_review_decision':
        from integration.government_approval_native_feedback import project_approval_event
        return project_approval_event(observation,organization_roles)
    factors=observation.data.get('decision_factors',{})
    if factors.get('micro_action_id')!='GOV-A02':return {}
    fields=('government_id','purpose','action_type','accepted')
    data={k:deepcopy(observation.data[k]) for k in fields if k in observation.data}
    for k in ('micro_action_id','micro_task_key','micro_result_sha256','native_government_scope','proposal_response_sha256'):
        if k in observation.data:data[k]=deepcopy(observation.data[k])
        elif k in factors:data[k]=deepcopy(factors[k])
    return {observation.agent_id:{'event_type':observation.event_type,'tick':observation.tick,
        'project_id':observation.project_id,'agent_id':observation.agent_id,'committed':True,'data':data}}


def prior_review_decisions(assembly,*,organization_id,tick,read_guard,organizations=None):
    """Authenticate earlier own willingness; never infer filing or permission."""
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    if not callable(read_guard):raise TaskConflict('Regulatory memory requires its original engine guard')
    with read_guard():
        assembly._validate_components();client,engine=assembly.client,assembly.engine
        if (client.organization_roles.get(organization_id)!='Government' or type(tick) is not int
                or tick!=engine.current_tick):
            raise TaskConflict('Regulatory memory changes its own organization or current native clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id)
        origins=[]
        for entry in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=entry['payload']
            if payload['event_type']!='regulatory_review_decision' or payload['tick']>=tick:continue
            project=engine.projects.get(payload['project_id'])
            events=[] if project is None else [e for e in project.event_log if e['event_id']==entry['event_id']]
            if len(events)!=1:raise TaskConflict('Regulatory memory lost its original event')
            event=events[0]
            expected=project_government_event(AgentObservationV1.model_validate(event),client.organization_roles)
            if (event['event_type']!='regulatory_review_decision' or event['agent_id']!=organization_id
                    or event['data'].get('government_id')!=organization_id
                    or organization_id not in expected or task_digest(payload)!=task_digest(expected[organization_id])):
                raise TaskConflict('Regulatory memory substitutes its original event or private recipient')
            data=payload['data'];factors=event['data'].get('decision_factors',{})
            # Failed/deferred transport is an actual event, but it does not
            # confirm that the original micro willingness was executed.
            if factors.get('decision_error') or 'proposal_response_sha256' not in data:continue
            assignment_purpose='completion_review_assignment' if event['data'].get('purpose')=='completion inspection' else 'review_assignment'
            scope={'project_id':project.project_id,'tick':event['tick'],'purpose':assignment_purpose}
            if data.get('native_government_scope')!=scope or type(data.get('accepted')) is not bool:
                raise TaskConflict('Regulatory memory changes its original project, time or willingness')
            proposal=[t for t in tasks if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='consider_review_assignment' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_government_scope')==scope]
            final=[t for t in tasks if t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='government_review_assignment' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_government_scope')==scope]
            if len(proposal)!=1 or len(final)!=1:
                raise TaskConflict('Regulatory memory lost its original proposal or confirmation')
            proposal,final=proposal[0]['output'],final[0]['output']
            fields=('micro_action_id','micro_task_key','micro_result_sha256','native_government_scope')
            if (data['proposal_response_sha256']!=task_digest(proposal)
                    or final['data'].get('proposal_response_sha256')!=task_digest(proposal)
                    or any(data.get(k)!=proposal['factors'].get(k) or data.get(k)!=final['data'].get(k) for k in fields)
                    or proposal['accepted']!=final['decision'] or proposal['accepted']!=data['accepted']
                    or proposal['action_type']!=final['action_type'] or proposal['action_type']!=data.get('action_type')):
                raise TaskConflict('Regulatory memory substitutes its actual confirmed micro willingness')
            micro=[t for t in tasks if t['identity']['purpose']=='action' and t['identity']['action_id']=='GOV-A02'
                and TaskIdentity(**t['identity']).key==data.get('micro_task_key') and t['state']=='output_formed'
                and t['output_sha256']==data.get('micro_result_sha256')]
            choice='accept_for_processing' if data['accepted'] else 'decline_processing'
            action='accept_regulatory_review' if data['accepted'] else 'defer_regulatory_review'
            if (len(micro)!=1 or micro[0]['output']['kind']!='completed'
                    or task_digest(micro[0]['output'])!=data['micro_result_sha256']
                    or micro[0]['output']['payload']['choice']!=choice or data['action_type']!=action):
                raise TaskConflict('Regulatory memory lost its original completed GOV-A02 result')
            authorize_government_history(assembly,TaskIdentity(**micro[0]['identity']),
                organizations=organizations,tick=tick)
            origins.append({'event_id':entry['event_id'],'project_id':project.project_id,'tick':event['tick'],
                'organization_id':organization_id,'accepted':data['accepted'],'action_type':action,
                'micro_task_key':data['micro_task_key'],'micro_result_sha256':data['micro_result_sha256'],
                'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final)})
        if len({r['event_id'] for r in origins})!=len(origins):
            raise TaskConflict('Regulatory memory repeats the same actual event')
        return sorted(origins,key=lambda r:(r['tick'],r['project_id'],r['event_id']))
