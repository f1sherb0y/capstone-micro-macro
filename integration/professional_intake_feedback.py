"""Own appointment observations and authenticated later service-intake memory."""
from copy import deepcopy

from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest

ROLE_FIELD = {'Architect': 'architect_id', 'Engineer': 'engineer_id', 'QS': 'qs_id'}


def authenticate_appointment(assembly, *, event, organization_id):
    """Authenticate actual selection and this recipient's original acceptance.

    Selection proves only the native team membership. It creates no detailed
    service appointment, released task, fee, qualification or performance fact.
    """
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    client, engine = assembly.client, assembly.engine
    role = client.organization_roles.get(organization_id)
    project = engine.projects.get(event['project_id'])

    def original(value):
        value = deepcopy(value)
        diagnostics = value['data'].pop('agent_observer_errors', [])
        if not isinstance(diagnostics, list) or any(not isinstance(d, str) for d in diagnostics):
            raise TaskConflict('Professional appointment has invalid native observer diagnostics')
        return value

    def authenticate(value):
        global_rows = [e.model_dump(mode='json') for e in engine.events.events if e.event_id == value['event_id']]
        local_rows = [] if project is None else [e for e in project.event_log if e['event_id'] == value['event_id']]
        if (len(global_rows) != 1 or len(local_rows) != 1
                or task_digest(original(global_rows[0])) != task_digest(original(value))
                or task_digest(original(local_rows[0])) != task_digest(original(value))):
            raise TaskConflict('Professional appointment lost its exact original global/project event')

    authenticate(event)
    reception = project_professional_event(AgentObservationV1.model_validate(event), client.organization_roles)
    received = [r for r in client.inbox.for_organization(run_id=client.run_id, organization_id=organization_id)
                if r['event_id'] == event['event_id']]
    if (role not in ROLE_FIELD or event['event_type'] != 'consultant_team_appointed'
            or project is None or event['agent_id'] != project.owner_id
            or event['data'].get('owner_id') != project.owner_id
            or event['data'].get(ROLE_FIELD.get(role)) != organization_id
            or organization_id not in reception or len(received) != 1
            or task_digest(received[0]['payload']) != task_digest(reception[organization_id])):
        raise TaskConflict('Professional appointment is not an actual own selection and recipient reception')
    acceptances = [e for e in project.event_log if e['event_type'] == 'appointment_decision'
        and e['tick'] == event['tick'] and e['agent_id'] == organization_id and e['data'].get('role') == role]
    if len(acceptances) != 1 or acceptances[0]['data'].get('accepted') is not True:
        raise TaskConflict('Professional appointment requires its original own accepted intake decision')
    acceptance, = acceptances
    authenticate(acceptance)
    own = authenticate_intake_decision(assembly, event=acceptance, organization_id=organization_id)
    return {**own, 'event_id': event['event_id'], 'status': 'appointed',
        'acceptance_event_id': acceptance['event_id'], 'acceptance_event_sha256': task_digest(original(acceptance)),
        'recipient_projection': deepcopy(reception[organization_id])}


def recorded_appointment_feedback(application, *, organization_id, appointments):
    """Attach only completed own A12 records to already authenticated history.

    Legacy decision-only configurations keep their existing native history.
    A declared selection-feedback plan must have its original formed result;
    querying an absent/unknown result never replays its worker.
    """
    histories = deepcopy(appointments)
    for prior in histories:
        plans = [p for p in application.plans if p.organization_id == organization_id
            and (p.project_id, p.tick, p.event_type) ==
                (prior['project_id'], prior['tick'], 'consultant_team_appointed')
            and p.appointment_feedback_ref is not None]
        if not plans:
            continue
        if len(plans) != 1 or prior['organization_id'] != organization_id:
            raise TaskConflict('Professional history requires one original own selection-feedback plan')
        plan, = plans
        journal = application._record(plan)
        queried = application.query_saved_result(plan.plan_id)
        if (journal is None or journal['state'] != 'formed' or queried['status'] != 'saved'
                or queried['task_state'] != 'output_formed'):
            raise TaskConflict('Professional history awaits its original completed selection feedback')
        saved = queried['record']
        result = saved['result']
        if (journal['observed']['event_id'] != prior['event_id']
                or journal['observed']['data']['status'] != 'appointed'
                or journal['observed']['data']['micro_result_sha256'] != prior['micro_result_sha256']
                or result['kind'] != 'completed'
                or plan.private_intake_judgment is None and (result['payload']['choice'] != 'record_feedback'
                    or result['payload']['feedback_refs'] != [plan.appointment_feedback_ref.model_dump(mode='json')])
                or saved['result_sha256'] != journal['result_sha256']):
            raise TaskConflict('Professional history substitutes its actual selection or original private feedback')
        if plan.private_intake_judgment is not None:
            recommendation = application._private_learning.recommendation(plan, saved)
            prior['private_feedback'] = {'identity': deepcopy(queried['identity']),
                'result_sha256': saved['result_sha256'], 'event_id': prior['event_id'],
                'intake_recommendation': recommendation}
        else:
            prior['private_feedback'] = {'identity': deepcopy(queried['identity']),
            'result_sha256': saved['result_sha256'], 'event_id': prior['event_id'],
            'interpretation': result['payload']['interpretation']}
    return histories


