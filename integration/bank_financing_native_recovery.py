"""Return a complete saved Bank pipeline to its still-open original native call."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def saved_financing_preflight(app, request):
    """Validate every original stage before finalizing any technical state."""
    plan, scope = app._current(request)
    if not app.settings.allow_saved_recovery:
        raise TaskConflict('Bank financing recovery requires explicit allow_saved_recovery')
    key = app._key(request)
    records = [row for row in app._records() if row['key'] == key]
    if len(records) != 1:
        raise TaskConflict('Bank financing recovery requires its existing original workflow')
    original = records[0]
    if (original['scope'] != scope or original['native_request'] != request.model_dump(mode='json')
            or original['source_file_sha256'] != app.settings.file_sha256
            or original['state'] not in {'preparing', 'formed'}):
        raise TaskConflict('Bank financing recovery changes its original request, source or workflow')
    # Only a genuine A02 decline or an actual A04 result can finish financing.
    # Incomplete accepted-intake/review work never starts another action here.
    stages = [action for action in app.workers if action in plan.steps]
    registered = [action for action in stages if action in original['steps']]
    if not registered or set(registered) != set(original['steps']):
        raise TaskConflict('Bank financing has no exact original registered action prefix')
    terminal = registered[-1]
    if terminal not in {'BANK-A02', 'BANK-A04'} or registered != stages[:stages.index(terminal) + 1]:
        raise TaskConflict('Bank financing lacks a complete terminal result; no processor replay is allowed')
    record = deepcopy(original)
    if record.get('terminal_action') not in {None, terminal}:
        raise TaskConflict('Bank financing recovery substitutes its original terminal action')
    record['terminal_action'] = terminal
    previous = {}
    for action in registered:
        worker, assembler, step = app.workers[action], app.assemblers[action], plan.steps[action]
        technical = record['steps'][action]
        identity = TaskIdentity(**technical['identity'])
        if (app._bound.get(identity.context_sha256) != (plan, request, action, previous)
                or identity.run_id != app.assembly.client.run_id or identity.organization_id != plan.organization_id
                or identity.action_id != action or identity.role != 'Bank' or identity.purpose != 'action'
                or identity.request_id != key + ':' + action):
            raise TaskConflict('Bank financing recovery changes original in-process binding or task identity')
        saved = worker.get_record(identity)
        if saved is None or saved['result'].get('kind') != 'completed':
            raise TaskConflict('Bank financing has no saved completed result; no processor replay is allowed')
        task = worker.store.get(identity)
        if task['state'] not in {'processing', 'output_formed'} or action != terminal and task['state'] != 'output_formed':
            raise TaskConflict('Bank financing predecessor or unresolved wait requires explicit diagnosis')
        if (task['state'] == 'processing' and (task['revision'] != saved['attempt_revision'] or task['output'] is not None)
                or task['state'] == 'output_formed' and (task['output'] != saved['result']
                    or task['output_sha256'] != saved['result_sha256'])):
            raise TaskConflict('Bank financing recovery changes its original saved-result task state')
        for field in ('result_sha256', 'record_sha256', 'source_reading_sha256'):
            if technical.get(field) not in {None, saved[field]}:
                raise TaskConflict('Bank financing recovery conflicts with its original saved digests')
            technical[field] = saved[field]
        # Read-only assembly: no original processor or method execution.
        prepared = assembler.build(step.context, **deepcopy(step.action_input))
        snapshot = app.snapshots.get(identity)
        if (worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity
                or snapshot['context'] != step.context.model_dump(mode='json')
                or snapshot['action_input'] != prepared.action_input.model_dump(mode='json')
                or prepared.reading.evidence() != saved['source_reading']):
            raise TaskConflict('Bank financing recovery changes original invocation, versions or authorized reading')
        if action != terminal:
            checked_result(worker, identity)
        prepared.reading.recheck()
        previous[action] = saved
    if terminal == 'BANK-A02' and saved['result']['payload']['choice'] != 'decline':
        raise TaskConflict('Accepted or unresolved intake has no terminal financing result; no later action is started')
    terminal, saved, objects, accepted, data = app._terminal(plan, request, record, saved_results=previous)
    response = app._proposal_response(request, plan, scope, record, terminal, saved, accepted, data, prepared.reading)
    digest = task_digest(response.model_dump(mode='json'))
    if record.get('proposal_response_sha256') not in {None, digest}:
        raise TaskConflict('Bank financing recovery conflicts with its original proposal')
    record.update(state='formed', native_summary={'accepted': accepted, 'data': data},
        source_sha256=task_digest(objects), proposal_response_sha256=digest)
    record['record_sha256'] = task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
    if original['state'] == 'formed' and original != record:
        raise TaskConflict('Bank financing recovery changes its already formed original decision')
    return record, terminal, worker, identity, saved, response


def validate_saved_financing_stage(app, row, saved, snapshot):
    with app.read_guard():
        identity = TaskIdentity(**row['identity'])
        bound = app._bound.get(identity.context_sha256)
        if bound is None:
            raise TaskConflict('Bank financing recovery lacks its original source binding')
        _, request, _, _ = bound
        _, _, worker, original, actual, _ = saved_financing_preflight(app, request)
        if original != identity or actual != saved or snapshot != app.snapshots.get(identity):
            raise TaskConflict('Bank financing recovery substitutes its original invocation or result')
        return True


def recover_saved_financing_proposal(app, request):
    with app.read_guard():
        record, _, worker, identity, saved, response = saved_financing_preflight(app, request)
        if worker.store.get(identity)['state'] == 'processing':
            worker._finalize(identity, saved, recovered=True)
        checked_result(worker, identity)
        app._save(record['key'], record)
        return response
