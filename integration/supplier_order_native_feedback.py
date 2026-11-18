"""Own native supply willingness/selection, without detailed order or stock facts."""
from copy import deepcopy

from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def project_supply_event(observation,roles):
    if not observation.committed or not isinstance(roles,dict):return {}
    data=observation.data;org=observation.agent_id
    if roles.get(org)!='Supplier':return {}
    if observation.event_type=='supplier_order_decision':
        if data.get('micro_action_id') not in {'SUPPLIER-A01','SUPPLIER-A02','SUPPLIER-A03','SUPPLIER-A04'}:return {}
        fields=('action_type','accepted','offer_score','native_supply_scope','micro_action_id',
            'micro_task_key','micro_result_sha256','proposal_response_sha256')
        own={k:deepcopy(data[k]) for k in fields if k in data}
    elif observation.event_type=='supplier_selected' and data.get('supplier_id')==org:
        own={k:deepcopy(data[k]) for k in ('supplier_id','contractor_id') if k in data}
        own['selected']=True
    else:return {}
    result={org:{'event_type':observation.event_type,'tick':observation.tick,'project_id':observation.project_id,
        'agent_id':org,'committed':True,'data':own}}
    selection=data.get('contractor_decision',{});contractor=data.get('contractor_id')
    if (observation.event_type=='supplier_selected' and roles.get(contractor)=='Contractor'
            and selection.get('micro_action_id')=='CONTRACTOR-A05'):
        fields=('micro_action_id','micro_task_key','micro_result_sha256','native_supply_scope','proposal_response_sha256')
        result[contractor]={'event_type':observation.event_type,'tick':observation.tick,'project_id':observation.project_id,
            'agent_id':org,'committed':True,'data':{'supplier_id':org,'contractor_id':contractor,
                **{k:deepcopy(selection[k]) for k in fields if k in selection}}}
    return result


