"""Query original durable monthly feedback without executing it again."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def original_monthly_work(app, request):
    plan, scope = app._current(request)
    if not app.settings.allow_saved_recovery:
        raise TaskConflict('Monthly feedback recovery requires explicit allow_saved_recovery configuration')
    key = app.PREFIX + task_digest([app.assembly.client.simulation_id, scope, request.request_id])
    records = [r for r in app._records() if r['key'] == key]
    if len(records) != 1:
        raise TaskConflict('Monthly feedback recovery requires its existing original workflow')
    record = records[0]
    if (record['scope'] != scope or record['native_request'] != request.model_dump(mode='json')
            or record['state'] not in {'preparing', 'formed'} or 'identity' not in record
            or record['context'] != plan.feedback.context.model_dump(mode='json')
            or record['action_input'] != plan.feedback.action_input
            or record['native_evidence_ref'] != plan.feedback.native_evidence_ref.model_dump(mode='json')):
        raise TaskConflict('Monthly feedback recovery changes its original request, input or registration')
    objects, observed = app._sources(plan, request)
    if task_digest(objects) != record['source_sha256'] or observed != record['observed']:
        raise TaskConflict('Monthly feedback recovery changes its original currently authorized sources')
    identity = TaskIdentity(**record['identity'])
    if (identity.organization_id != plan.organization_id or identity.request_id != key + ':GOV-A12'
            or identity.purpose != 'action'):
        raise TaskConflict('Monthly feedback recovery changes its original task identity')
    return plan, scope, record, identity


def validate_saved_monthly_stage(app, row, saved, snapshot):
    with app.parent.read_guard():
        identity = TaskIdentity(**row['identity'])
        bound = app._bound.get(identity.context_sha256)
        if bound is None:
            raise TaskConflict('Monthly feedback recovery lacks its original source binding')
        plan, request = bound
        current, _, record, original = original_monthly_work(app, request)
        if (current != plan or original != identity or snapshot != app.worker.snapshots.get(identity)
                or snapshot['context'] != record['context'] or snapshot['action_input'] != record['action_input']
                or saved != app.worker.get_record(identity) or saved['result'].get('kind') != 'completed'
                or saved['result']['payload']['choice'] != 'record_feedback'):
            raise TaskConflict('Monthly feedback recovery substitutes its original invocation or result')
        return True


def recover_saved_monthly_proposal(app, request):
    with app.parent.read_guard():
        plan, scope, record, identity = original_monthly_work(app, request)
        app._bound[task_digest(record['context'])] = (plan, request.model_copy(deep=True))
        prepared = app.assembler.build(plan.feedback.context, **deepcopy(plan.feedback.action_input))
        if (app.worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity
                or app.worker.snapshots.get(identity)['context'] != record['context']
                or app.worker.snapshots.get(identity)['action_input'] != record['action_input']):
            raise TaskConflict('Monthly feedback recovery changes its original context, input or execution versions')
        saved = app.worker.get_record(identity)
        if saved is None or saved['result'].get('kind') != 'completed':
            raise TaskConflict('Interrupted monthly feedback has no saved completed result; no processor replay is allowed')
        if record.get('result_sha256') not in {None, saved['result_sha256']}:
            raise TaskConflict('Monthly feedback recovery conflicts with its original result')
        task = app.worker.store.get(identity)
        if task['state'] == 'processing':
            app.worker._finalize(identity, saved, recovered=True)
        elif task['state'] != 'output_formed':
            raise TaskConflict('Monthly feedback has unresolved wait/failure state; explicit diagnosis required')
        checked_result(app.worker, identity)
        saved = app._result(plan, record)
        response = app._proposal_response(request, scope, identity, saved)
        digest = task_digest(response.model_dump(mode='json'))
        if record.get('proposal_response_sha256') not in {None, digest}:
            raise TaskConflict('Recovered monthly feedback differs from its original proposal')
        if record['state'] != 'formed' or record.get('proposal_response_sha256') is None:
            record.update(state='formed', result_sha256=saved['result_sha256'], proposal_response_sha256=digest)
            app.parent._save(record['key'], record)
        return response
