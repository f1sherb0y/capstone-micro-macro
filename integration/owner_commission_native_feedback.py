"""Own actual consultant selections, without other firms' private intake data."""
from copy import deepcopy
import json

from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

ROLE_FIELD={'Architect':'architect_id','Engineer':'engineer_id','QS':'qs_id'}


def owner_commission_recipients(observation,organization_roles):
    owner=observation.data.get('owner_id')
    if (not observation.committed or observation.event_type!='consultant_team_appointed'
            or observation.agent_id!=owner or organization_roles.get(owner)!='Owner'):return {}
    choices={}
    for role in ROLE_FIELD:
        selected=observation.data.get('owner_selections',{}).get(role.lower(),{})
        factors=selected.get('decision_factors',{})
        if factors.get('micro_action_id')!='OWN-A04':continue
        choices[role]={'accepted':selected.get('accepted'),'selected_agent_id':selected.get('selected_agent_id'),
            'proposal_response_sha256':selected.get('proposal_response_sha256'),
            **{k:deepcopy(factors.get(k)) for k in ('micro_action_id','micro_task_key','micro_result_sha256','native_professional_scope')}}
    return {owner:{'owner_id':owner,'owner_commissions':choices}} if choices else {}


def prior_owner_commissions(assembly,*,organization_id,role,tick,read_guard):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    if not callable(read_guard):raise TaskConflict('Owner commission history requires its original authority guard')
    with read_guard():
        assembly._validate_components();client,engine=assembly.client,assembly.engine
        if client.organization_roles.get(organization_id)!='Owner' or role not in ROLE_FIELD or type(tick) is not int or tick!=engine.current_tick:
            raise TaskConflict('Owner commission history changes its current original identity or clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id);origins=[]
        for entry in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=entry['payload']
            if payload['event_type']!='consultant_team_appointed' or payload['tick']>=tick:continue
            choices=payload['data'].get('owner_commissions',{})
            if role not in choices:continue
            project=engine.projects.get(payload['project_id'])
            events=[] if project is None else [e for e in project.event_log if e['event_id']==entry['event_id']]
            if len(events)!=1:raise TaskConflict('Owner commission history lost its actual original team event')
            event=events[0];expected=owner_commission_recipients(AgentObservationV1.model_validate(event),client.organization_roles)
            if (project.owner_id!=organization_id or organization_id not in expected or payload['data']!=expected[organization_id]
                    or payload['agent_id']!=organization_id or payload['tick']!=event['tick'] or payload['committed'] is not True):
                raise TaskConflict('Owner commission history substitutes its original event or private recipient')
            result=choices[role];scope={'project_id':project.project_id,'tick':event['tick'],'role':role}
            selected=result['selected_agent_id'];accepted=result['accepted']
            proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose' and t['identity']['action_id']=='select_appointment'
                and t['state']=='output_formed' and t['output']['factors'].get('native_professional_scope')==scope]
            finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide' and t['identity']['action_id']=='owner_select_'+role.lower()
                and t['state']=='output_formed' and t['output']['data'].get('native_professional_scope')==scope]
            micro=[t for t in tasks if t['identity']['purpose']=='action' and t['identity']['action_id']=='OWN-A04'
                and t['state']=='output_formed' and TaskIdentity(**t['identity']).key==result['micro_task_key']]
            if len(proposals)!=1 or len(finals)!=1 or len(micro)!=1:
                raise TaskConflict('Owner commission history lost its original proposal, final or micro result')
            proposal,final=proposals[0],finals[0];identity=TaskIdentity(**micro[0]['identity'])
            if (result['native_professional_scope']!=scope or proposal['accepted']!=accepted or final['decision']!=accepted
                    or proposal['data'].get('selected_agent_id')!=selected or final['data'].get('selected_agent_id')!=selected
                    or event['data'].get(ROLE_FIELD[role])!=selected
                    or proposal['action_type']!=final['action_type'] or final['action_type']!='select_'+role.lower()
                    or task_digest(proposal)!=result['proposal_response_sha256']
                    or final['data'].get('proposal_response_sha256')!=result['proposal_response_sha256']
                    or any(result[k]!=proposal['factors'].get(k) or result[k]!=final['data'].get(k)
                        for k in ('micro_action_id','micro_task_key','micro_result_sha256','native_professional_scope'))
                    or micro[0]['output_sha256']!=result['micro_result_sha256'] or task_digest(micro[0]['output'])!=result['micro_result_sha256']
                    or micro[0]['output']['kind']!='completed'
                    or micro[0]['output']['payload']['choice']!=('accept' if accepted else 'reject_all')):
                raise TaskConflict('Owner commission history changes the original confirmed selection or actual consequence')
            with client.tasks._lock:
                row=client.tasks._db.execute('SELECT record FROM owner_commission_results WHERE task_key=?',(identity.key,)).fetchone()
                technical=[json.loads(v) for v, in client.tasks._db.execute(
                    'SELECT value FROM metadata WHERE key LIKE ?',('owner_commission_native_request:%',))]
            saved=None if row is None else json.loads(row[0]);records=[r for r in technical if r.get('identity')==identity.as_dict()]
            if saved is None or len(records)!=1:raise TaskConflict('Owner commission history lost its original sources')
            record=records[0];snapshot=InvocationSnapshotStore(client.tasks).get(identity)
            native=[r['projection'] for r in saved['source_reading'] if r['ref']['kind']=='Evidence'
                and r['projection'].get('locator')=='actual-owner-commission-request-and-own-history']
            handoff=[r['projection'] for r in saved['source_reading'] if r['ref']['kind']=='Evidence'
                and r['projection'].get('locator')=='actual-independent-provider-intake-for-owner']
            if (saved['record_sha256']!=task_digest({k:v for k,v in saved.items() if k!='record_sha256'})
                    or saved['source_reading_sha256']!=task_digest(saved['source_reading'])
                    or saved['identity']!=identity.as_dict() or saved['result']!=micro[0]['output']
                    or saved['result_sha256']!=result['micro_result_sha256']
                    or saved['audit']['input_sha256']!=identity.input_sha256 or saved['audit']['result_sha256']!=result['micro_result_sha256']
                    or record['record_sha256']!=task_digest({k:v for k,v in record.items() if k!='record_sha256'})
                    or record['state']!='formed' or record['scope']!=scope or record['result_sha256']!=result['micro_result_sha256']
                    or record['proposal_response_sha256']!=task_digest(proposal)
                    or record['native_request']['agent']['agent_id']!=organization_id
                    or record['observed']['native_request_sha256']!=task_digest(record['native_request'])
                    or len(native)!=1 or native[0]['content_hash']!=task_digest(record['observed'])
                    or len(handoff)!=1 or handoff[0]['content_hash']!=task_digest(record['observed']['providers'])
                    or snapshot['context']['business_time']['offset']!=event['tick']
                    or snapshot['context']['scope']['ref']['id']!=project.project_id):
                raise TaskConflict('Owner commission history changes its original source, audit or invocation binding')
            if accepted and selected not in [r['provider_id'] for r in record['observed']['providers'] if r['accepted']]:
                raise TaskConflict('Owner commission history changes the independently accepting selected provider')
            origins.append({'event_id':event['event_id'],'project_id':project.project_id,'tick':event['tick'],
                'organization_id':organization_id,'role':role,'provider_id':selected,'accepted':accepted,
                'micro_task_key':identity.key,'micro_result_sha256':result['micro_result_sha256'],
                'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final)})
        if len({(r['event_id'],r['role']) for r in origins})!=len(origins):raise TaskConflict('Owner commission history repeats the same actual selection')
        return sorted(origins,key=lambda r:(r['tick'],r['project_id'],r['event_id']))
