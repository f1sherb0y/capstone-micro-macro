"""Read own actual completion outcomes, without fabricating delivered receipts.

The native success event has no agent or decision payload. Its recipient is
therefore authorized by the original own final request and reviewer assignment,
not by attributing that event to an invented Government actor.
"""
import json

from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from integration.government_history_authority import authorize_government_history


def _one(rows, message):
    if len(rows)!=1:raise TaskConflict(message)
    return rows[0]


def _saved_action(client,tasks,*,action,key,sha,choice):
    task=_one([t for t in tasks if t['identity']['purpose']=='action'
        and t['identity']['action_id']==action and TaskIdentity(**t['identity']).key==key
        and t['state']=='output_formed'], 'Completion memory lost its original micro task')
    tables={'GOV-A02':'government_intake_results','GOV-A04':'government_review_results',
        'GOV-A07':'government_decision_results'}
    with client.tasks._lock:
        raw=client.tasks._db.execute('SELECT record FROM '+tables[action]+' WHERE task_key=?',(key,)).fetchone()
    saved=None if raw is None else json.loads(raw[0])
    if (saved is None or task['output_sha256']!=sha or task_digest(task['output'])!=sha
            or task['output'].get('kind')!='completed' or task['output']['payload'].get('choice')!=choice
            or saved['record_sha256']!=task_digest({k:v for k,v in saved.items() if k!='record_sha256'})
            or saved['identity']!=task['identity'] or saved['result']!=task['output'] or saved['result_sha256']!=sha
            or saved['audit'].get('result_sha256')!=sha
            or saved['audit'].get('input_sha256')!=task['identity']['input_sha256']
            or saved['source_reading_sha256']!=task_digest(saved['source_reading'])):
        raise TaskConflict('Completion memory substitutes original micro result, audit or source reading')
    return saved


def _transport(tasks,scope,*,proposal_action,final_action,fields):
    proposal=_one([t['output'] for t in tasks if t['identity']['purpose']=='propose'
        and t['identity']['action_id']==proposal_action and t['state']=='output_formed'
        and t['output'].get('factors',{}).get('native_government_scope')==scope],
        'Completion memory needs one original own proposal')
    final=_one([t['output'] for t in tasks if t['identity']['purpose']=='decide'
        and t['identity']['action_id']==final_action and t['state']=='output_formed'
        and t['output'].get('data',{}).get('native_government_scope')==scope],
        'Completion memory needs one original own final response')
    if (final['data'].get('proposal_response_sha256')!=task_digest(proposal)
            or proposal['accepted']!=final['decision'] or proposal['action_type']!=final['action_type']
            or any(final['data'].get(k)!=proposal['factors'].get(k) for k in fields)):
        raise TaskConflict('Completion memory substitutes its original proposal or final confirmation')
    return proposal,final


def _record(client,*,prefix,scope,organization_id):
    with client.tasks._lock:
        records=[json.loads(v) for v, in client.tasks._db.execute(
            'SELECT value FROM metadata WHERE key LIKE ?',(prefix+'%',))]
    record=_one([r for r in records if r['scope']==scope
        and r['native_request']['agent']['agent_id']==organization_id],
        'Completion memory lost its original own workflow')
    original=record['native_request']
    if (record['record_sha256']!=task_digest({k:v for k,v in record.items() if k!='record_sha256'})
            or record['state']!='formed' or record['key']!=prefix+task_digest(
                [client.simulation_id,organization_id,scope,original['request_id']])):
        raise TaskConflict('Completion memory substitutes its original scoped workflow')
    return record


