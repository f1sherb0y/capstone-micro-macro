"""Exact native terms-request correlation and own observed negotiation history."""
from copy import deepcopy

from integration.bank_financing_private import checked_result, evidence_binding
from integration.bindings.gba_v1_progress_payments import read_own_progress_payments
from integration.bindings.gba_v1_construction_suspensions import read_own_construction_suspensions
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def formation_scope(assembly,request,*,purpose):
    from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
    assembly._validate_components();engine=assembly.engine;client=assembly.client
    role=request.agent.role;org=request.agent.agent_id
    if role!='Contractor' or client.organization_roles.get(org)!='Contractor' or org not in engine.agents:
        raise TaskConflict('Contract terms require the actual current Contractor')
    if purpose=='propose' and request.operation=='decide_contract_terms':
        original=request.inputs.get('project',{});project=engine.projects.get(original.get('project_id'))
        if project is None or original!=project.model_dump(mode='json'):
            raise TaskConflict('Contract terms substitute the actual original project request')
        bids=[bid for bid in project.bids if bid.get('contractor_id')==org]
        if len(bids)!=1 or request.inputs.get('preferred_bid')!=bids[0]:
            raise TaskConflict('Contract terms require the exact independently supplied native preferred bid')
    elif purpose=='decide' and request.decision_type=='contract_negotiation':
        project=engine.projects.get(request.project_id)
        if (project is None or request.tick!=engine.current_tick
                or request.project!=DecisionRequestCollector._project_snapshot(project)):
            raise TaskConflict('Contract negotiation changes its actual project summary or time')
        risk=request.current_state.get('risk_inputs',{})
        if (risk.get('contract_sum')!=project.contract_sum or risk.get('planned_duration')!=project.performance.planned_duration
                or risk.get('owner_id')!=project.owner_id or risk.get('contractor_id')!=org):
            raise TaskConflict('Contract negotiation changes its original parties, price or programme')
    else:raise TaskConflict('Unexpected original Contractor terms transport')
    if (project.current_stage.value!='contract_award' or project.selected_contractor_id!=org
            or not project.flags.get('contract_negotiation_started') or project.flags.get('contract_signed')
            or project.flags.get('contract_negotiation_recommendation_recorded')):
        raise TaskConflict('Contract terms are outside the actual pending native negotiation')
    return {'project_id':project.project_id,'owner_id':project.owner_id,'contractor_id':org,'tick':engine.current_tick}


def prior_negotiations(app,*,organization_id,tick,include_current=False,decision_task_key=None):
    """Own strictly earlier authenticated original A04 decisions, not signatures."""
    if type(include_current) is not bool or (include_current != bool(decision_task_key)):
        raise TaskConflict('Current negotiation query requires its exact original decision identity')
    assembly=app.assembly;engine=assembly.engine;history=[]
    if (assembly.client.organization_roles.get(organization_id)!='Contractor' or tick!=engine.current_tick):
        raise TaskConflict('Contract history changes its own recipient or current business clock')
    events={event.event_id:event.model_dump(mode='json') for event in engine.events.events}
    records=app.records();tasks=assembly.client.tasks.for_organization(run_id=assembly.client.run_id,organization_id=organization_id)
    for project in engine.projects.values():
        for event in project.event_log:
            if (event['event_type']!='contract_negotiation_recommendation' or (event['tick']>tick or event['tick']==tick and not include_current)
                    or event['agent_id']!=organization_id):continue
            data=event['data'];individual=data.get('individual_decision',{});factors=individual.get('decision_factors',{})
            if factors.get('micro_action_id')!='CONTRACTOR-A04':continue
            scope={'project_id':project.project_id,'owner_id':data.get('owner_id'),
                'contractor_id':organization_id,'tick':event['tick']}
            matching=[r for r in records if r['state']=='formed' and r['scope']==scope]
            if len(matching)!=1:raise TaskConflict('Contract history lost its one original micro terms request')
            record=matching[0];identity=TaskIdentity(**record['identity'])
            if decision_task_key is not None and identity.key!=decision_task_key:continue
            plans=[p for p in app.plans if (p.organization_id,p.project_id,p.tick)==(organization_id,project.project_id,event['tick'])
                and task_digest(p.context.model_dump(mode='json'))==identity.context_sha256]
            if len(plans)!=1:raise TaskConflict('Negotiation history lost its original immutable source plan')
            from integration.financing_native_outcome_query import _original_result
            saved=_original_result(app,identity,app.worker,plans[0].context,plans[0].action_input,key=record['key'],tick=tick)
            proposals=[t['output'] for t in tasks if t['state']=='output_formed' and t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='decide_contract_terms' and t['output'].get('factors',{}).get('native_formation_scope')==scope]
            finals=[t['output'] for t in tasks if t['state']=='output_formed' and t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='contract_negotiation' and t['output'].get('data',{}).get('native_formation_scope')==scope]
            if len(proposals)!=1 or len(finals)!=1:raise TaskConflict('Contract history lost its original proposal or bounded confirmation')
            proposal,final=proposals[0],finals[0];accepted,action=app.summary(saved)
            if (events.get(event['event_id'])!=event or data.get('contractor_id')!=organization_id
                    or project.owner_id!=scope['owner_id'] or data.get('error') is not None or data.get('skipped_reason') is not None
                    or data.get('selected_action')!=action or final['action_type']!=action or final['decision']!=accepted
                    or individual.get('action_type')!=action or individual.get('accepted')!=accepted
                    or individual.get('decision_factors')!=proposal['factors']
                    or factors.get('native_formation_scope')!=scope or factors.get('micro_task_key')!=identity.key
                    or record['result_sha256']!=saved['result_sha256'] or factors.get('micro_result_sha256')!=saved['result_sha256']
                    or task_digest(proposal)!=record['proposal_response_sha256']
                    or final['data'].get('proposal_response_sha256')!=record['proposal_response_sha256']):
                raise TaskConflict('Contract history changes original A04 result, provenance or actual native negotiation outcome')
            history.append({'event_id':event['event_id'],'project_id':project.project_id,'tick':event['tick'],
                'contractor_id':organization_id,'owner_id':scope['owner_id'],'action_type':action,
                'source_event_sha256':task_digest(event),'micro_task_key':identity.key,'micro_result_sha256':saved['result_sha256']})
    if len({h['event_id'] for h in history})!=len(history):raise TaskConflict('Contract history repeats an actual event')
    return sorted(history,key=lambda h:(h['tick'],h['project_id'],h['event_id']))


