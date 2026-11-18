"""Clip actual Owner invitation effects; share only a recipient's own origin link."""
import json

from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def project_owner_invitation_event(observation, organization_roles):
    if (not observation.committed or observation.event_type != 'tender_opened'
            or not isinstance(organization_roles, dict)
            or organization_roles.get(observation.agent_id) != 'Owner'):
        return {}
    decision = observation.data.get('owner_shortlist_decision', {})
    factors = decision.get('decision_factors', {})
    if factors.get('micro_action_id') != 'OWN-A09':
        return {}
    invited = [row['contractor_id'] for row in observation.data.get('invited_contractors', [])]
    if len(invited) != len(set(invited)) or observation.data.get('invited_count') != len(invited):
        raise TaskConflict('Owner invitation event has inconsistent actual recipients')
    # Candidate dossiers, scores, other firms' resources, project snapshots and
    # internal rationale do not enter the Owner's business-feedback projection.
    data = {'invited_contractor_ids': invited, 'invited_count': len(invited), 'micro_action_id': 'OWN-A09',
        **{name: factors.get(name) for name in ('micro_result_sha256', 'micro_task_key')},
        'proposal_request_id': decision.get('proposal_request_id')}
    return {observation.agent_id: {'event_type': observation.event_type, 'tick': observation.tick,
        'project_id': observation.project_id, 'agent_id': observation.agent_id, 'committed': True, 'data': data}}


def own_invitation_origin(engine, client, *, project, organization_id):
    """Authenticate a native invitation before linking an original OWN-A09.

    The host may inspect the original journal, but the Contractor receives only
    its own invitation identity and public result digest, never Owner sources.
    Native-only invitations retain their existing source path without a
    fabricated micro link.
    """
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1

    events = [event for event in project.event_log if event.get('event_type') == 'tender_opened']
    if not events:
        return None
    event = AgentObservationV1.model_validate(events[-1])
    if event.agent_id != project.owner_id or event.tick > engine.current_tick:
        raise TaskConflict('Invitation origin changes actual Owner or event time')
    payloads = project_owner_invitation_event(event, client.organization_roles)
    if not payloads:
        return None
    payload = payloads[project.owner_id]
    link = payload['data']
    if organization_id not in link['invited_contractor_ids']:
        raise TaskConflict('Current invitation membership is absent from the latest actual opening event')
    with client.tasks._lock:
        original = client.tasks._db.execute('SELECT record FROM owner_tender_results WHERE task_key=?',
            (link['micro_task_key'],)).fetchone()
    if original is None:
        raise TaskConflict('Invitation origin has no original Owner micro result')
    record = json.loads(original[0])
    identity = TaskIdentity(**record['identity'])
    task = client.tasks.get(identity)
    expected_proposal = f'proposal-tick{event.tick}-{project.project_id}-{project.owner_id}-select_tender_invitees'
    if (identity.organization_id != project.owner_id or identity.action_id != 'OWN-A09'
            or identity.request_id != 'owner-invitation:' + expected_proposal
            or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
            or record['result_sha256'] != link['micro_result_sha256']
            or task_digest(record['result']) != link['micro_result_sha256']
            or task['state'] != 'output_formed' or task['output'] != record['result']
            or record['result']['kind'] != 'completed' or record['result']['payload']['choice'] != 'invite'
            or set(record['result']['payload']['bidder_ids']) != set(link['invited_contractor_ids'])
            or link['proposal_request_id'] != expected_proposal):
        raise TaskConflict('Invitation origin substitutes its original completed Owner result or actual recipients')
    originals = client.tasks.for_organization(run_id=client.run_id, organization_id=project.owner_id)
    for purpose, action, request_id in [('propose', 'select_tender_invitees', expected_proposal),
            ('decide', 'owner_tender_shortlist', f'tick{event.tick}-{project.project_id}-{project.owner_id}-owner_tender_shortlist')]:
        rows = [row for row in originals if row['identity']['purpose'] == purpose
            and row['identity']['action_id'] == action and row['identity']['request_id'] == request_id]
        if len(rows) != 1 or rows[0]['state'] != 'output_formed':
            raise TaskConflict('Invitation origin lacks its original formed native proposal or final choice')
        response = rows[0]['output']
        evidence = response['factors'] if purpose == 'propose' else response['data']
        if evidence.get('micro_result_sha256') != link['micro_result_sha256']:
            raise TaskConflict('Invitation origin native response changes its original Owner result')
    return {'event_id': event.event_id, 'tick': event.tick, 'project_id': project.project_id,
        'owner_id': project.owner_id, 'recipient_organization_id': organization_id,
        'micro_action_id': 'OWN-A09', 'micro_result_sha256': link['micro_result_sha256'],
        'proposal_request_id': expected_proposal}