def prior_supply_decisions(assembly,*,organization_id,tick,read_guard,workers,query_original=None):
    """Own actually executed willingness outcomes, including upstream declines.

    These are not supply selections, detailed orders or resource commitments.
    Original micro output, transport confirmation and native event must agree.
    """
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    from integration.bank_financing_private import checked_result
    if not callable(read_guard):raise TaskConflict('Supply outcome memory needs its original source guard')
    with read_guard():
        assembly._validate_components();engine,client=assembly.engine,assembly.client
        if client.organization_roles.get(organization_id)!='Supplier' or type(tick) is not int or tick!=engine.current_tick:
            raise TaskConflict('Supply outcome memory changes its current organization or clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id);origins=[]
        choices={'SUPPLIER-A01':{'decline':False},'SUPPLIER-A02':{'decline':False},
            'SUPPLIER-A03':{'decline_quote':False},'SUPPLIER-A04':{'accept':True,'reject':False}}
        for row in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=row['payload']
            if payload['event_type']!='supplier_order_decision' or payload['tick']>=tick:continue
            project=engine.projects.get(payload['project_id'])
            events=[] if project is None else [e for e in project.event_log if e['event_id']==row['event_id']]
            if len(events)!=1:raise TaskConflict('Supply outcome memory lost its actual native decision event')
            event=events[0];expected=project_supply_event(AgentObservationV1.model_validate(event),client.organization_roles)
            if organization_id not in expected or task_digest(payload)!=task_digest(expected[organization_id]):
                raise TaskConflict('Supply outcome memory substitutes its actual event or private recipient')
            data=event['data'];scope={'project_id':project.project_id,'contractor_id':project.selected_contractor_id,'tick':event['tick']}
            proposal=[t['output'] for t in tasks if t['identity']['action_id']=='consider_supply_order'
                and t['identity']['purpose']=='propose' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_supply_scope')==scope]
            final=[t['output'] for t in tasks if t['identity']['action_id']=='supplier_order_acceptance'
                and t['identity']['purpose']=='decide' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_supply_scope')==scope]
            if (len(proposal)!=1 or len(final)!=1 or data.get('native_supply_scope')!=scope
                    or data.get('proposal_response_sha256')!=task_digest(proposal[0])
                    or final[0]['data'].get('proposal_response_sha256')!=task_digest(proposal[0])):
                raise TaskConflict('Supply outcome memory lost its original proposal or confirmation')
            action=data.get('micro_action_id')
            micro=[t for t in tasks if t['identity']['action_id']==action and t['identity']['purpose']=='action'
                and t['state']=='output_formed' and TaskIdentity(**t['identity']).key==data.get('micro_task_key')]
            if action not in choices or len(micro)!=1:raise TaskConflict('Supply outcome memory lost its original deciding action')
            saved=checked_result(workers[action],TaskIdentity(**micro[0]['identity']))
            accepted=choices[action].get(saved['result']['payload']['choice'])
            expected_action='accept_supply_order' if accepted else 'decline_supply_order'
            if (accepted is None or data.get('accepted') is not accepted or proposal[0]['accepted'] is not accepted
                    or final[0]['decision'] is not accepted or saved['result_sha256']!=data.get('micro_result_sha256')
                    or data.get('action_type')!=expected_action or proposal[0]['action_type']!=expected_action
                    or final[0]['action_type']!=expected_action
                    or data.get('offer_score')!=proposal[0]['data'].get('offer_score')
                    or data.get('offer_score')!=final[0]['data'].get('offer_score')
                    or any(data.get(k)!=proposal[0]['factors'].get(k) or data.get(k)!=final[0]['data'].get(k)
                        for k in ('micro_action_id','micro_task_key','micro_result_sha256'))):
                raise TaskConflict('Supply outcome memory changes its executed willingness or original micro result')
            origins.append({'event_id':row['event_id'],'project_id':project.project_id,'organization_id':organization_id,
                'tick':event['tick'],'accepted':accepted,'native_action':expected_action,'micro_action_id':action,
                'micro_choice':saved['result']['payload']['choice'],'micro_task_key':data['micro_task_key'],
                'micro_result_sha256':saved['result_sha256'],'proposal_response_sha256':task_digest(proposal[0])})
        if len({r['event_id'] for r in origins})!=len(origins):raise TaskConflict('Supply outcome memory repeats a native decision')
        if query_original is not None:
            from integration.supply_native_outcome_query import reconcile_supply_history
            reconcile_supply_history(query_original,origins,tasks,tick)
        return sorted(origins,key=lambda r:(r['tick'],r['project_id'],r['event_id']))


def prior_supply_selections(assembly,*,organization_id,tick,read_guard,query_original=None):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    if not callable(read_guard):raise TaskConflict('Supply memory needs its original source guard')
    with read_guard():
        assembly._validate_components();engine,client=assembly.engine,assembly.client
        if client.organization_roles.get(organization_id)!='Supplier' or type(tick) is not int or tick!=engine.current_tick:
            raise TaskConflict('Supply memory changes its current organization or clock')
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id);origins=[]
        for row in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id):
            payload=row['payload']
            if payload['event_type']!='supplier_selected' or payload['tick']>=tick:continue
            project=engine.projects.get(payload['project_id'])
            events=[] if project is None else [e for e in project.event_log if e['event_id']==row['event_id']]
            if len(events)!=1:raise TaskConflict('Supply memory lost its original selection event')
            event=events[0];expected=project_supply_event(AgentObservationV1.model_validate(event),client.organization_roles)
            if (organization_id not in expected or task_digest(payload)!=task_digest(expected[organization_id])
                    or event['data'].get('contractor_id')!=project.selected_contractor_id):
                raise TaskConflict('Supply memory substitutes its original selection or private recipient')
            scope={'project_id':project.project_id,'contractor_id':project.selected_contractor_id,'tick':event['tick']}
            decisions=[e for e in project.event_log if e['event_type']=='supplier_order_decision'
                and e['agent_id']==organization_id and e['tick']==event['tick']]
            if len(decisions)!=1 or decisions[0]['data'].get('accepted') is not True:
                raise TaskConflict('Supply selection has no original independent acceptance')
            data=decisions[0]['data']
            proposal=[t['output'] for t in tasks if t['identity']['action_id']=='consider_supply_order'
                and t['identity']['purpose']=='propose' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_supply_scope')==scope]
            final=[t['output'] for t in tasks if t['identity']['action_id']=='supplier_order_acceptance'
                and t['identity']['purpose']=='decide' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_supply_scope')==scope]
            if (len(proposal)!=1 or len(final)!=1 or proposal[0]['accepted'] is not True or final[0]['decision'] is not True
                    or proposal[0]['action_type']!=final[0]['action_type'] or data.get('native_supply_scope')!=scope
                    or data.get('proposal_response_sha256')!=task_digest(proposal[0])
                    or final[0]['data'].get('proposal_response_sha256')!=task_digest(proposal[0])):
                raise TaskConflict('Supply memory lost its original formed proposal or confirmation')
            fields=('micro_action_id','micro_task_key','micro_result_sha256')
            if (data.get('micro_action_id')!='SUPPLIER-A04'
                    or any(data.get(k)!=proposal[0]['factors'].get(k) or data.get(k)!=final[0]['data'].get(k) for k in fields)):
                raise TaskConflict('Supply memory changes its original micro result linkage')
            micro=[t for t in tasks if t['identity']['action_id']=='SUPPLIER-A04' and t['identity']['purpose']=='action'
                and t['state']=='output_formed' and TaskIdentity(**t['identity']).key==data.get('micro_task_key')
                and t['output_sha256']==data.get('micro_result_sha256')]
            if (len(micro)!=1 or micro[0]['output']['kind']!='completed' or micro[0]['output']['payload']['choice']!='accept'
                    or task_digest(micro[0]['output'])!=data['micro_result_sha256']):
                raise TaskConflict('Supply memory lost its original completed acceptance')
            selection=event['data'].get('contractor_decision',{})
            contractor_tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=scope['contractor_id'])
            native=[t['output'] for t in contractor_tasks if t['identity']['action_id']=='select_supplier'
                and t['identity']['purpose']=='propose' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_supply_scope')==scope]
            confirmed=[t['output'] for t in contractor_tasks if t['identity']['action_id']=='contractor_supplier_selection'
                and t['identity']['purpose']=='decide' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_supply_scope')==scope]
            if (len(native)!=1 or len(confirmed)!=1 or selection.get('selected_supplier_id')!=organization_id
                    or native[0]['data'].get('selected_supplier_id')!=organization_id
                    or confirmed[0]['data'].get('selected_supplier_id')!=organization_id
                    or selection.get('proposal_response_sha256')!=task_digest(native[0])
                    or confirmed[0]['data'].get('proposal_response_sha256')!=task_digest(native[0])):
                raise TaskConflict('Supply memory lost the actual Contractor selection')
            origins.append({'event_id':row['event_id'],'acceptance_event_id':decisions[0]['event_id'],
                'project_id':project.project_id,'contractor_id':scope['contractor_id'],'organization_id':organization_id,
                'tick':event['tick'],'micro_task_key':data['micro_task_key'],'micro_result_sha256':data['micro_result_sha256'],
                'proposal_response_sha256':task_digest(proposal[0])})
        if len({r['event_id'] for r in origins})!=len(origins):raise TaskConflict('Supply memory repeats the same selection')
        if query_original is not None:
            from integration.supply_native_outcome_query import reconcile_supply_history
            reconcile_supply_history(query_original,origins,tasks,tick)
        return sorted(origins,key=lambda r:(r['tick'],r['project_id'],r['event_id']))
