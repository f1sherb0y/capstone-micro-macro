"""Return a saved complete supply decision to its still-open native call."""
from copy import deepcopy
from dataclasses import replace

from integration.bank_financing_private import checked_result
from integration.supplier_order_native_decline import decline_for_supply
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def saved_supply_preflight(app, request):
    """Validate the whole original chain before advancing any technical state."""
    plan, scope = app._current(request)
    if not app.settings.allow_saved_recovery:
        raise TaskConflict('Supply recovery requires explicit allow_saved_recovery')
    key = app.PREFIX + task_digest([app.assembly.client.simulation_id, plan.organization_id, scope, request.request_id])
    records = [r for r in app._records() if r['key'] == key]
    if len(records) != 1:
        raise TaskConflict('Supply recovery requires its existing original workflow')
    record = records[0]
    if (record['scope'] != scope or record['native_request'] != request.model_dump(mode='json')
            or record['state'] not in {'preparing', 'formed'}):
        raise TaskConflict('Supply recovery changes its original request or scope')
    stages = []
    if plan.quote:
        if plan.quote.product:
            if plan.quote.product.screening:
                stages.append(('screening', app.screening_assembler, app.screening_worker))
            stages.append(('product', app.product_assembler, app.product_worker))
        stages.append(('quote', app.quote_assembler, app.quote_worker))
    stages.append(('order', app.assembler, app.worker))
    registered = [stage for stage, _, _ in stages if (stage in record if stage != 'order'
        else record.get('identity', {}).get('action_id') == 'SUPPLIER-A04')]
    if not registered:
        raise TaskConflict('Supply has no registered original stage; no processor replay is allowed')
    terminal = record.get('terminal_stage', registered[-1])
    names = [stage for stage, _, _ in stages]
    if terminal not in names or registered != names[:names.index(terminal) + 1]:
        raise TaskConflict('Supply recovery changes the original registered stage sequence')
    for stage, assembler, worker in stages[:names.index(terminal) + 1]:
        step = app._step(plan, stage)
        technical = record if stage == 'order' else record[stage]
        identity = TaskIdentity(**technical['identity'])
        if (app._bound.get(identity.context_sha256) != (plan, request, stage)
                or identity.run_id != plan.context.run_id or identity.organization_id != plan.organization_id
                or identity.action_id != step.context.contract_ref.id or identity.role != 'Supplier'
                or identity.purpose != 'action' or identity.request_id != key + ':' + identity.action_id):
            raise TaskConflict('Supply recovery changes original in-process binding or task identity')
        saved = worker.get_record(identity)
        if saved is None or saved['result'].get('kind') != 'completed':
            raise TaskConflict('Supply has no saved completed result; no processor replay is allowed')
        task = worker.store.get(identity)
        if task['state'] not in {'processing', 'output_formed'} or stage != terminal and task['state'] != 'output_formed':
            raise TaskConflict('Supply predecessor or waiting stage requires explicit diagnosis')
        objects, observed = app._sources(plan, request, stage=stage)
        if (task_digest(objects) != technical['source_sha256'] or observed != technical['observed']
                or technical.get('result_sha256') not in {None, saved['result_sha256']}):
            raise TaskConflict('Supply recovery changes original currently authorized sources or result')
        # Rebuild only the read view. No original processor, professional method,
        # handoff execution or later unstarted business stage is run here.
        prepared = assembler.build(step.context, **deepcopy(step.action_input))
        for obj in objects:
            prepared.reading.resolve(Reference.model_validate(obj['ref']))
        prepared = replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))
        snapshot = worker.snapshots.get(identity)
        if (worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity
                or snapshot['context'] != step.context.model_dump(mode='json')
                or snapshot['action_input'] != prepared.action_input.model_dump(mode='json')
                or prepared.reading.evidence() != saved['source_reading']):
            raise TaskConflict('Supply recovery changes original invocation, versions or reading')
        if stage != terminal:
            checked_result(worker, identity)
            choices = {'screening': {'respond'}, 'product': {'propose_original', 'propose_substitute'}, 'quote': {'quote'}}
            if saved['result']['payload']['choice'] not in choices[stage]:
                raise TaskConflict('Supply recovery cannot continue an unresolved predecessor')
        prepared.reading.recheck()
    # Native full acceptance/rejection must already follow from a completed
    # terminal result. Saved partial/clarify responses never become declines.
    binding = None if terminal == 'order' else decline_for_supply(saved, invocation=snapshot, plan=plan, stage=terminal)
    response = app._proposal_response(request, plan, scope, identity, saved, objects, prepared.reading, stage=terminal)
    digest = task_digest(response.model_dump(mode='json'))
    if (record.get('proposal_response_sha256') not in {None, digest}
            or record.get('terminal_stage') not in {None, terminal}
            or record.get('decline_binding') not in (None, binding)):
        raise TaskConflict('Supply recovery conflicts with its original terminal proposal')
    if record['state'] == 'formed' and (record.get('identity') != identity.as_dict()
            or record.get('result_sha256') != saved['result_sha256']
            or record.get('source_sha256') != task_digest(objects) or record.get('observed') != observed
            or record.get('proposal_response_sha256') != digest or record.get('terminal_stage') != terminal
            or terminal != 'order' and record.get('decline_binding') != binding):
        raise TaskConflict('Supply recovery changes its already formed original decision')
    return plan, scope, record, terminal, worker, identity, saved, prepared, response


def validate_saved_supply_stage(app, row, saved, snapshot):
    with app.read_guard():
        identity = TaskIdentity(**row['identity'])
        bound = app._bound.get(identity.context_sha256)
        if bound is None:
            raise TaskConflict('Supply recovery lacks its original current binding')
        _, request, _ = bound
        _, _, _, _, worker, original, actual, _, _ = saved_supply_preflight(app, request)
        if original != identity or actual != saved or snapshot != worker.snapshots.get(identity):
            raise TaskConflict('Supply recovery substitutes its original invocation or result')
        return True


def recover_saved_supply_proposal(app, request):
    with app.read_guard():
        plan, scope, record, stage, worker, identity, saved, prepared, response = saved_supply_preflight(app, request)
        if worker.store.get(identity)['state'] == 'processing':
            worker._finalize(identity, saved, recovered=True)
        checked_result(worker, identity)
        if stage != 'order' and record[stage].get('result_sha256') is None:
            record[stage]['result_sha256'] = saved['result_sha256']
        if record['state'] != 'formed':
            actual = app._form(request, plan, scope, record, prepared, saved, stage=stage)
            if actual != response:
                raise TaskConflict('Supply recovery changes its preflight native decision')
        return response
