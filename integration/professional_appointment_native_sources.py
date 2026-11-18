"""Authenticate native reception and original independent A02/OWN-A04 results."""
from copy import deepcopy
import json

from integration.bank_financing_private import checked_result, evidence_binding
from integration.professional_intake_feedback import ROLE_FIELD, project_professional_event
from src.actions.contracts.architect_appointment_objects import service_terms_digest
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def received_team(app, *, plan, entry):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    p = app.professional
    client, engine = p.assembly.client, p.assembly.engine
    payload = entry['payload']
    project = engine.projects.get(plan.project_id)
    events = [] if project is None else [e for e in project.event_log if e['event_id'] == entry['event_id']]
    if len(events) != 1:
        raise TaskConflict('Appointment reception has no unique actual native project event')
    event = events[0]
    expected = project_professional_event(AgentObservationV1.model_validate(event), client.organization_roles)
    if (event['event_type'] != 'consultant_team_appointed' or event['tick'] != plan.tick
            or event['agent_id'] != project.owner_id or event['project_id'] != plan.project_id
            or event['data'].get(ROLE_FIELD[plan.role]) != plan.organization_id
            or plan.organization_id not in expected or payload != expected[plan.organization_id]
            or client.organization_roles.get(plan.organization_id) != plan.role):
        raise TaskConflict('Appointment reception substitutes its actual recipient, role, owner, time or native selection')
    return event


def _party(app, *, organization_id, action_id, scope, propose_action, final_action):
    client = app.professional.assembly.client
    tasks = client.tasks.for_organization(run_id=client.run_id, organization_id=organization_id)
    proposals = [t['output'] for t in tasks if t['state'] == 'output_formed'
        and t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == propose_action
        and t['output'].get('factors', {}).get('native_professional_scope') == scope]
    finals = [t['output'] for t in tasks if t['state'] == 'output_formed'
        and t['identity']['purpose'] == 'decide' and t['identity']['action_id'] == final_action
        and t['output'].get('data', {}).get('native_professional_scope') == scope]
    if len(proposals) != 1 or len(finals) != 1:
        raise TaskConflict('Appointment reception lost its original independent proposal or final decision')
    proposal, final = proposals[0], finals[0]
    factors = proposal['factors']
    micro = [t for t in tasks if t['state'] == 'output_formed' and t['identity']['purpose'] == 'action'
        and t['identity']['action_id'] == action_id
        and TaskIdentity(**t['identity']).key == factors.get('micro_task_key')]
    if (len(micro) != 1 or proposal['accepted'] is not True or final['decision'] is not True
            or factors.get('micro_action_id') != action_id
            or final['data'].get('micro_task_key') != factors.get('micro_task_key')
            or final['data'].get('micro_result_sha256') != factors.get('micro_result_sha256')
            or final['action_type'] != proposal['action_type']
            or action_id == 'OWN-A04' and final['data'].get('proposal_response_sha256') != task_digest(proposal)):
        raise TaskConflict('Appointment reception changes original independent party acceptance or task provenance')
    return TaskIdentity(**micro[0]['identity']), proposal, final