def authenticate_intake_decision(assembly, *, event, organization_id):
    """Read the recipient's original decision and transports, without declaring an appointment.

    The caller authenticates the native global/project event. This function
    additionally requires actual reception and the same formed A02 result,
    proposal and final decision; another firm's private results are never read.
    """
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    client = assembly.client
    role = client.organization_roles.get(organization_id)
    scope = {'project_id': event['project_id'], 'tick': event['tick'], 'role': role}
    expected = project_professional_event(AgentObservationV1.model_validate(event), client.organization_roles)
    received = [r for r in client.inbox.for_organization(run_id=client.run_id, organization_id=organization_id)
                if r['event_id'] == event['event_id']]
    accepted = event['data'].get('accepted')
    action = {'Architect': 'design', 'Engineer': 'engineering', 'QS': 'qs'}.get(role)
    action = ('accept_' if accepted else 'decline_') + str(action) + '_appointment'
    factors = event['data'].get('decision_factors', {})
    if (role not in ROLE_FIELD or event['event_type'] != 'appointment_decision'
            or event['agent_id'] != organization_id or type(accepted) is not bool
            or event['data'].get('role') != role or event['data'].get('action_type') != action
            or factors.get('native_professional_scope') != scope
            or organization_id not in expected or len(received) != 1
            or received[0]['payload'] != expected[organization_id]):
        raise TaskConflict('Professional feedback lost its actual own intake decision or recipient reception')
    tasks = client.tasks.for_organization(run_id=client.run_id, organization_id=organization_id)
    micro = [t for t in tasks if t['identity']['purpose'] == 'action'
        and t['identity']['action_id'] == role.upper() + '-A02'
        and TaskIdentity(**t['identity']).key == factors.get('micro_task_key')]
    if len(micro) != 1:
        raise TaskConflict('Professional feedback has no unique original own A02 task')
    original = micro[0]
    identity = TaskIdentity(**original['identity'])
    snapshot = InvocationSnapshotStore(client.tasks).get(identity)
    context = snapshot['context']
    if (original['state'] != 'output_formed' or original['output_sha256'] != task_digest(original['output'])
            or original['output_sha256'] != factors.get('micro_result_sha256')
            or factors.get('micro_action_id') != role.upper() + '-A02'
            or context['run_id'] != client.run_id or context['scope']['kind'] != 'project'
            or context['scope']['ref']['id'] != event['project_id']
            or context['business_time']['offset'] != event['tick']
            or original['output'].get('kind') != 'completed'
            or original['output']['payload']['choice'] != ('accept' if accepted else 'decline')):
        raise TaskConflict('Professional feedback changes its original formed A02 result, scope or clock')
    transports = {}
    for purpose, operation, field, decision_field in (
            ('propose', 'consider_appointment', 'factors', 'accepted'),
            ('decide', role.lower() + '_appointment_acceptance', 'data', 'decision')):
        matches = [t for t in tasks if t['identity']['purpose'] == purpose
            and t['identity']['action_id'] == operation
            and (t.get('output') or {}).get(field, {}).get('native_professional_scope') == scope]
        if len(matches) != 1:
            raise TaskConflict('Professional feedback lost its unique original proposal or final decision')
        task = matches[0]
        output = task['output']
        if (task['state'] != 'output_formed' or task['output_sha256'] != task_digest(output)
                or output.get(decision_field) is not accepted or output.get('action_type') != action
                or any(output.get(field, {}).get(k) != factors.get(k) for k in
                    ('micro_action_id', 'micro_task_key', 'micro_result_sha256'))):
            raise TaskConflict('Professional feedback substitutes its original bounded proposal/final decision')
        transports[purpose + '_sha256'] = task['output_sha256']
    return {'event_id': event['event_id'], 'project_id': event['project_id'], 'tick': event['tick'],
        'organization_id': organization_id, 'role': role, 'accepted': accepted,
        'status': 'accepted_pending_owner_selection' if accepted else 'declined',
        'micro_identity': identity.as_dict(), 'micro_result_sha256': original['output_sha256'],
        'recipient_projection': deepcopy(expected[organization_id]), **transports}


