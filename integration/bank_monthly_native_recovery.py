"""Reconcile one original Bank monthly call from its durable BANK-A01 result."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def original_bank_monthly_work(app, request):
    plan, scope = app._current(request)
    if not app.settings.allow_saved_recovery:
        raise TaskConflict('Bank monthly recovery requires explicit allow_saved_recovery')
    key = app.PREFIX + task_digest([app.assembly.client.simulation_id, scope, request.request_id])
    records = [r for r in app._records() if r['key'] == key]
    if len(records) != 1:
        raise TaskConflict('Bank monthly recovery requires its existing original workflow')
    record = records[0]
    if (record['scope'] != scope or record['native_request'] != request.model_dump(mode='json')
            or record['state'] not in {'preparing', 'formed'} or 'identity' not in record
            or record['context'] != plan.context.model_dump(mode='json') or record['action_input'] != plan.action_input
            or record['native_evidence_ref'] != plan.native_evidence_ref.model_dump(mode='json')):
        raise TaskConflict('Bank monthly recovery changes its original request, input or registration')
    objects, observed = app._sources(plan, request)
    if task_digest(objects) != record['source_sha256'] or observed != record['observed']:
        raise TaskConflict('Bank monthly recovery changes its original currently authorized sources')
    identity = TaskIdentity(**record['identity'])
    if (identity.run_id != app.assembly.client.run_id or identity.organization_id != plan.organization_id
            or identity.action_id != 'BANK-A01' or identity.role != 'Bank' or identity.purpose != 'action'
            or identity.request_id != key + ':BANK-A01'):
        raise TaskConflict('Bank monthly recovery changes its original task identity')
    return plan, scope, record, identity


def _current_saved_bank_monthly(app, request):
    plan, scope, record, identity = original_bank_monthly_work(app, request)
    if app._bound.get(identity.context_sha256) != (plan, request):
        raise TaskConflict('Bank monthly recovery lacks its original in-process source binding')
    saved = app.worker.get_record(identity)
    if saved is None or saved['result'].get('kind') != 'completed':
        raise TaskConflict('Bank monthly has no saved completed result; no processor replay is allowed')
    snapshot = app.worker.snapshots.get(identity)
    prepared = app.assembler.build(plan.context, **deepcopy(plan.action_input))
    if (app.worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity
            or snapshot['context'] != record['context'] or snapshot['action_input'] != record['action_input']
            or prepared.reading.evidence() != saved['source_reading']
            or record.get('result_sha256') not in {None, saved['result_sha256']}):
        raise TaskConflict('Bank monthly recovery changes original invocation, execution versions or reading')
    task = app.worker.store.get(identity)
    if task['state'] not in {'processing', 'output_formed'}:
        raise TaskConflict('Bank monthly has unresolved wait/failure state; explicit diagnosis required')
    # Validate the native mapping, metrics and original proposal hash before
    # finalizing even the technical task. Unresolved strategy stays unresolved.
    response = app._proposal_response(request, plan, scope, identity, saved, prepared.reading)
    digest = task_digest(response.model_dump(mode='json'))
    if (record.get('proposal_response_sha256') not in {None, digest}
            or record['state'] == 'formed' and (record.get('result_sha256') != saved['result_sha256']
                or record.get('proposal_response_sha256') != digest)):
        raise TaskConflict('Bank monthly recovery conflicts with its original proposal')
    prepared.reading.recheck()
    return plan, scope, record, identity, saved, response


def validate_saved_bank_monthly_stage(app, row, saved, snapshot):
    with app.parent.read_guard():
        identity = TaskIdentity(**row['identity'])
        bound = app._bound.get(identity.context_sha256)
        if bound is None:
            raise TaskConflict('Bank monthly recovery lacks its original source binding')
        _, request = bound
        _, _, _, original, actual, _ = _current_saved_bank_monthly(app, request)
        if original != identity or actual != saved or snapshot != app.worker.snapshots.get(identity):
            raise TaskConflict('Bank monthly recovery substitutes its original invocation or result')
        return True


def recover_saved_bank_monthly_proposal(app, request):
    with app.parent.read_guard():
        _, _, record, identity, saved, response = _current_saved_bank_monthly(app, request)
        if app.worker.store.get(identity)['state'] == 'processing':
            app.worker._finalize(identity, saved, recovered=True)
        checked_result(app.worker, identity)
        digest = task_digest(response.model_dump(mode='json'))
        if record['state'] != 'formed' or record.get('proposal_response_sha256') is None:
            record.update(state='formed', result_sha256=saved['result_sha256'], proposal_response_sha256=digest)
            app.parent._save(record['key'], record)
        return response