def appointment_sources(app, *, plan, entry):
    p = app.professional
    event = received_team(app, plan=plan, entry=entry)
    scope = {'project_id': plan.project_id, 'tick': plan.tick, 'role': plan.role}
    identity, proposal, final = _party(app, organization_id=plan.organization_id,
        action_id=plan.role.upper() + '-A02', scope=scope,
        propose_action='consider_appointment', final_action=plan.role.lower() + '_appointment_acceptance')
    provider = checked_result(p.workers[plan.role], identity)
    snapshot = p.snapshots.get(identity)
    acceptance_events = [e for e in p.assembly.engine.projects[plan.project_id].event_log
        if e['event_type'] == 'appointment_decision' and e['tick'] == plan.tick
        and e['agent_id'] == plan.organization_id and e['data'].get('role') == plan.role]
    if (len(acceptance_events) != 1 or acceptance_events[0]['data'].get('accepted') is not True
            or any(acceptance_events[0]['data'].get('decision_factors', {}).get(k) != v
                for k, v in proposal['factors'].items())
            or provider['result_sha256'] != proposal['factors']['micro_result_sha256']
            or provider['result']['payload']['choice'] != 'accept'
            or snapshot['context']['business_time'] != plan.context.business_time.model_dump(mode='json')
            or snapshot['context']['actor_id'] != plan.context.actor_id
            or snapshot['context']['function_ref'] != plan.context.function_ref.model_dump(mode='json')):
        raise TaskConflict('Appointment reception does not match the actual independently accepted professional decision')
    owner_id = event['agent_id']
    owner_actor = p.organizations.get(owner_id).actor_id
    owner_identity, owner_proposal, owner_final = _party(app, organization_id=owner_id,
        action_id='OWN-A04', scope=scope, propose_action='select_appointment',
        final_action='owner_select_' + plan.role.lower())
    owner = checked_result(p.owner.worker, owner_identity)
    native_selection = event['data'].get('owner_selections', {}).get(plan.role.lower(), {})
    if (owner['result']['payload']['choice'] != 'accept'
            or owner['result_sha256'] != owner_proposal['factors']['micro_result_sha256']
            or owner_proposal['data'].get('selected_agent_id') != plan.organization_id
            or owner_final['data'].get('selected_agent_id') != plan.organization_id
            or any(native_selection.get('decision_factors', {}).get(k) != v for k, v in owner_proposal['factors'].items())
            or any(native_selection.get(k) != v for k, v in owner_proposal['data'].items())):
        raise TaskConflict('Appointment reception changes the actual owner selection or selected professional')
    objects = deepcopy(plan.objects)
    by_ref = {task_digest(r['ref']): r['value'] for r in objects}
    original = {task_digest(r['ref']): r['projection'] for r in provider['source_reading']}
    previous_plan, = [v for v in p.plans if (v.organization_id, v.project_id, v.tick)
        == (plan.organization_id, plan.project_id, plan.tick)]
    if previous_plan.opportunity is not None:
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
        technical = _original_intake(p, identity)
        handoff = p.opportunity.handoff(previous_plan,
            AgentProposalRequestV1.model_validate(technical['native_request']))
        if handoff != technical['observed'].get('opportunity_handoff'):
            raise TaskConflict('Appointment reception changes its original A01 interest consumed by A02')
        evidence_binding(objects, previous_plan.opportunity.handoff_evidence_ref.model_dump(mode='json'), handoff)
    for row in previous_plan.objects:
        key = task_digest(row['ref'])
        if key not in by_ref or key not in original:
            raise TaskConflict('Appointment receipt omits an original independently read professional source')
        if row['ref'] == previous_plan.native_evidence_ref.model_dump(mode='json'):
            evidence_binding(objects, row['ref'], _original_observed(p, identity))
        if by_ref[key] != original[key]:
            raise TaskConflict('Appointment receipt substitutes original service terms, rights, calendar or private source')
    terms_ref = plan.action_input['accepted_terms_ref']
    terms = by_ref[task_digest(terms_ref)]
    accepted_field = 'accepted_terms_ref' if plan.role == 'Architect' else 'terms_ref'
    if (provider['result']['payload'].get(accepted_field) != terms_ref
            or terms.get('scope') != plan.action_input['scope']
            or terms['provider_id'] != plan.context.actor_id or terms['client_id'] != owner_actor
            or terms['payer_id'] != owner_actor or terms['relation'] != 'external'):
        raise TaskConflict('Appointment receipt changes the independently accepted complete original terms')
    owner_sources = {task_digest(r['ref']): r['projection'] for r in owner['source_reading']}
    offer = owner_sources[task_digest(owner['result']['payload']['offer_ref'])]
    selected = owner_sources[task_digest(offer['provider_ref'])]
    owner_terms = owner_sources[task_digest(owner['result']['payload']['terms_ref'])]
    # The owner handoff already validates the explicit different-schema delivery
    # mapping. Reuse that audited origin, not a new guessed ContractTerms mapping.
    owner_records = [r for r in p.owner.records() if r['state'] == 'formed' and r['scope'] == scope]
    if (len(owner_records) != 1 or owner_records[0]['identity'] != owner_identity.as_dict()
            or selected['organization_id'] != plan.organization_id
            or owner_terms['provider_organization_id'] != plan.organization_id):
        raise TaskConflict('Appointment receipt lost its original received commercial handoff')
    owner_record = owner_records[0]
    owner_plan, = [v for v in p.owner.plans if (v.organization_id, v.project_id, v.tick, v.role)
        == (owner_id, plan.project_id, plan.tick, plan.role)]
    if (owner_record['result_sha256'] != owner['result_sha256']
            or owner_record['proposal_response_sha256'] != task_digest(owner_proposal)
            or owner_sources[task_digest(owner_plan.native_evidence_ref.model_dump(mode='json'))]['content_hash']
                != task_digest(owner_record['observed'])
            or owner_sources[task_digest(owner_plan.handoff_evidence_ref.model_dump(mode='json'))]['content_hash']
                != task_digest(owner_record['observed']['providers'])):
        raise TaskConflict('Appointment reception substitutes the audited original owner commercial evidence')
    providers = owner_records[0]['observed']['providers']
    origin, = [v for v in providers if v['provider_id'] == plan.organization_id]
    if origin['result_sha256'] != provider['result_sha256']:
        raise TaskConflict('Appointment receipt uses another provider result than the owner actually received')
    acceptance_ref = by_ref[task_digest(plan.action_input['appointment_ref'])]['acceptance_ref']
    acceptance = by_ref[task_digest(acceptance_ref)]
    appointment = by_ref[task_digest(plan.action_input['appointment_ref'])]
    if (acceptance['choice'] != 'accept' or acceptance['action_id'] != identity.action_id
            or acceptance['accepted_terms_ref'] != terms_ref
            or acceptance['authority_ref'] not in snapshot['context']['authorization_refs']
            or acceptance['request_ref'] != snapshot['action_input']['request_ref']
            or acceptance['organization_id'] != plan.organization_id or acceptance['actor_id'] != plan.context.actor_id
            or acceptance['function_ref'] != snapshot['context']['function_ref']
            or acceptance['decided_at'] != snapshot['context']['business_time']
            or acceptance['received_at'] != plan.context.business_time.model_dump(mode='json')
            or acceptance['terms_digest'] is not None or appointment['terms_digest'] is not None
            or appointment['received_at'] != plan.context.business_time.model_dump(mode='json')
            or appointment['status'] != 'selected' or appointment['service_relationship_ref'] is not None
            or appointment['reservation_ref'] is not None
            or appointment['provider_organization_id'] != plan.organization_id
            or appointment['client_organization_id'] != owner_id or appointment['payer_organization_id'] != owner_id):
        raise TaskConflict('Appointment receipt changes actual acceptance, original terms, reception or formal occupancy')
    acceptance['terms_digest'] = appointment['terms_digest'] = service_terms_digest(terms)
    if plan.role == 'QS':
        _qs_sources(plan, by_ref, original, previous_plan)
    observed = {'event_id': event['event_id'], 'event_sha256': task_digest(event), 'scope': scope,
        'organization_id': plan.organization_id, 'provider_task_key': identity.key,
        'provider_result_sha256': provider['result_sha256'], 'provider_source_reading_sha256': provider['source_reading_sha256'],
        'provider_proposal_sha256': task_digest(proposal), 'provider_final_sha256': task_digest(final),
        'owner_task_key': owner_identity.key, 'owner_result_sha256': owner['result_sha256'],
        'owner_proposal_sha256': task_digest(owner_proposal), 'owner_final_sha256': task_digest(owner_final),
        'acceptance_event_id': acceptance_events[0]['event_id'], 'owner_handoff_record_sha256': owner_records[0]['record_sha256']}
    evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), observed)
    evidence_binding(objects, plan.acceptance_evidence_ref.model_dump(mode='json'), provider['result'])
    if plan.role == 'QS':
        # These older intake versions use different closed view schemas; they
        # were authenticated above, but cannot be passed as A03 typed objects.
        old_refs = [previous_plan.action_input['capacity_ref'], previous_plan.action_input['conflict_check_ref']]
        objects = [r for r in objects if r['ref'] not in old_refs]
    return objects, observed


