"""Authenticate received candidates, original private A03 calculations and consequences."""
from copy import deepcopy
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def one(rows, predicate, message):
    result = [r for r in rows if predicate(r)]
    if len(result) != 1:
        raise TaskConflict(message)
    return result[0]


def valid(row):
    if row.get('record_sha256') != task_digest({k:v for k,v in row.items() if k!='record_sha256'}):
        raise TaskConflict('Original pipeline source record changed')


def received_candidates(*, records, tasks, saved_results, snapshots, events, organization_id, tick,
                        run_id, simulation_id, authorize):
    """Read only current own received evaluations, never regenerate an opportunity.

    A positive individual final decision is not proof of project creation. The
    returned consequence is present only for the matching original event.
    """
    if type(tick) is not int or tick < 1 or not callable(authorize):
        raise TaskConflict('Pipeline reading requires current time and original private read authority')
    rows=[r for r in records if r['scope']['owner_id']==organization_id and r['scope']['tick']==tick]
    if not rows:
        raise TaskConflict('No actual own native candidates were received at this original time')
    result=[]
    for record in rows:
        valid(record);scope=record['scope'];request=record['native_request'];op=request['inputs']['opportunity']
        identity=TaskIdentity(**record['identity'])
        expected=f"OPPORTUNITY-{tick}-{organization_id}-{op['region']}-{op['project_type']}-{int(op['budget'])}"
        if (record['state']!='formed' or record.get('terminal_stage')!='investment'
                or identity.run_id!=run_id or identity.organization_id!=organization_id or identity.role!='Owner'
                or identity.action_id!='OWN-A03' or identity.purpose!='action'
                or request['agent']['agent_id']!=organization_id or request['agent']['role']!='Owner'
                or request['operation']!='evaluate_project_opportunity'
                or request['inputs']['macro_environment']['current_tick']!=tick
                or scope!={'owner_id':organization_id,'tick':tick,'candidate_project_id':expected,'opportunity_sha256':task_digest(op)}
                or record['observed']['scope']!=scope or record['observed']['opportunity']!=op
                or record['observed']['native_request_sha256']!=task_digest(request)):
            raise TaskConflict('Pipeline source changes actual reception, Owner, candidate, clock or original action')
        saved=one(saved_results,lambda s:s['identity']==identity.as_dict(),'Original candidate A03 result missing')
        valid(saved);snapshot=snapshots[identity.key];authorize(saved,snapshot,tick=tick)
        micro=one(tasks,lambda t:t['identity']==identity.as_dict(),'Original candidate action task missing')
        if (micro['state']!='output_formed' or micro['output']!=saved['result']
                or micro['output_sha256']!=record['result_sha256'] or saved['result_sha256']!=task_digest(saved['result'])
                or saved['result_sha256']!=record['result_sha256'] or saved['source_reading_sha256']!=task_digest(saved['source_reading'])
                or saved['result']['kind']!='completed' or record['context']!=snapshot['context']
                or record['action_input']!=snapshot['action_input'] or snapshot['identity']!=identity.as_dict()
                or identity.context_sha256!=task_digest(snapshot['context']) or identity.input_sha256!=task_digest(snapshot['action_input'])):
            raise TaskConflict('Pipeline source changes original invocation, calculation or result')
        evidence=one(saved['source_reading'],lambda s:s['ref']['kind']=='Evidence'
            and s['ref']['id']==organization_id+'-'+task_digest(scope)+'-actual-native-opportunity',
            'Original candidate source evidence missing')['projection']
        if evidence['content_hash']!=task_digest(record['observed']):
            raise TaskConflict('Pipeline candidate was not bound into original micro reading')
        proposals=[t for t in tasks if t['identity']['organization_id']==organization_id and t['identity']['purpose']=='propose'
            and t['identity']['action_id']=='evaluate_project_opportunity' and (t.get('output') or {}).get('factors',{}).get('native_owner_opportunity_scope')==scope]
        proposal=one(proposals,lambda t:True,'Original candidate proposal missing')
        p=proposal['output'];pi=TaskIdentity(**proposal['identity'])
        if (proposal['state']!='output_formed' or proposal['output_sha256']!=task_digest(p)
                or pi.run_id!=run_id or pi.input_sha256!=task_digest({'run_id':run_id,'versions':pi.versions,'request':request})
                or pi.context_sha256!=task_digest({'simulation_id':simulation_id,'request':request})
                or record['proposal_response_sha256']!=task_digest(p) or p['data']!={'selected_concept':op}
                or p['action_type']!='initiate_project' or p['factors']['micro_action_id']!='OWN-A03'
                or p['factors']['micro_task_key']!=identity.key or p['factors']['micro_result_sha256']!=saved['result_sha256']):
            raise TaskConflict('Pipeline reception differs from actual original proposal transport')
        final=one(tasks,lambda t:t['identity']['organization_id']==organization_id and t['identity']['purpose']=='decide'
            and t['identity']['action_id']=='owner_project_opportunity'
            and (t.get('output') or {}).get('data',{}).get('native_owner_opportunity_scope')==scope,'Original candidate final missing')
        f=final['output'];fi=TaskIdentity(**final['identity']);choice=saved['result']['payload']['choice'];accepted=choice=='invest'
        if (choice not in {'invest','reject','authorize_preparation'} or final['state']!='output_formed'
                or fi.run_id!=run_id or fi.role!='Owner' or f['agent_id']!=organization_id or f['data']['micro_action_id']!='OWN-A03'
                or final['output_sha256']!=task_digest(f) or f['data']['micro_task_key']!=identity.key
                or f['data']['micro_result_sha256']!=saved['result_sha256']
                or f['data']['proposal_response_sha256']!=task_digest(p) or f['decision']!=accepted or p['accepted']!=accepted
                or f['action_type']!=('initiate_project' if accepted else 'defer_project')):
            raise TaskConflict('Pipeline source substitutes an unresolved or different individual decision')
        consequences=[e for e in events if e['agent_id']==organization_id and e['tick']==tick
            and e['event_type'] in {'project_opportunity_initiated','project_opportunity_declined'}
            and e['data'].get('decision_factors',{}).get('native_owner_opportunity_scope')==scope]
        if len(consequences)>1:
            raise TaskConflict('Candidate has ambiguous original native consequences')
        consequence=deepcopy(consequences[0]) if consequences else None
        if consequence is not None and consequence['data']['decision_factors'].get('micro_task_key')!=identity.key:
            raise TaskConflict('Native candidate consequence belongs to a different private result')
        result.append({'scope':deepcopy(scope),'native_opportunity':deepcopy(op),'native_request_sha256':task_digest(request),
            'micro_task_key':identity.key,'micro_identity':identity.as_dict(),'micro_result_sha256':saved['result_sha256'],
            'source_reading_sha256':saved['source_reading_sha256'],'choice':choice,
            'proposal_response_sha256':task_digest(p),'final_response_sha256':task_digest(f),
            'actual_native_consequence':consequence,'actually_created_project':bool(consequence and consequence['event_type']=='project_opportunity_initiated')})
    if len({task_digest(r['scope']) for r in result})!=len(result):
        raise TaskConflict('Duplicate original received candidate scope')
    # The frozen generator emits one round per tick. Its real global event
    # supplies the expected received set size; this is not a generated count.
    rounds=[e for e in events if e['agent_id']==organization_id and e['tick']==tick
        and e['event_type'] in {'project_opportunity_initiated','project_opportunity_declined'}]
    if not rounds or any(e['data']['candidate_opportunity_count']!=len(result) for e in rounds):
        raise TaskConflict('Received candidate set is incomplete for the actual original generation round')
    return sorted(result,key=lambda r:r['scope']['candidate_project_id'])
