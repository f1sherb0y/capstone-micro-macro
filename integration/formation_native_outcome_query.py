"""Query original contract recommendations and Owner decisions, not signatures."""
from copy import deepcopy

from integration.financing_native_outcome_query import _original_result
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def matching_formation_events(assembly, record, organization_id, *, owner):
    scope = record['scope']
    project = assembly.engine.projects.get(scope['project_id'])
    if project is None or project.owner_id != scope['owner_id']:
        raise TaskConflict('Formation query lost its original native project or Owner')
    event_type = 'owner_contract_award_decision' if owner else 'contract_negotiation_recommendation'
    def matches(event):
        return (event['event_type'] == event_type and event['tick'] == scope['tick']
                and event['project_id'] == scope['project_id'] and event['agent_id'] == organization_id)
    local = [e for e in project.event_log if matches(e)]
    global_events = [e.model_dump(mode='json') for e in assembly.engine.events.events
                     if matches(e.model_dump(mode='json'))]
    if (len(local) > 1 or len({e['event_id'] for e in local}) != len(local)
            or len({e['event_id'] for e in global_events}) != len(global_events)
            or {e['event_id']:task_digest(e) for e in local}
               != {e['event_id']:task_digest(e) for e in global_events}):
        raise TaskConflict('Formation query requires consistent unique original project and global events')
    return local


def query_formation_outcome(app, identity, *, organization_id, tick, owner=False):
    parent = app.parent if owner else app
    with parent.read_guard():
        parent._check()
        if owner:
            app._check()
        identity = TaskIdentity(**(identity.as_dict() if isinstance(identity, TaskIdentity) else identity))
        role, action = ('Owner', 'OWN-A10') if owner else ('Contractor', 'CONTRACTOR-A04')
        client, engine = parent.assembly.client, parent.assembly.engine
        if (type(tick) is not int or tick != engine.current_tick or identity.run_id != client.run_id
                or identity.organization_id != organization_id or identity.role != role
                or identity.action_id != action or identity.purpose != 'action'
                or client.organization_roles.get(organization_id) != role):
            raise TaskConflict('Formation query changes its original organization, action or current business clock')
        records = [r for r in app.records() if r.get('identity') == identity.as_dict()]
        if len(records) != 1:
            raise TaskConflict('Formation query needs its one original formed workflow')
        record, = records
        scope, request = record['scope'], record['native_request']
        if (record['state'] != 'formed' or request['agent']['agent_id'] != organization_id
                or request['agent']['role'] != role or request['operation'] != ('decide_contract_award' if owner else 'decide_contract_terms')
                or scope['owner_id' if owner else 'contractor_id'] != organization_id
                or record['key'] != app.PREFIX + task_digest([client.simulation_id, scope, request['request_id']])
                or not 1 <= scope['tick'] <= tick):
            raise TaskConflict('Formation query substitutes its original request, scope or technical record')
        plans = [p for p in app.plans if (p.organization_id, p.project_id, p.tick) == (
            organization_id, scope['project_id'], scope['tick']) and (
                not owner or p.reviewed_contractor_terms['contractor_id'] == scope['contractor_id'])
            and task_digest(p.context.model_dump(mode='json')) == identity.context_sha256]
        if len(plans) != 1:
            raise TaskConflict('Formation query lost its exact original source plan')
        plan, = plans
        saved = _original_result(parent, identity, app.worker, plan.context, plan.action_input,
                                 key=record['key'], tick=tick)
        evidence = [r['projection'] for r in saved['source_reading']
                    if r['ref'] == plan.native_evidence_ref.model_dump(mode='json')]
        if (saved['result_sha256'] != record['result_sha256'] or len(evidence) != 1
                or evidence[0]['content_hash'] != task_digest(record['observed'])
                or record['observed']['scope'] != scope
                or record['observed']['native_request_sha256'] != task_digest(request)):
            raise TaskConflict('Formation query changes its original result or bound native request')
        events = matching_formation_events(parent.assembly, record, organization_id, owner=owner)
        outcome = None
        if events:
            if owner:
                from integration.owner_award_native_sources import prior_owner_awards
                history = prior_owner_awards(app, owner_id=organization_id, tick=tick,
                                             include_current=True, decision_task_key=identity.key)
            else:
                from integration.contractor_formation_native_sources import prior_negotiations
                history = prior_negotiations(app, organization_id=organization_id, tick=tick,
                                             include_current=True, decision_task_key=identity.key)
            if len(history) != 1 or history[0]['event_id'] != events[0]['event_id']:
                raise TaskConflict('Formation query lost its authenticated exact original native result')
            accepted, native_action = app.summary(saved)
            outcome = {**history[0], 'event_type':events[0]['event_type'], 'accepted':accepted,
                       'action_type':native_action, 'event_sha256':task_digest(events[0])}
        result = {'schema_version':'native-formation-outcome-query.v1',
            'status':'unknown' if outcome is None else 'observed', 'run_id':identity.run_id,
            'simulation_id':client.simulation_id, 'organization_id':organization_id, 'queried_at_tick':tick,
            'original_decision_identity':identity.as_dict(), 'native_scope':deepcopy(scope),
            'micro_result_sha256':saved['result_sha256'], 'native_outcome':deepcopy(outcome), 'resubmitted':False,
            'limits':['Original Contractor recommendation or Owner decision only; acceptance is not a later native signature, detailed agreement registration, resource reservation or payment.',
                      'Missing outcome remains unknown. No processor replay, new tasks, feedback redelivery or native resubmission.']}
        result['query_sha256'] = task_digest(result)
        return result
