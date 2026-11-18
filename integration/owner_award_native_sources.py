"""Owner award views from actual negotiation and an explicitly reviewed agreement.

The two original processors use different agreement projections. Their common
fields and the complete Contractor projection are bound before execution; a
native negotiation event alone cannot authorize a different detailed agreement.
"""
from copy import deepcopy
from decimal import Decimal

from integration.bank_financing_private import checked_result, evidence_binding
from integration.contractor_formation_native_sources import prior_negotiations
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_award_objects import OwnerAwardTermsView, award_agreement_digest
from src.methods.capacity import CAPACITY_METHOD
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def award_scope(assembly, request, *, purpose):
    from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
    assembly._validate_components()
    engine = assembly.engine
    owner = request.agent.agent_id
    if request.agent.role != 'Owner' or assembly.client.organization_roles.get(owner) != 'Owner':
        raise TaskConflict('Award requires the actual Owner recipient')
    if purpose == 'propose' and request.operation == 'decide_contract_award':
        original = request.inputs.get('project', {})
        project = engine.projects.get(original.get('project_id'))
        if project is None or original != project.model_dump(mode='json'):
            raise TaskConflict('Award changes its actual original project request')
        bids = [b for b in project.bids if b.get('contractor_id') == project.selected_contractor_id]
        if len(bids) != 1 or request.inputs.get('preferred_bid') != bids[0]:
            raise TaskConflict('Award changes the actual selected bid')
    elif purpose == 'decide' and request.decision_type == 'owner_contract_award':
        project = engine.projects.get(request.project_id)
        if (project is None or request.tick != engine.current_tick
                or request.project != DecisionRequestCollector._project_snapshot(project)):
            raise TaskConflict('Award confirmation changes its current original project or clock')
    else:
        raise TaskConflict('Unexpected original Owner award transport')
    if (project.owner_id != owner or project.current_stage.value != 'contract_award'
            or not project.flags.get('contract_negotiation_recommendation_recorded')
            or project.flags.get('contractor_contract_decision') != 'accept_terms'
            or project.flags.get('owner_contract_decision_recorded') or project.flags.get('contract_signed')):
        raise TaskConflict('Award is outside its actual pending independent Owner decision')
    return {'project_id': project.project_id, 'owner_id': owner,
            'contractor_id': project.selected_contractor_id, 'tick': engine.current_tick}