def formation_sources(app,plan,request):
    scope=formation_scope(app.assembly,request,purpose='propose');objects=deepcopy(plan.objects)
    projected=None
    if plan.original_tender_projection is not None:
        from integration.contractor_tender_formation_projection import project_original_tender_formation
        objects,projected=project_original_tender_formation(app,plan,request,objects)
    history=prior_negotiations(app,organization_id=plan.organization_id,tick=plan.tick)
    paused=plan.max_prior_accept_terms is not None and sum(h['action_type']=='accept_terms' for h in history)>=plan.max_prior_accept_terms
    observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
        'prior_own_negotiations':history,'max_prior_accept_terms':plan.max_prior_accept_terms,'private_revision_preference':paused}
    if projected is not None:observed['actual_tender_projection']=projected
    if plan.original_tender_request_id is not None:
        from integration.contractor_selected_tender_sources import validate_formation_original_bid
        observed['actual_original_tender'] = validate_formation_original_bid(app,plan,request,objects)
    if plan.max_prior_owner_payment_delays is not None:
        payments=read_own_progress_payments(app.assembly,organization_id=plan.organization_id,
            tick=plan.tick,read_guard=app.read_guard)
        # Match the current counterparty. A delay event and its request are
        # one historical occurrence, never two payments or an unpaid balance.
        delayed=[r for r in payments['payment_requests'] if r['owner_id']==scope['owner_id']
            and r['payment_status']=='delayed']
        delay_pause=len(delayed)>=plan.max_prior_owner_payment_delays
        paused=paused or delay_pause
        observed.update(own_progress_payments=payments,prior_current_owner_delayed_requests=deepcopy(delayed),
            max_prior_owner_payment_delays=plan.max_prior_owner_payment_delays,
            payment_delay_preference_requests_price_review=delay_pause,private_revision_preference=paused)
    if plan.max_prior_construction_suspensions is not None:
        suspensions=read_own_construction_suspensions(app.assembly,organization_id=plan.organization_id,
            tick=plan.tick,read_guard=app.read_guard)
        suspension_pause=len(suspensions['suspensions'])>=plan.max_prior_construction_suspensions
        paused=paused or suspension_pause
        observed.update(own_construction_suspensions=suspensions,
            max_prior_construction_suspensions=plan.max_prior_construction_suspensions,
            suspension_preference_requests_price_review=suspension_pause,private_revision_preference=paused)
    profile,=[r['value'] for r in objects if r['ref']==plan.action_input['formation_profile_ref']]
    if profile['choice']!='accept' or profile['requirement_changes']:
        raise TaskConflict('Contract terms need their original independent acceptance baseline')
    if paused:
        if not plan.history_revision_change_refs:raise TaskConflict('Contract revision preference lacks independent permitted change requests')
        profile['choice']='revise';profile['requirement_changes']=[r.model_dump(mode='json') for r in plan.history_revision_change_refs]
    evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
    return objects,observed