def project_professional_event(observation, organization_roles):
    if not observation.committed or not isinstance(organization_roles, dict):
        return {}
    if observation.event_type == 'appointment_decision':
        organization = observation.agent_id
        role = organization_roles.get(organization)
        factors = observation.data.get('decision_factors', {})
        if role not in ROLE_FIELD or factors.get('micro_action_id') != role.upper() + '-A02':
            return {}
        data = {name: observation.data.get(name) for name in ('role', 'purpose', 'action_type', 'accepted')}
        data.update({name: factors.get(name) for name in ('micro_action_id', 'micro_task_key', 'micro_result_sha256',
                                                         'native_professional_scope')})
        recipients = {organization: data}
    elif observation.event_type == 'consultant_team_appointed':
        recipients = {}
        for role, field in ROLE_FIELD.items():
            organization = observation.data.get(field)
            if organization is not None and organization_roles.get(organization) == role:
                recipients[organization] = {'organization_id': organization, 'role': role,
                    'owner_id': observation.data.get('owner_id'), 'selected': True}
        from integration.owner_commission_native_feedback import owner_commission_recipients
        recipients.update(owner_commission_recipients(observation,organization_roles))
    else:
        return {}
    return {organization: {'event_type': observation.event_type, 'tick': observation.tick,
        'project_id': observation.project_id, 'agent_id': observation.agent_id, 'committed': True, 'data': data}
        for organization, data in recipients.items()}


def prior_appointments(assembly, *, organization_id, tick):
    """Count real earlier own appointments, never intentions or other firms' work."""
    client, engine = assembly.client, assembly.engine
    role = client.organization_roles.get(organization_id)
    if role not in ROLE_FIELD or type(tick) is not int or tick != engine.current_tick:
        raise TaskConflict('Professional memory requires its original current organization and native clock')
    inbox = client.inbox.for_organization(run_id=client.run_id, organization_id=organization_id)
    origins = []
    for entry in inbox:
        payload = entry['payload']
        if payload['event_type'] != 'consultant_team_appointed' or payload['tick'] >= tick:
            continue
        project = engine.projects.get(payload['project_id'])
        events = [] if project is None else [e for e in project.event_log if e['event_id'] == entry['event_id']]
        if (len(events) != 1 or events[0]['event_type'] != 'consultant_team_appointed'
                or events[0]['tick'] != payload['tick'] or events[0]['agent_id'] != project.owner_id
                or events[0]['data'].get(ROLE_FIELD[role]) != organization_id
                or payload['data'] != {'organization_id': organization_id, 'role': role, 'owner_id': project.owner_id, 'selected': True}):
            raise TaskConflict('Professional memory substitutes its actual native appointment or recipient')
        acceptance = [e for e in project.event_log if e['event_type'] == 'appointment_decision'
            and e['agent_id'] == organization_id and e['tick'] == payload['tick'] and e['data'].get('role') == role]
        if len(acceptance) != 1 or acceptance[0]['data'].get('accepted') is not True:
            raise TaskConflict('Actual appointment has no unique original independent professional acceptance')
        factors = acceptance[0]['data'].get('decision_factors', {})
        sha = factors.get('micro_result_sha256')
        micro = [t for t in client.tasks.for_organization(run_id=client.run_id, organization_id=organization_id)
                 if t['identity']['action_id'] == role.upper() + '-A02' and t['identity']['purpose'] == 'action'
                 and t['state'] == 'output_formed' and t['output_sha256'] == sha
                 and TaskIdentity(**t['identity']).key == factors.get('micro_task_key')]
        if (len(micro) != 1 or micro[0]['output']['kind'] != 'completed'
                or micro[0]['output']['payload']['choice'] != 'accept'):
            raise TaskConflict('Professional memory lost its original completed A02 acceptance')
        scope = {'project_id': project.project_id, 'tick': payload['tick'], 'role': role}
        if factors.get('native_professional_scope') != scope:
            raise TaskConflict('Professional memory changes its original project and appointment time')
        originals = client.tasks.for_organization(run_id=client.run_id, organization_id=organization_id)
        for action, purpose in [('consider_appointment', 'propose'), (role.lower() + '_appointment_acceptance', 'decide')]:
            matches = [t for t in originals if t['identity']['action_id'] == action and t['identity']['purpose'] == purpose
                and t['state'] == 'output_formed'
                and t['output'].get('factors' if purpose == 'propose' else 'data', {}).get('native_professional_scope') == scope]
            if len(matches) != 1 or matches[0]['output'].get('factors' if purpose == 'propose' else 'data', {}).get('micro_result_sha256') != sha:
                raise TaskConflict('Professional memory lost the original formed proposal or final acceptance')
        origins.append({'event_id': entry['event_id'], 'project_id': project.project_id, 'tick': payload['tick'],
            'organization_id': organization_id, 'role': role, 'acceptance_event_id': acceptance[0]['event_id'],
            'micro_result_sha256': sha})
    if len({o['event_id'] for o in origins}) != len(origins):
        raise TaskConflict('Professional memory repeats the same actual appointment')
    return sorted(origins, key=lambda o: (o['tick'], o['project_id'], o['event_id']))