def received_contractor_acceptance(app, plan, scope):
    """Disclose acceptance and its public agreement, never private cash or crews."""
    parent = app.parent
    history = prior_negotiations(parent, organization_id=scope['contractor_id'], tick=scope['tick'])
    matches = [h for h in history if h['project_id'] == scope['project_id']
               and h['owner_id'] == scope['owner_id']]
    if not matches or matches[-1]['action_type'] != 'accept_terms':
        raise TaskConflict('Owner has no actual earlier accepted Contractor negotiation')
    event = matches[-1]
    records = [r for r in parent.records() if r.get('identity')
               and TaskIdentity(**r['identity']).key == event['micro_task_key']]
    if len(records) != 1:
        raise TaskConflict('Owner acceptance lost its original Contractor task')
    record = records[0]
    saved = checked_result(parent.worker, TaskIdentity(**record['identity']))
    original = {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
    public_terms = plan.reviewed_contractor_terms
    if original.get(task_digest(public_terms['ref'])) != public_terms:
        raise TaskConflict('Actual Contractor acceptance differs from the independently reviewed complete agreement')
    payload = saved['result']['payload']
    if (payload.get('choice') != 'accept' or payload.get('terms_ref') != public_terms['ref']
            or payload.get('offer_ref') != public_terms['offer_ref']
            or public_terms['contractor_id'] != scope['contractor_id']
            or public_terms['client_id'] != scope['owner_id']):
        raise TaskConflict('Actual Contractor result changes its party or accepted exact terms')
    capacity = [m for m in saved['audit']['method_calls'] if m['method_ref'] == CAPACITY_METHOD.model_dump(mode='json')]
    if (len(capacity) != 1 or capacity[0]['result']['kind'] != 'ok'
            or capacity[0]['result'].get('value', {}).get('feasible') is not True):
        raise TaskConflict('Owner capacity condition needs an actual successful original Contractor capacity method')
    source_plan, = [p for p in parent.plans if p.context.operation_id == saved['audit']['operation_id']]
    grant_ref = source_plan.action_input['authority_ref']
    grant = original[task_digest(grant_ref)]
    function = original[task_digest(source_plan.context.function_ref.model_dump(mode='json'))]
    declared = {task_digest(r['ref']): r['value'] for r in plan.objects}
    if (declared.get(task_digest(grant_ref)) != grant
            or declared.get(task_digest(source_plan.context.function_ref.model_dump(mode='json'))) != function):
        raise TaskConflict('Owner substitutes the actual independent Contractor signing authority')
    return event, source_plan, grant_ref


def prior_owner_awards(app, *, owner_id, tick, include_current=False, decision_task_key=None):
    """Own authenticated actual award decisions, not inferred signatures or cash."""
    if type(include_current) is not bool or (include_current != bool(decision_task_key)):
        raise TaskConflict('Current Owner award query requires its exact original decision identity')
    with app.read_guard():
        app.parent._check()
        app._check()
        engine = app.assembly.engine
        if (tick != engine.current_tick or app.assembly.client.organization_roles.get(owner_id) != 'Owner'):
            raise TaskConflict('Owner award feedback changes its recipient or current business clock')
        global_events = {e.event_id: e.model_dump(mode='json') for e in engine.events.events}
        tasks = app.assembly.client.tasks.for_organization(run_id=app.assembly.client.run_id, organization_id=owner_id)
        history = []
        for project in engine.projects.values():
            for event in project.event_log:
                if (event['event_type'] != 'owner_contract_award_decision' or (event['tick'] > tick or event['tick'] == tick and not include_current)
                        or event['agent_id'] != owner_id):
                    continue
                factors = event['data'].get('decision_factors', {})
                if factors.get('micro_action_id') != 'OWN-A10':
                    continue
                scope = {'project_id': project.project_id, 'owner_id': owner_id,
                         'contractor_id': project.selected_contractor_id, 'tick': event['tick']}
                records = [r for r in app.records() if r['state'] == 'formed' and r['scope'] == scope]
                if len(records) != 1:
                    raise TaskConflict('Owner award history lost its one original result')
                record = records[0]
                identity = TaskIdentity(**record['identity'])
                if decision_task_key is not None and identity.key != decision_task_key:
                    continue
                original = app.snapshots.get(identity)
                context = ActionContext.model_validate(original['context'])
                plans = [p for p in app.plans if p.organization_id == owner_id
                         and p.project_id == project.project_id and p.tick == event['tick']
                         and p.context == context]
                if (len(plans) != 1 or original['action_input'] != plans[0].action_input
                        or identity.organization_id != owner_id or identity.role != 'Owner'
                        or identity.action_id != 'OWN-A10' or identity.purpose != 'action'):
                    raise TaskConflict('Owner award history changes its original invocation, input or source plan')
                current = context.model_copy(update={
                    'business_time': context.business_time.model_copy(update={'offset': tick})}, deep=True)
                grants = app.organizations.grants(current, 'OWN-A10', 'Owner')
                if any(g.organization_id != owner_id for g in grants):
                    raise TaskConflict('Owner award history borrows another organization authority')
                saved = checked_result(app.worker, identity)
                readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in context.visible_refs}
                if any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading']):
                    raise TaskConflict('Owner award history lost current permission for its original private sources')
                accepted, action = app.summary(saved)
                proposals = [t['output'] for t in tasks if t['state'] == 'output_formed'
                             and t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == 'decide_contract_award'
                             and t['output'].get('factors', {}).get('native_award_scope') == scope]
                finals = [t['output'] for t in tasks if t['state'] == 'output_formed'
                          and t['identity']['purpose'] == 'decide' and t['identity']['action_id'] == 'owner_contract_award'
                          and t['output'].get('data', {}).get('native_award_scope') == scope]
                if len(proposals) != 1 or len(finals) != 1:
                    raise TaskConflict('Owner award history lost its original proposal or bounded confirmation')
                proposal, final = proposals[0], finals[0]
                profile = engine.agents[owner_id]
                expected_factors = {**proposal['factors'], 'decision_source': 'llm_agent',
                    'decision_type': 'owner_contract_award',
                    'agent_identity': {'agent_id': owner_id, 'role': profile.role.value if hasattr(profile.role, 'value') else profile.role,
                                       'region': profile.region, 'enterprise_type': profile.enterprise_type},
                    'local_evidence_utility': round(proposal['utility'], 4),
                    'local_evidence_probability': round(proposal['probability'], 4),
                    'llm_action_type': action, 'llm_decision': accepted, 'llm_reason': final['reason']}
                if (project.owner_id != owner_id
                        or global_events.get(event['event_id']) != event
                        or event['data'].get('action_type') != action or event['data'].get('accepted') != accepted
                        or factors != expected_factors or event['data'].get('reason') != final['reason']
                        or factors.get('micro_task_key') != TaskIdentity(**record['identity']).key
                        or factors.get('micro_result_sha256') != saved['result_sha256']
                        or record['result_sha256'] != saved['result_sha256']
                        or task_digest(proposals[0]) != record['proposal_response_sha256']
                        or finals[0]['action_type'] != action or finals[0]['decision'] != accepted
                        or finals[0]['data'].get('proposal_response_sha256') != record['proposal_response_sha256']):
                    raise TaskConflict('Owner award history changes its original micro result or actual native outcome')
                history.append({'event_id': event['event_id'], 'project_id': project.project_id, 'tick': event['tick'],
                                'action_type': action, 'source_event_sha256': task_digest(event),
                                'micro_task_key': factors['micro_task_key'], 'micro_result_sha256': saved['result_sha256']})
        return sorted(history, key=lambda h: (h['tick'], h['project_id'], h['event_id']))


