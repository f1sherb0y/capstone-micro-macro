"""Recover the original saved review-willingness response, never missing work."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def original_intake_work(app, request):
    plan, scope = app._current(request)
    if not app.settings.allow_saved_recovery:
        raise TaskConflict('Intake recovery requires explicit allow_saved_recovery configuration')
    key = app.PREFIX + task_digest([app.assembly.client.simulation_id, plan.organization_id, scope, request.request_id])
    records = [r for r in app._records() if r['key'] == key]
    if len(records) != 1:
        raise TaskConflict('Intake recovery requires its existing original workflow')
    record = records[0]
    if (record['scope'] != scope or record['native_request'] != request.model_dump(mode='json')
            or record['state'] not in {'preparing', 'formed'} or 'identity' not in record):
        raise TaskConflict('Intake recovery changes its original pending request or registration')
    objects, observed = app._sources(plan, request)
    if task_digest(objects) != record['source_sha256'] or observed != record['observed']:
        raise TaskConflict('Intake recovery changes its original currently authorized sources')
    identity = TaskIdentity(**record['identity'])
    app._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True))
    prepared = app.assembler.build(plan.context, **deepcopy(plan.action_input))
    snapshot = app.worker.snapshots.get(identity)
    if (identity.organization_id != plan.organization_id or identity.request_id != key + ':GOV-A02'
            or identity.purpose != 'action'
            or app.worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity
            or snapshot['context'] != plan.context.model_dump(mode='json')
            or snapshot['action_input'] != plan.action_input):
        raise TaskConflict('Intake recovery changes its original input, context or execution versions')
    return plan, scope, record, identity, prepared


def validate_saved_intake_stage(app, row, saved, snapshot):
    with app.read_guard():
        identity = TaskIdentity(**row['identity'])
        bound = app._bound.get(identity.context_sha256)
        if bound is None:
            raise TaskConflict('Intake recovery lost its original current source binding')
        plan, request = bound
        current, _, record, original, _ = original_intake_work(app, request)
        if (current != plan or original != identity or row != app.worker.store.get(identity)
                or snapshot != app.worker.snapshots.get(identity)
                or saved != app.worker.get_record(identity) or saved['result'].get('kind') != 'completed'
                or record.get('result_sha256') not in {None, saved['result_sha256']}):
            raise TaskConflict('Intake recovery substitutes its original invocation or saved result')
        # Correction/referral/acknowledgement cannot turn into native willingness.
        app._summary(saved['result'])
        return True


def recover_saved_intake_proposal(app, request):
    with app.read_guard():
        plan, scope, record, identity, prepared = original_intake_work(app, request)
        saved = app.worker.get_record(identity)
        if saved is None or saved['result'].get('kind') != 'completed':
            raise TaskConflict('Interrupted intake has no saved completed result; no processor replay is allowed')
        if record.get('result_sha256') not in {None, saved['result_sha256']}:
            raise TaskConflict('Intake recovery conflicts with its original saved result')
        app._summary(saved['result'])
        task = app.worker.store.get(identity)
        if task['state'] == 'processing':
            app.worker._finalize(identity, saved, recovered=True)
        elif task['state'] != 'output_formed':
            raise TaskConflict('Intake has unresolved wait/failure state; explicit diagnosis required')
        saved = checked_result(app.worker, identity)
        response = app._proposal_response(plan, request, scope, identity, saved, prepared)
        digest = task_digest(response.model_dump(mode='json'))
        if record.get('proposal_response_sha256') not in {None, digest}:
            raise TaskConflict('Recovered intake differs from its original formed proposal')
        if record['state'] != 'formed' or record.get('proposal_response_sha256') is None:
            record.update(state='formed', result_sha256=saved['result_sha256'], proposal_response_sha256=digest)
            app._save(record['key'], record)
        return response