def _assignment(client,tasks,project,record,organization_id,decision_tick,*,assembly,organizations,read_tick):
    assignment=record['review_observed']['assignment'];scope=assignment['scope']
    if (set(scope)!={'project_id','tick','purpose'} or scope['project_id']!=project.project_id
            or scope['purpose']!='completion_review_assignment' or type(scope['tick']) is not int
            or not 1<=scope['tick']<=decision_tick
            or assignment!=record['decision_observed']['assignment']):
        raise TaskConflict('Completion memory substitutes original completion reviewer assignment')
    event=_one([e for e in project.event_log if e['event_id']==assignment['event_id']],
        'Completion memory lost its actual reviewer assignment event')
    if (event['event_type']!='regulatory_review_decision' or event['project_id']!=project.project_id
            or event['tick']!=scope['tick'] or event['agent_id']!=organization_id
            or event['data'].get('government_id')!=organization_id
            or event['data'].get('purpose')!='completion inspection'
            or event['data'].get('accepted') is not True):
        raise TaskConflict('Completion memory borrows another stage, time or reviewer')
    # The engagement may have been released by actual completion. Authenticate
    # its historical interval; do not require it to remain active at read time.
    if not any(e.agent_id==organization_id and e.role=='Government' and e.joined_at_tick==scope['tick']
            and (e.released_at_tick is None or e.released_at_tick>=decision_tick) for e in project.engagements):
        raise TaskConflict('Completion memory lacks its actual historical reviewer engagement')
    fields=('micro_action_id','micro_task_key','micro_result_sha256','native_government_scope')
    proposal,final=_transport(tasks,scope,proposal_action='consider_review_assignment',
        final_action='government_review_assignment',fields=fields)
    factors=event['data'].get('decision_factors',{});data={**factors,**event['data']}
    if (data.get('proposal_response_sha256')!=task_digest(proposal)
            or assignment['proposal_response_sha256']!=task_digest(proposal)
            or assignment['final_response_sha256']!=task_digest(final)
            or any(data.get(k)!=final['data'].get(k) for k in fields)
            or data.get('micro_action_id')!='GOV-A02' or proposal['accepted'] is not True
            or proposal['action_type']!='accept_regulatory_review'
            or data.get('action_type')!=proposal['action_type'] or factors.get('decision_error')):
        raise TaskConflict('Completion memory substitutes actual confirmed micro intake')
    saved=_saved_action(client,tasks,action='GOV-A02',key=assignment['micro_task_key'],
        sha=assignment['micro_result_sha256'],choice='accept_for_processing')
    authorize_government_history(assembly,TaskIdentity(**saved['identity']),
        organizations=organizations,tick=read_tick,saved=saved)
    intake=_record(client,prefix='government_intake_native_request:',scope=scope,organization_id=organization_id)
    intake_observed=assignment['intake_evidence']['observed']
    if (saved['result_sha256']!=data.get('micro_result_sha256')
            or assignment['micro_task_key']!=data.get('micro_task_key')
            or intake['identity']!=saved['identity'] or intake['result_sha256']!=saved['result_sha256']
            or intake['proposal_response_sha256']!=task_digest(proposal)
            or intake['observed']!=intake_observed
            or intake_observed['scope']!=scope
            or intake_observed['native_request_sha256']!=task_digest(intake['native_request'])
            or not any(r['ref']==assignment['intake_evidence']['ref']
                and r['projection'].get('content_hash')==task_digest(intake_observed) for r in saved['source_reading'])):
        raise TaskConflict('Completion memory substitutes its original intake handoff')
    return assignment


