"""Authenticate Contractor's own earlier A05 selections for its private preference."""
import json

from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def prior_contractor_supply_selections(assembly,*,organization_id,tick,read_guard,query_original=None):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    from integration.supplier_order_native_feedback import project_supply_event
    if not callable(read_guard):raise TaskConflict('Contractor supply history requires its original source guard')
    with read_guard():
        assembly._validate_components();engine,client=assembly.engine,assembly.client
        if client.organization_roles.get(organization_id)!='Contractor' or type(tick) is not int or tick!=engine.current_tick:
            raise TaskConflict('Contractor history changes its actual own identity or current clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id);history=[]
        for row in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=row['payload']
            if payload['event_type']!='supplier_selected' or payload['tick']>=tick:continue
            project=engine.projects.get(payload['project_id'])
            events=[] if project is None else [e for e in project.event_log if e['event_id']==row['event_id']]
            if len(events)!=1:raise TaskConflict('Contractor history lost its original actual selection event')
            event=events[0];expected=project_supply_event(AgentObservationV1.model_validate(event),client.organization_roles)
            if (project.selected_contractor_id!=organization_id or organization_id not in expected
                    or payload!=expected[organization_id]):
                raise TaskConflict('Contractor history substitutes its original selection or private recipient')
            data=payload['data'];scope=data['native_supply_scope']
            proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose' and t['identity']['action_id']=='select_supplier'
                and t['state']=='output_formed' and t['output'].get('factors',{}).get('native_supply_scope')==scope]
            finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide' and t['identity']['action_id']=='contractor_supplier_selection'
                and t['state']=='output_formed' and t['output'].get('data',{}).get('native_supply_scope')==scope]
            micro=[t for t in tasks if t['identity']['purpose']=='action' and t['identity']['action_id']=='CONTRACTOR-A05'
                and t['state']=='output_formed' and TaskIdentity(**t['identity']).key==data['micro_task_key']]
            if (len(proposals)!=1 or len(finals)!=1 or len(micro)!=1 or data['micro_action_id']!='CONTRACTOR-A05'
                    or scope!={'project_id':project.project_id,'contractor_id':organization_id,'tick':event['tick']}
                    or proposals[0]['accepted'] is not True or finals[0]['decision'] is not True
                    or proposals[0]['data'].get('selected_supplier_id')!=data['supplier_id']
                    or finals[0]['data'].get('selected_supplier_id')!=data['supplier_id']
                    or data['proposal_response_sha256']!=task_digest(proposals[0])
                    or finals[0]['data'].get('proposal_response_sha256')!=data['proposal_response_sha256']
                    or micro[0]['output']['kind']!='completed' or micro[0]['output']['payload']['choice']!='accept_supply_offer'
                    or micro[0]['output_sha256']!=data['micro_result_sha256'] or task_digest(micro[0]['output'])!=data['micro_result_sha256']
                    or any(data[k]!=proposals[0]['factors'].get(k) or data[k]!=finals[0]['data'].get(k)
                        for k in ('micro_action_id','micro_task_key','micro_result_sha256'))):
                raise TaskConflict('Contractor history changes its actual original A05, native proposal or final confirmation')
            with client.tasks._lock:
                raw=client.tasks._db.execute('SELECT record FROM contractor_planning_results WHERE task_key=?',(data['micro_task_key'],)).fetchone()
            saved=None if raw is None else json.loads(raw[0])
            if (saved is None or saved['record_sha256']!=task_digest({k:v for k,v in saved.items() if k!='record_sha256'})
                    or saved['identity']!=micro[0]['identity'] or saved['result']!=micro[0]['output']
                    or saved['result_sha256']!=data['micro_result_sha256']
                    or saved['audit'].get('input_sha256')!=micro[0]['identity']['input_sha256']
                    or saved['audit'].get('result_sha256')!=data['micro_result_sha256']
                    or saved['source_reading_sha256']!=task_digest(saved['source_reading'])):
                raise TaskConflict('Contractor history lost its actual original saved procurement sources')
            offers=[r['projection'] for r in saved['source_reading'] if r['ref']==micro[0]['output']['payload']['offer_ref']]
            if len(offers)!=1 or offers[0]['supplier_id']!=data['supplier_id']:
                raise TaskConflict('Contractor history substitutes the original accepted offer Supplier')
            history.append({'event_id':row['event_id'],'project_id':project.project_id,'contractor_id':organization_id,
                'supplier_id':data['supplier_id'],'tick':event['tick'],'micro_task_key':data['micro_task_key'],
                'micro_result_sha256':data['micro_result_sha256'],'proposal_response_sha256':data['proposal_response_sha256']})
        if len({r['event_id'] for r in history})!=len(history):raise TaskConflict('Contractor history repeats the same actual selection')
        if query_original is not None:
            from integration.supply_native_outcome_query import reconcile_supply_history
            reconcile_supply_history(query_original,history,tasks,tick)
        return sorted(history,key=lambda r:(r['tick'],r['project_id'],r['event_id']))