def _original_intake(p, identity):
    with p.assembly.client.tasks._lock:
        raws = p.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?', (p.PREFIX + '%',)).fetchall()
    records = [json.loads(raw) for raw, in raws]
    records = [r for r in records if r.get('identity') == identity.as_dict() and r['state'] == 'formed']
    if (len(records) != 1 or records[0]['record_sha256'] != task_digest(
            {k: v for k, v in records[0].items() if k != 'record_sha256'})
            or records[0]['source_file_sha256'] != p.settings.file_sha256):
        raise TaskConflict('Appointment receipt lost original professional intake source binding')
    return records[0]


def _original_observed(p, identity):
    return _original_intake(p, identity)['observed']


def _qs_sources(plan, by_ref, original, previous_plan):
    calendar = by_ref[task_digest(plan.action_input['capacity_ref'])]
    before = original[task_digest(previous_plan.action_input['capacity_ref'])]
    common = deepcopy(calendar)
    common['ref'] = before['ref']
    for r in common['resources']:
        r.pop('personnel_ids', None)
        r.pop('suitable', None)
    if common != before:
        raise TaskConflict('QS appointment cannot change its original physical capacity or commitments')
    appointment = by_ref[task_digest(plan.action_input['appointment_ref'])]
    check = by_ref[task_digest(appointment['conflict_check_ref'])]
    old_check = original[task_digest(previous_plan.action_input['conflict_check_ref'])]
    common = {k: v for k, v in check.items() if k not in {'author_actor_id', 'author_function_ref', 'authority_ref'}}
    common['ref'] = old_check['ref']
    if (common != old_check or check['author_actor_id'] != plan.context.actor_id
            or check['author_function_ref'] != plan.context.function_ref.model_dump(mode='json')
            or check['authority_ref'] not in [r.model_dump(mode='json') for r in plan.context.authorization_refs]
            or appointment['task_refs'] or appointment['existing_allocation_refs'] or appointment['prior_plan_ref'] is not None):
        raise TaskConflict('QS appointment substitutes independently declared conflict check or creates an unsupplied task allocation')