def award_sources(app, plan, request):
    scope = award_scope(app.assembly, request, purpose='propose')
    event, source_plan, grant_ref = received_contractor_acceptance(app, plan, scope)
    objects = deepcopy(plan.objects)
    by_ref = {task_digest(r['ref']): r['value'] for r in objects}
    terms = by_ref[task_digest(plan.action_input['final_terms_ref'])]
    full = plan.reviewed_contractor_terms
    project = app.assembly.engine.projects[plan.project_id]
    if (terms['scope'] != full['scope'] or terms['scope_keys'] != full['scope_keys']
            or terms['required_party_ids'] != full['required_party_ids'] or terms['work_window'] != full['work_window']
            or terms['clause_refs'] != full['clause_refs'] or terms['total_price'] != full['price']
            or terms['contract_template_ref'] != full['contract_template_ref']
            or terms['round_ref'] != full['round_ref'] or terms['condition_refs'] != full['condition_refs']
            or terms['owner_organization_id'] != scope['owner_id']
            or terms['counterparty_organization_id'] != scope['contractor_id']
            or Decimal(full['price']['value']) != Decimal(str(project.contract_sum))
            or full['work_window']['end']['offset'] - full['work_window']['start']['offset'] != project.performance.planned_duration
            or full['price']['currency'] != 'HKD'):
        raise TaskConflict('Owner projection changes the reviewed complete agreement or actual native price')
    if any(r['ref']['kind'] == 'PartyAcceptance' for r in objects):
        raise TaskConflict('Owner initial input must not prewrite future Contractor acceptance')
    acceptance_ref = plan.received_acceptance_ref.model_dump(mode='json')
    point = {'clock_ref': plan.context.business_time.clock_ref.model_dump(mode='json'), 'offset': event['tick']}
    acceptance = {'ref': acceptance_ref, 'evidence_refs': [plan.native_evidence_ref.model_dump(mode='json')],
        'scope': deepcopy(terms['scope']), 'available_at': point, 'effective_window': deepcopy(terms['effective_window']),
        'run_id': plan.context.run_id, 'offer_ref': deepcopy(terms['offer_ref']), 'round_ref': deepcopy(terms['round_ref']),
        'terms_ref': deepcopy(terms['ref']), 'party_id': scope['contractor_id'],
        'author_actor_id': source_plan.context.actor_id,
        'author_function_ref': source_plan.context.function_ref.model_dump(mode='json'),
        'author_authority_ref': grant_ref, 'author_action_id': 'CONTRACTOR-A04',
        'agreement_sha256': award_agreement_digest(OwnerAwardTermsView.model_validate(terms)),
        'choice': 'accept', 'status': 'active', 'decided_at': point}
    objects.append({'ref': acceptance_ref, 'value': acceptance})
    history = prior_owner_awards(app, owner_id=scope['owner_id'], tick=scope['tick'])
    paused = (plan.max_prior_accepts is not None
              and sum(h['action_type'] == 'accept_contract' for h in history) >= plan.max_prior_accepts)
    snapshot = by_ref[task_digest(plan.action_input['commitment_snapshot_ref'])]
    capacity = by_ref[task_digest(snapshot['counterparty_capacity_condition_ref'])]
    if (capacity['kind'] != 'resource' or capacity['verification'] != {'state': 'known', 'value': False}
            or plan.native_evidence_ref.model_dump(mode='json') not in capacity['evidence_refs']):
        raise TaskConflict('Owner capacity condition needs its declared binding to actual original A04 acceptance')
    capacity['verification'] = {'state': 'known', 'value': True}
    profile = by_ref[task_digest(snapshot['formation_profile_ref'])]
    if paused:
        if not plan.history_revision_refs:
            raise TaskConflict('Owner revision preference lacks independently authorized revision references')
        profile['choice_order'] = ['revise']
        profile['requested_change_refs'] = [r.model_dump(mode='json') for r in plan.history_revision_refs]
    observed = {'scope': scope, 'native_request_sha256': task_digest(request.model_dump(mode='json')),
                'received_contractor_acceptance': event, 'reviewed_complete_agreement_sha256': task_digest(full),
                'owner_agreement_sha256': acceptance['agreement_sha256'], 'prior_own_awards': history,
                'max_prior_accepts': plan.max_prior_accepts, 'private_revision_preference': paused}
    evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), observed)
    return objects, observed