def own_completion_outcomes(assembly,*,organization_id,tick,include_current=False,decision_task_key=None,organizations=None):
    """Caller holds the original read guard and has checked organization/time."""
    client,engine=assembly.client,assembly.engine
    tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id)
    fields=('micro_action_id','micro_task_key','micro_result_sha256','review_micro_task_key',
        'review_micro_result_sha256','native_government_scope')
    origins=[];seen=set()
    for task in tasks:
        if (task['identity']['purpose']!='decide' or task['identity']['action_id']!='government_completion_approval'
                or task['state']!='output_formed'):continue
        final=task['output'];scope=final.get('data',{}).get('native_government_scope')
        if (not isinstance(scope,dict) or set(scope)!={'project_id','tick','purpose'}
                or scope['purpose']!='completion_approval' or type(scope['tick']) is not int):
            raise TaskConflict('Completion memory lost its exact original project/time scope')
        if scope['tick']>tick or (scope['tick']==tick and not include_current):continue
        if decision_task_key is not None and final.get('data',{}).get('micro_task_key')!=decision_task_key:continue
        if task_digest(scope) in seen:raise TaskConflict('Completion memory repeats one original final decision')
        seen.add(task_digest(scope))
        project=engine.projects.get(scope['project_id'])
        if project is None or final.get('agent_id')!=organization_id:
            raise TaskConflict('Completion memory changes its original own project or actor')
        proposal,checked_final=_transport(tasks,scope,proposal_action='decide_approval',
            final_action='government_completion_approval',fields=fields)
        if checked_final!=final:raise TaskConflict('Completion memory substitutes its original final response')
        accepted=proposal['accepted'];data=final['data']
        if (type(accepted) is not bool or data.get('micro_action_id')!='GOV-A07'
                or proposal['action_type']!=('approve' if accepted else 'request_revision')):
            raise TaskConflict('Completion memory substitutes its actual micro approval opinion')
        record=_record(client,prefix='government_approval_native_request:',scope=scope,organization_id=organization_id)
        original=record['native_request'];native_project=original.get('inputs',{}).get('project',{})
        if (original['operation']!='decide_approval' or native_project.get('current_stage')!='completion'
                or native_project.get('project_id')!=project.project_id
                or proposal.get('request_id')!=original['request_id']
                or task['identity']['request_id']!=final['request_id']+':regulatory-scope:'+task_digest(scope)
                or record['proposal_response_sha256']!=task_digest(proposal)):
            raise TaskConflict('Completion memory changes its original native approval request')
        assignment=_assignment(client,tasks,project,record,organization_id,scope['tick'],
            assembly=assembly,organizations=organizations,read_tick=tick)
        for stage,action,key,sha,choice in [
                ('review','GOV-A04','review_micro_task_key','review_micro_result_sha256','assess'),
                ('decision','GOV-A07','micro_task_key','micro_result_sha256','approve' if accepted else 'defer_by_procedure')]:
            saved=_saved_action(client,tasks,action=action,key=data[key],sha=data[sha],choice=choice)
            authorize_government_history(assembly,TaskIdentity(**saved['identity']),
                organizations=organizations,tick=tick,saved=saved)
            observed=record[stage+'_observed']
            if (saved['identity']!=record[stage+'_identity'] or saved['result_sha256']!=record[stage+'_result_sha256']
                    or observed['scope']!=scope or observed['native_request_sha256']!=task_digest(original)
                    or not any(r['ref']['kind']=='Evidence' and r['projection'].get('basis_kind')=='observed'
                        and r['projection'].get('content_hash')==task_digest(observed) for r in saved['source_reading'])):
                raise TaskConflict('Completion memory lost the actual native evidence read by its original processor')
        event=_one([e for e in project.event_log if e['tick']==scope['tick']
            and (e['event_type']=='project_completed' or (e['event_type']=='quality_issue'
                and e['agent_id']==organization_id and e['data'].get('completion_decision') is not None))],
            'Completion memory lacks one actual native execution outcome; diagnose original request')
        completed=event['event_type']=='project_completed'
        if event['project_id']!=project.project_id or (completed and not accepted):
            raise TaskConflict('Completion memory substitutes its actual native completion outcome')
        if not completed:
            decision=event['data']['completion_decision'];factors=decision.get('decision_factors',{})
            flattened={**factors,**decision}
            if (factors.get('decision_error') or decision.get('accepted')!=accepted
                    or decision.get('action_type')!=proposal['action_type']
                    or flattened.get('proposal_response_sha256')!=task_digest(proposal)
                    or any(flattened.get(k)!=data.get(k) for k in fields)):
                raise TaskConflict('Completion memory substitutes its actual rectification event')
        origins.append({'event_id':event['event_id'],'event_type':event['event_type'],'project_id':project.project_id,
            'tick':scope['tick'],'organization_id':organization_id,'accepted':accepted,'action_type':proposal['action_type'],
            'native_outcome':'completed' if completed else 'rectification_required','completed':completed,
            'assignment_event_id':assignment['event_id'],
            **{k:data[k] for k in fields if k not in {'micro_action_id','native_government_scope'}},
            'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final)})
    return origins
