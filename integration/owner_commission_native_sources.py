"""Project only received commercial terms from actual original A02 execution."""
from copy import deepcopy
import json

from integration.bank_financing_private import checked_result,evidence_binding
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest


def commission_sources(app,*,plan,request,history):
    from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
    parent=app.professional;client=parent.assembly.client;engine=parent.assembly.engine
    objects=deepcopy(plan.objects);byref={task_digest(r['ref']):r['value'] for r in objects}
    def target(ref):return byref[task_digest(ref.model_dump(mode='json') if hasattr(ref,'model_dump') else ref)]
    candidates=request.inputs['candidates'];ids=[p['agent_id'] for p,d in candidates]
    if len(set(ids))!=len(ids) or set(ids)!={d.provider_id for d in plan.disclosures}:
        raise TaskConflict('Owner commission changes its complete current provider disclosure set')
    origins=[]
    for profile,decision in candidates:
        org=profile['agent_id'];disclosure,=[d for d in plan.disclosures if d.provider_id==org]
        if profile!=engine.agents[org].model_dump(mode='json') or profile['role']!=plan.role:
            raise TaskConflict('Owner commission substitutes its actual current provider profile')
        factors=decision['factors'];scope={'project_id':plan.project_id,'tick':plan.tick,'role':plan.role}
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=org)
        micro=[t for t in tasks if t['identity']['purpose']=='action' and t['identity']['action_id']==plan.role.upper()+'-A02'
            and t['state']=='output_formed' and TaskIdentity(**t['identity']).key==factors.get('micro_task_key')]
        if len(micro)!=1:raise TaskConflict('Owner commission lost the actual original A02 worker task')
        identity=TaskIdentity(**micro[0]['identity']);saved=checked_result(parent.workers[plan.role],identity)
        proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose' and t['identity']['action_id']=='consider_appointment'
            and t['state']=='output_formed' and t['output']['factors'].get('native_professional_scope')==scope]
        finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide'
            and t['identity']['action_id']==plan.role.lower()+'_appointment_acceptance' and t['state']=='output_formed'
            and t['output']['data'].get('native_professional_scope')==scope]
        events=[e for e in engine.projects[plan.project_id].event_log if e['tick']==plan.tick
            and e['event_type']=='appointment_decision' and e['agent_id']==org]
        if len(proposals)!=1 or len(finals)!=1 or len(events)!=1:
            raise TaskConflict('Owner commission lost its original provider proposal, confirmation or actual decision event')
        proposal,final,event=proposals[0],finals[0],events[0]
        snapshot=parent.snapshots.get(identity)
        technical,=[r for r in _provider_records(parent) if r.get('identity')==identity.as_dict()]
        original=AgentProposalRequestV1.model_validate(technical['native_request'])
        provider_plan,=[p for p in parent.plans if (p.organization_id,p.project_id,p.tick,p.role)==
            (org,plan.project_id,plan.tick,plan.role)]
        # Each actual acceptance appends an event. Preserve its original read
        # point, rather than comparing that older full snapshot with the later
        # Owner request's event log or substituting a new provider invocation.
        actual_scope={'project_id':original.inputs['project']['project_id'],'tick':snapshot['context']['business_time']['offset'],
            'role':original.agent.role}
        current=engine.projects[plan.project_id].model_dump(mode='json');prior=original.inputs['project']
        fresh_objects,fresh_observed=parent._sources(provider_plan,original)
        native=[r['projection'] for r in saved['source_reading'] if r['ref']==provider_plan.native_evidence_ref.model_dump(mode='json')]
        grants=parent.organizations.grants(provider_plan.context,plan.role.upper()+'-A02',plan.role)
        accepted,action=parent._selected(provider_plan,saved['result'])
        if (actual_scope!=scope or original.agent.agent_id!=org or original.operation!='consider_appointment'
                or any(prior[k]!=current[k] for k in ('project_id','owner_id','region','project_type','initial_budget','current_stage'))
                or current['event_log'][:len(prior['event_log'])]!=prior['event_log']
                or technical['record_sha256']!=task_digest({k:v for k,v in technical.items() if k!='record_sha256'})
                or technical['request_sha256']!=task_digest(original.model_dump(mode='json'))
                or technical['source_file_sha256']!=parent.settings.file_sha256
                or technical['source_sha256']!=task_digest(fresh_objects) or technical['observed']!=fresh_observed
                or len(native)!=1 or native[0]['content_hash']!=task_digest(technical['observed'])
                or not grants or grants[0].organization_id!=org
                or factors.get('native_professional_scope')!=scope
                or factors.get('micro_action_id')!=plan.role.upper()+'-A02'
                or factors.get('micro_result_sha256')!=saved['result_sha256']
                or event['data'].get('decision_factors')!=factors
                or event['data'].get('accepted')!=accepted or event['data'].get('action_type')!=action
                or decision['accepted']!=accepted or decision['action_type']!=action
                or proposal['accepted']!=accepted or final['decision']!=accepted
                or proposal['action_type']!=action or final['action_type']!=action
                or proposal['factors'].get('micro_task_key')!=identity.key
                or final['data'].get('micro_result_sha256')!=saved['result_sha256']
                or technical['state']!='formed' or technical['identity']!=identity.as_dict()
                or technical['result_sha256']!=saved['result_sha256']
                or snapshot['context']!=provider_plan.context.model_dump(mode='json')
                or snapshot['action_input']!=provider_plan.action_input):
            raise TaskConflict('Owner commission substitutes the original independently confirmed A02 acceptance')
        originals={task_digest(r['ref']):r['projection'] for r in saved['source_reading']}
        terms=originals[task_digest(provider_plan.action_input['terms_ref'])]
        service_request=originals[task_digest(provider_plan.action_input['request_ref'])]
        offer=target(disclosure.offer_ref);out=target(disclosure.terms_ref);provider=target(disclosure.provider_ref)
        service=target(plan.action_input['service_scope_ref']);window=target(service['window_ref'])
        grant=originals[task_digest(provider_plan.context.authorization_refs[0].model_dump(mode='json'))]
        public={'scope_ref':terms['scope'],'employer_organization_id':service_request['client_organization_id'],
            'provider_organization_id':org,'payer_organization_id':service_request['payer_organization_id'],
            'payer_actor_id':terms['payer_id'],'fee':terms['fee'],'service_codes':{'state':'known','value':[terms['service_code']['value']]},
            'requested_uses':terms['requested_uses'],'responsibility_codes':terms['responsibility_codes'],
            'issued_at':terms['issued_at'],'effective_window':terms['effective_window'],'status':'offered'}
        if (service_request['client_organization_id']!=plan.organization_id or service_request['payer_organization_id']!=plan.organization_id
                or terms['scope']!=plan.context.scope.model_dump(mode='json') or terms['relation']!='external'
                or terms['provider_id']!=provider_plan.context.actor_id
                or terms['client_id']!=plan.context.actor_id or terms['payer_id']!=plan.context.actor_id
                or terms['region_id']!={'state':'known','value':service['region_id']}
                or terms['object_type']!={'state':'known','value':current['project_type']}
                or terms['desired_window']!={'state':'known','value':window}
                or any(out.get(k)!=v for k,v in public.items())
                or provider['organization_id']!=org or provider['actor_id']!=terms['provider_id']
                or provider['function_ref']!=provider_plan.context.function_ref.model_dump(mode='json')
                or offer['author_actor_id']!=terms['provider_id'] or offer['author_function_ref']!=provider['function_ref']
                or offer['authority_ref']!=grant['ref'] or offer['authority_action_id']!=plan.role.upper()+'-A02'
                or target(grant['ref'])!=grant):
            raise TaskConflict('Owner received commercial terms change the actual A02 scope, author, fee, deadline or payer')
        # Requirement refs have distinct closed schemas for provider and owner;
        # preserve the same exact request scope/use/description in both views.
        if {task_digest(v['provider_ref']) for v in disclosure.deliverable_links}!={task_digest(v) for v in terms['deliverable_requirement_refs']}:
            raise TaskConflict('Owner commission drops or expands accepted provider deliverables')
        for link in disclosure.deliverable_links:
            source=originals[task_digest(link['provider_ref'])];projected=target(link['owner_ref'])
            if (source['request_ref']!=service_request['ref'] or source['scope']!=terms['scope']
                    or any(source[k]!=projected[k] for k in ('requested_use','description'))
                    or projected['service_scope_ref']!=service['ref'] or link['owner_ref'] not in out['deliverable_refs']):
                raise TaskConflict('Owner commission substitutes an accepted deliverable requirement')
        # Initial disclosed capabilities and qualifications are independent
        # sources; compare every shared field rather than manufacturing them
        # from the mere fact that the provider answered accept.
        cap=originals[task_digest(provider_plan.action_input['capability_ref'])];projected=target(provider['capability_ref'])
        for field in ('organization_id','region_ids','service_codes','allowed_uses','responsibility_codes','method_refs',
                'qualification_refs','qualification_coverage','effective_window'):
            if projected[field]!=cap[field]:raise TaskConflict('Owner commission changes disclosed provider capability')
        for ref in cap['qualification_refs']:
            actual=originals[task_digest(ref)];view=target(ref)
            if any(view[k]!=actual[k] for k in ('ref','evidence_refs','organization_id','code','region_ids','service_codes',
                    'effective_window','standing')):raise TaskConflict('Owner commission changes a disclosed provider qualification')
        for ref in disclosure.shared_evidence_refs:
            if target(ref)!=originals[task_digest(ref.model_dump(mode='json'))]:
                raise TaskConflict('Owner commission substitutes the original received commercial Evidence')
        if not accepted:offer['status']='withdrawn'
        else:offer['priority']['value']+=plan.repeat_provider_priority_penalty*sum(h['provider_id']==org for h in history)
        origins.append({'provider_id':org,'accepted':accepted,'identity':identity.as_dict(),'result_sha256':saved['result_sha256'],
            'source_reading_sha256':saved['source_reading_sha256'],'record_sha256':saved['record_sha256'],
            'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final),
            'acceptance_event_id':event['event_id'],'original_terms_ref':terms['ref']})
    observed={'native_request_sha256':task_digest(request.model_dump(mode='json')),'prior_own_commissions':history,
        'repeat_provider_priority_penalty':plan.repeat_provider_priority_penalty,'providers':origins}
    evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
    evidence_binding(objects,plan.handoff_evidence_ref.model_dump(mode='json'),origins)
    return objects,observed


def _provider_records(parent):
    with parent.assembly.client.tasks._lock:
        return [json.loads(v) for v, in parent.assembly.client.tasks._db.execute(
            'SELECT value FROM metadata WHERE key LIKE ?',(parent.PREFIX+'%',))]
