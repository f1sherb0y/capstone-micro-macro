"""Read one original native approval outcome; absence remains unknown."""
from copy import deepcopy

from integration.government_approval_native_feedback import prior_approval_decisions
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def _matching_native_events(record, project_events, global_events):
    """Compare original logs without treating a missing reply as nonexecution."""
    scope = record['scope']

    def matches(event):
        if event['project_id'] != scope['project_id'] or event['tick'] != scope['tick']:
            return False
        if scope['purpose'] == 'design_approval':
            return event['event_type'] in {'approval_approved', 'approval_rejected'}
        return event['event_type'] == 'project_completed' or (
            event['event_type'] == 'quality_issue' and event['data'].get('completion_decision') is not None)

    project = [deepcopy(e) for e in project_events if matches(e)]
    global_ = [deepcopy(e) for e in global_events if matches(e)]
    if (len({e['event_id'] for e in project}) != len(project)
            or len({e['event_id'] for e in global_}) != len(global_)
            or {e['event_id']: task_digest(e) for e in project} != {
                e['event_id']: task_digest(e) for e in global_}):
        raise TaskConflict('Approval query requires matching original global and project native events')
    if len(project) > 1:
        raise TaskConflict('Approval query has ambiguous native execution outcomes')
    return project


def query_native_approval_outcome(app, identity, *, organization_id, tick):
    """No processor, transport, reconciliation, clock advancement or resubmission."""
    identity = TaskIdentity(**(identity.as_dict() if isinstance(identity, TaskIdentity) else identity))
    with app.parent.read_guard():
        app.parent._check()
        app.check_components()
        client, engine = app.assembly.client, app.assembly.engine
        if (identity.run_id != client.run_id or identity.organization_id != organization_id
                or identity.role != 'Government' or identity.action_id != 'GOV-A07'
                or identity.purpose != 'action' or client.organization_roles.get(organization_id) != 'Government'
                or type(tick) is not int or tick != engine.current_tick):
            raise TaskConflict('Approval query changes the original organization, action or current native clock')
        rows = [r for r in app._records() if r.get('decision_identity') == identity.as_dict()]
        if len(rows) != 1:
            raise TaskConflict('Approval query needs its one original registered workflow')
        record = rows[0]
        scope, original = record['scope'], record['native_request']
        if (record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                or record['key'] != app.PREFIX + task_digest([
                    client.simulation_id, organization_id, scope, original['request_id']])
                or record['state'] not in {'preparing', 'formed', 'waiting_input'}
                or original['agent']['agent_id'] != organization_id or original['operation'] != 'decide_approval'
                or scope.get('purpose') not in {'design_approval', 'completion_approval'}
                or type(scope.get('tick')) is not int or not 1 <= scope['tick'] <= tick):
            raise TaskConflict('Approval query substitutes its original workflow, request or scope')
        plans = [p for p in app.plans if (p.organization_id, p.project_id, p.tick, p.review_phase) == (
            organization_id, scope['project_id'], scope['tick'],
            'design' if scope['purpose'] == 'design_approval' else 'completion')]
        if len(plans) != 1:
            raise TaskConflict('Approval query lost its original immutable source plan')
        plan = plans[0]
        saved_decision = None
        for stage, _, worker in app._stages(plan):
            stage_identity = TaskIdentity(**record[stage + '_identity'])
            context = app._stage_context(plan, stage)
            snapshot = worker.snapshots.get(stage_identity)
            if (snapshot['context'] != context.model_dump(mode='json')
                    or snapshot['action_input'] != app._stage_input(plan, stage)
                    or stage_identity.request_id != record['key'] + ':' + context.contract_ref.id
                    or (stage == 'decision' and stage_identity != identity)):
                raise TaskConflict('Approval query changes an original invocation, input or snapshot')
            # Current read authority is checked at the actual query time. The
            # original invocation and its saved historical time are untouched.
            current = context.model_copy(update={
                'business_time': context.business_time.model_copy(update={'offset': tick})}, deep=True)
            grants = app.parent.organizations.grants(current, context.contract_ref.id, 'Government')
            if any(g.organization_id != organization_id for g in grants):
                raise TaskConflict('Approval query borrows another organization authority')
            saved = worker.get_record(stage_identity)
            if saved is not None:
                readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in context.visible_refs}
                if any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading']):
                    raise TaskConflict('Approval query lost current permission for original private sources')
            known = record.get(stage + '_result_sha256')
            if known is not None and (saved is None or known != saved['result_sha256']):
                raise TaskConflict('Approval query conflicts with the original saved result')
            if stage == 'decision':
                saved_decision = saved
        project = engine.projects.get(scope['project_id'])
        if project is None:
            raise TaskConflict('Approval query lost its original native project')
        events = _matching_native_events(record, project.event_log,
            [e.model_dump(mode='json') for e in engine.events.events])
        result = {'schema_version': 'native-government-approval-outcome-query.v1',
            'status': 'unknown', 'run_id': client.run_id, 'simulation_id': client.simulation_id,
            'organization_id': organization_id, 'queried_at_tick': tick,
            'original_decision_identity': identity.as_dict(), 'original_native_request_id': original['request_id'],
            'native_scope': deepcopy(scope),
            'micro_result_sha256': None if saved_decision is None else saved_decision['result_sha256'],
            'native_outcome': None,
            'limits': ['Absence is unknown, not proof of nonexecution or permission to resubmit.',
                       'An original native design/completion outcome is not a detailed signed decision, '
                       'supplement receipt, physical inspection, permit, cash execution or liability release.',
                       'Query is read-only; original tasks, results, waiting conditions and business time are unchanged.']}
        if events:
            outcomes = prior_approval_decisions(app.assembly, organization_id=organization_id, tick=tick,
                read_guard=app.parent.read_guard, include_current=True, decision_task_key=identity.key,
                organizations=app.parent.organizations)
            selected = [r for r in outcomes if r['micro_task_key'] == identity.key]
            if len(selected) != 1 or selected[0]['event_id'] != events[0]['event_id']:
                raise TaskConflict('Approval query lacks one authenticated original native execution outcome')
            result.update(status='observed', native_outcome={**deepcopy(selected[0]),
                'event_type': events[0]['event_type'], 'event_sha256': task_digest(events[0])})
        result['query_sha256'] = task_digest(result)
        return result
