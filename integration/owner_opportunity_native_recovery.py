"""Reconcile saved Owner opportunity work inside its original native call."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def original_opportunity_work(app, request):
    policy, scope = app._current(request)
    if not app.settings.allow_saved_recovery:
        raise TaskConflict('Owner opportunity recovery requires explicit allow_saved_recovery')
    key = app.PREFIX + task_digest([app.assembly.client.simulation_id, scope, request.request_id])
    records = [r for r in app._records() if r['key'] == key]
    if (len(records) != 1 or records[0]['scope'] != scope
            or records[0]['native_request'] != request.model_dump(mode='json')
            or records[0]['state'] not in {'preparing', 'formed'}):
        raise TaskConflict('Owner recovery requires its exact existing current workflow')
    return policy, scope, records[0]


def _components(app, stage):
    return {
        'observation': (app.observation_assembler, app.observation_worker, 'OWN-A01'),
        'proposal': (app.proposal_assembler, app.proposal_worker, 'OWN-A16'),
        'investment': (app.assembler, app.worker, 'OWN-A03'),
        'study': (app.study_assembler, app.study_worker, 'OWN-A02'),
    }[stage]


def _saved(app, policy, record, stage):
    _, worker, action = _components(app, stage)
    technical = record.get(stage)
    if not technical:
        raise TaskConflict('Owner opportunity has no saved completed result for required ' + stage
                           + '; no processor replay is allowed')
    identity = TaskIdentity(**technical['identity'])
    if (identity.organization_id != policy.organization_id or identity.action_id != action
            or identity.run_id != app.assembly.client.run_id or identity.role != 'Owner'
            or identity.request_id != record['key'] + ':' + action or identity.purpose != 'action'):
        raise TaskConflict('Owner recovery substitutes its original stage identity')
    saved = worker.get_record(identity)
    if saved is None or saved['result']['kind'] != 'completed':
        raise TaskConflict('Owner opportunity has no saved completed result for required ' + stage
                           + '; no processor replay is allowed')
    if technical.get('result_sha256') not in {None, saved['result_sha256']}:
        raise TaskConflict('Owner recovery conflicts with its saved result digest')
    row = worker.store.get(identity)
    if row['state'] not in {'processing', 'output_formed'}:
        raise TaskConflict('Owner recovery retains unresolved wait/failure states for explicit diagnosis')
    return identity, saved


def _stages(app, policy, record):
    """Preflight the complete required chain before finalizing technical tasks."""
    stages = []
    for enabled, stage, terminal, advances in (
            (policy.with_observation, 'observation', 'ignore', {'follow'}),
            (policy.with_proposal, 'proposal', 'no_proposal', {'propose'}),
            (True, 'investment', None, {'invest', 'reject', 'authorize_preparation', 'study_more'})):
        if not enabled:
            continue
        _, saved = _saved(app, policy, record, stage)
        choice = saved['result']['payload']['choice']
        stages.append(stage)
        if choice == terminal:
            return stages, stage
        if choice not in advances:
            raise TaskConflict('Owner saved outcome requires explicit business review')
        if stage == 'investment' and choice == 'study_more':
            if policy.study_question_code is None:
                raise TaskConflict('Unresolved investment lacks an enabled original study followup')
            _, study = _saved(app, policy, record, 'study')
            if study['result']['payload']['choice'] not in {'internal_study', 'commission', 'stop'}:
                raise TaskConflict('Owner saved study outcome requires explicit business review')
            stages.append('study')
    return stages, 'investment'


def _current_stage(app, policy, request, scope, record, stage):
    assembler, worker, _ = _components(app, stage)
    identity, saved = _saved(app, policy, record, stage)
    source = app._sources(policy, request, scope, stage=stage)
    snapshot = worker.snapshots.get(identity)
    technical = record[stage]
    if (technical['source_sha256'] != task_digest(source['objects']) or technical['observed'] != source['observed']
            or snapshot['context'] != source['context'].model_dump(mode='json')
            or snapshot['action_input'] != source['action_input']):
        raise TaskConflict('Owner recovery changes original current sources, context or action input')
    bound = app._bound.get(identity.context_sha256)
    if bound is None or bound != (policy, request, stage):
        raise TaskConflict('Owner recovery lacks its original in-process source binding')
    prepared = assembler.build(source['context'], **deepcopy(source['action_input']))
    if (worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity
            or prepared.reading.evidence() != saved['source_reading']):
        raise TaskConflict('Owner recovery changes original execution versions or authorized reading')
    prepared.reading.recheck()
    return identity, saved, source


def validate_saved_opportunity_stage(app, row, saved, snapshot):
    with app.read_guard():
        identity = TaskIdentity(**row['identity'])
        bound = app._bound.get(identity.context_sha256)
        if bound is None:
            raise TaskConflict('Owner recovery lacks its original source binding')
        policy, request, stage = bound
        current, scope, record = original_opportunity_work(app, request)
        original, actual, _ = _current_stage(app, current, request, scope, record, stage)
        if (current != policy or original != identity or actual != saved
                or snapshot != app.snapshots.get(identity)):
            raise TaskConflict('Owner recovery substitutes its saved invocation or result')
        return True


def recover_saved_opportunity_proposal(app, request):
    with app.read_guard():
        policy, scope, record = original_opportunity_work(app, request)
        stages, terminal = _stages(app, policy, record)
        if record['state'] == 'formed' and record.get('terminal_stage') != terminal:
            raise TaskConflict('Owner recovery changes its original terminal stage')
        results = {}
        for stage in stages:
            identity, saved, source = _current_stage(app, policy, request, scope, record, stage)
            _, worker, _ = _components(app, stage)
            if worker.store.get(identity)['state'] == 'processing':
                worker._finalize(identity, saved, recovered=True)
            checked_result(worker, identity)
            record[stage]['result_sha256'] = saved['result_sha256']
            record = app._save(record['key'], record)
            results[stage] = (saved, source)
        saved, source = results[terminal]
        if record['state'] == 'formed' and (
                record['identity'] != saved['identity'] or record['result_sha256'] != saved['result_sha256']
                or record['context'] != source['context'].model_dump(mode='json')
                or record['action_input'] != source['action_input']
                or record['source_sha256'] != task_digest(source['objects'])
                or record['observed'] != source['observed']
                or record['source_grants'] != [g.model_dump(mode='json') for g in source['grants']]):
            raise TaskConflict('Owner recovery conflicts with its original formed proposal evidence')
        return app._form(record['key'], record, source, saved, request, stage=terminal)
