"""Technical waits for original private prerequisites, never business retries."""
from copy import deepcopy

from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, task_digest


def authorize_private_sources(app, plan, *, source_reading=()):
    role = app.assembly.client.organization_roles[plan.organization_id]
    tick = app.assembly.engine.current_tick
    if type(tick) is not int or tick < plan.tick:
        raise TaskConflict('Lifecycle private read changes its actual current business clock')
    current = plan.context.model_copy(update={
        'business_time': plan.context.business_time.model_copy(update={'offset': tick})}, deep=True)
    grants = app.authority.organizations.grants(current, plan.context.contract_ref.id, role)
    if not grants or any(g.organization_id != plan.organization_id for g in grants):
        raise TaskConflict('Lifecycle dependency lost its current original organization authority')
    readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in plan.context.visible_refs}
    if any(Reference.model_validate(r['ref']).key() not in readable for r in source_reading):
        raise TaskConflict('Lifecycle dependency lost permission for its original private sources')
    return grants


def validate_dependency_wait(app, plan, record):
    """Recheck a never-started plan, including its exact actual retained event."""
    authorize_private_sources(app, plan)
    events = [e for e in app.assembly.engine.events.events if e.event_id == record['observed']['event_id']]
    if (record['state'] != 'waiting_dependencies' or not plan.depends_on or len(events) != 1
            or app.assembly.engine.current_tick < plan.tick
            or record['observed'] != app._event(plan, events[0])
            or record.get('source_file_sha256') != app.settings.file_sha256
            or record.get('independent_source_sha256') != task_digest(plan.objects)
            or record.get('formal_effect') != 'not_submitted'
            or not record.get('dependency_waits')
            or any(row.get('plan_id') not in plan.depends_on for row in record['dependency_waits'])
            or 'identity' in record or app._saved_identity(plan, record) is not None):
        raise TaskConflict('Lifecycle dependency wait changes its original event, source or unstarted identity')
    return events[0]


def pending_dependencies(app, plan):
    """Read original outcomes; an unknown execution is never retried here."""
    pending = []
    for key in plan.depends_on:
        before = app._by_id[key]
        authorize_private_sources(app, before)
        record = app._record(before)
        if record is None:
            pending.append({'plan_id': key, 'state': 'not_started'})
        elif record['state'] == 'waiting_dependencies':
            validate_dependency_wait(app, before, record)
            pending.append({'plan_id': key, 'state': 'waiting_dependencies'})
        elif record['state'] in {'formed', 'unresolved'}:
            original = app.query_saved_result(key)
            if original['status'] != 'saved':
                raise TaskConflict('Lifecycle dependency lost its original saved outcome')
            saved = original['record']
            if record['state'] == 'formed':
                if saved['result']['kind'] != 'completed' or original['task_state'] != 'output_formed':
                    raise TaskConflict('Lifecycle dependency substitutes a completed original action')
            else:
                if saved['result']['kind'] == 'completed' or original['task_state'] not in {'waiting_input', 'technical_failure'}:
                    raise TaskConflict('Lifecycle dependency substitutes an unresolved original action')
                pending.append({'plan_id': key, 'state': 'unresolved',
                    'result_kind': saved['result']['kind'], 'result_sha256': saved['result_sha256']})
        elif record['state'] in {'preparing', 'processing'}:
            pending.append({'plan_id': key, 'state': 'unknown_execution',
                'record_state': record['state'], 'requires_original_saved_result_query': True})
        else:
            raise TaskConflict('Lifecycle dependency has an unknown original journal state')
    return pending


def retain_dependency_wait(app, plan, event, prior, *, resume=False):
    """Return a wait without registering, calculating, sending or submitting."""
    if prior is not None:
        validate_dependency_wait(app, plan, prior)
    pending = pending_dependencies(app, plan)
    if not pending and (prior is None or resume):
        return False
    if prior is None:
        if app.assembly.engine.current_tick != plan.tick:
            raise TaskConflict('Lifecycle dependency wait cannot start at a historical clock')
        authorize_private_sources(app, plan)
        app._save(plan, {'state': 'waiting_dependencies', 'observed': app._event(plan, event),
            'source_file_sha256': app.settings.file_sha256,
            'independent_source_sha256': task_digest(plan.objects),
            'dependency_waits': deepcopy(pending), 'formal_effect': 'not_submitted'})
    return True


def query_dependency_wait(app, plan, record):
    event = validate_dependency_wait(app, plan, record)
    pending = pending_dependencies(app, plan)
    return {'status': 'waiting_dependencies', 'plan_id': plan.plan_id,
        'event_id': event.event_id, 'initial_dependency_waits': deepcopy(record['dependency_waits']),
        'pending_dependencies': pending, 'dependencies_ready': not pending,
        'continuation': 'explicit_current_tick_only', 'original_action_registered': False,
        'formal_effect': 'not_submitted'}
