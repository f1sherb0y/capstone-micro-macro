"""Bind repeated native supply transports to original project/contractor/time."""
from copy import deepcopy

from src.coordination.tasks import TaskConflict, task_digest


def supply_scope(assembly,request,*,purpose):
    from gba_construction_sim.backend.agents.base_agent import AgentDecision
    from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
    assembly._validate_components();engine,client=assembly.engine,assembly.client
    role=request.agent.role
    if client.organization_roles.get(request.agent.agent_id)!=role or role not in {'Supplier','Contractor'}:
        raise TaskConflict('Supply request changes its actual organization role')
    if purpose=='propose' and (role,request.operation)==('Supplier','consider_supply_order'):
        snapshot=request.inputs.get('project',{});project=engine.projects.get(snapshot.get('project_id'))
        if project is None or project.model_dump(mode='json')!=snapshot:
            raise TaskConflict('Supply request changes its original current project snapshot')
        scope={'project_id':project.project_id,'contractor_id':request.inputs.get('contractor_id'),'tick':engine.current_tick}
        if set(request.inputs)!={'project','contractor_id','required_resource','prior_fit'}:
            raise TaskConflict('Supply request changes the original native input contract')
    elif purpose=='propose' and (role,request.operation)==('Contractor','select_supplier'):
        offers=request.inputs.get('offers',[]);scopes=[]
        if not offers:raise TaskConflict('Supply selection needs original scoped supplier decisions')
        if len({p.get('agent_id') for p,d in offers})!=len(offers):
            raise TaskConflict('Supply selection repeats the same original supplier')
        for profile,decision in offers:
            scope=decision.get('factors',{}).get('native_supply_scope')
            if profile.get('role')!='Supplier' or not isinstance(scope,dict):
                raise TaskConflict('Supply selection lacks an original supplier scope')
            actual=engine.agents.get(profile.get('agent_id'));project=engine.projects.get(scope.get('project_id'))
            events=[] if project is None else [e for e in project.event_log if e['event_type']=='supplier_order_decision'
                and e['agent_id']==profile.get('agent_id') and e['tick']==engine.current_tick]
            if (actual is None or actual.model_dump(mode='json')!=profile or len(events)!=1
                    or task_digest(events[0]['data'])!=task_digest(AgentDecision(**decision).to_event_data())):
                raise TaskConflict('Supply selection changes its original candidate or actual acceptance event')
            tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=profile['agent_id'])
            proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='consider_supply_order' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_supply_scope')==scope]
            finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='supplier_order_acceptance' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_supply_scope')==scope]
            if (len(proposals)!=1 or len(finals)!=1 or decision.get('utility')!=proposals[0]['utility']
                    or decision.get('data',{}).get('offer_score')!=proposals[0]['data'].get('offer_score')
                    or decision.get('accepted')!=finals[0]['decision']
                    or decision.get('action_type')!=finals[0]['action_type']
                    or decision.get('data',{}).get('micro_result_sha256')!=finals[0]['data'].get('micro_result_sha256')
                    or decision.get('data',{}).get('proposal_response_sha256')!=finals[0]['data'].get('proposal_response_sha256')):
                raise TaskConflict('Supply selection substitutes an original confirmed supplier decision')
            scopes.append(scope)
        scope=scopes[0]
        if any(s!=scope for s in scopes):raise TaskConflict('Supply selection combines different projects or times')
        project=engine.projects.get(scope.get('project_id'))
    elif purpose=='decide' and (role,request.decision_type) in {
            ('Supplier','supplier_order_acceptance'),('Contractor','contractor_supplier_selection')}:
        scope=request.decision_support.get('decision_factors',{}).get('native_supply_scope')
        project=engine.projects.get(request.project_id)
        if (not isinstance(scope,dict) or scope.get('project_id')!=request.project_id
                or request.tick!=engine.current_tick or project is None
                or request.project!=DecisionRequestCollector._project_snapshot(project)):
            raise TaskConflict('Supply confirmation changes its original scope or project summary')
    else:raise TaskConflict('Unexpected original supply transport')
    if (set(scope)!={'project_id','contractor_id','tick'} or type(scope['tick']) is not int
            or scope['tick']!=engine.current_tick or project is None
            or project.current_stage.value!='contract_award' or not project.flags.get('contract_signed')
            or project.selected_contractor_id!=scope['contractor_id']
            or role=='Contractor' and request.agent.agent_id!=scope['contractor_id']):
        raise TaskConflict('Supply transport is outside its actual signed-contract project and time')
    return dict(scope)


def transport_native_supplier_selection(routes,request):
    """Preserve the original Contractor selection, including bounded candidates."""
    from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
    from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
    scope=supply_scope(routes.assembly,request,purpose='decide')
    proposals=[t['output'] for t in routes.assembly.client.tasks.for_organization(
        run_id=routes.assembly.client.run_id,organization_id=request.agent.agent_id)
        if t['identity']['purpose']=='propose' and t['identity']['action_id']=='select_supplier'
        and t['state']=='output_formed' and t['output'].get('factors',{}).get('native_supply_scope')==scope]
    if len(proposals)!=1:raise TaskConflict('Supply selection needs its one original native proposal')
    proposal=proposals[0];support=request.decision_support
    if (proposal['factors'].get('decision_source')!='native_macro' or support.get('decision_factors')!=proposal['factors']
            or support.get('accepted')!=proposal['accepted'] or support.get('action_type')!=proposal['action_type']
            or any(task_digest(support.get(k))!=task_digest(v) for k,v in proposal['data'].items())
            or request.choice_contract.output_field!='selected_supplier_id' or request.choice_contract.multiple
            or proposal['accepted'] and proposal['data'].get('selected_supplier_id') not in {c['id'] for c in request.candidate_options}
            or proposal['action_type'] not in request.constraints.allowed_actions):
        raise TaskConflict('Supply selection substitutes its original proposal or bounded candidates')
    response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=request.agent.agent_id,
        action_type=proposal['action_type'],decision=proposal['accepted'],reason=proposal['reason'],
        data={**deepcopy(proposal['data']),'decision_source':'native_macro','source':'original_native_supplier_selection',
            'native_supply_scope':scope,'proposal_response_sha256':task_digest(proposal)})
    ExternalAgentDecisionProvider._validated_action(request,response)
    routes._calls.append({'purpose':'decide','role':'Contractor','decision_type':request.decision_type,
        'request_id':request.request_id,'decision_source':'native_macro','source':'original_native_supplier_selection'})
    return response
