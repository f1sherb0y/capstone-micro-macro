"""Archive authentic original handover/account disposition without settling cash or residual duties."""
from integration.architect_learning_terminal import _reconcile_learning_wait
from src.coordination import contractor_closeout_conditions as closeout_conditions
from src.coordination.tasks import TaskConflict


def reconcile_contractor_closeout_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=closeout_conditions.check_contractor_closeout_history)


def _reconcile_original_history(*, identity, signal, reader, dispatcher, validate_relation, checker):
    source = reader.snapshots.store.get(identity)
    if len(source['conditions']) != 1:
        raise TaskConflict('Closeout terminal archive requires its original single history wait')
    code = source['conditions'][0]['condition_code']
    if code not in reader.CONDITION_CODES:
        raise TaskConflict('Closeout terminal archive requires its original handover/account route')
    snapshot = reader.snapshots.get(identity)

    def authenticate(**kwargs):
        resolution = kwargs['resolution']
        if (resolution['original_action_input'] != snapshot['action_input']
                or resolution['original_context'] != snapshot['context']):
            raise TaskConflict('Closeout terminal authentication replaces original persisted invocation')
        try:
            return validate_relation(**kwargs)
        finally:
            reader._check()
            if reader.snapshots.get(identity) != snapshot:
                raise TaskConflict('Closeout native authentication rewrites original persisted invocation')

    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=authenticate, condition_code=code, checker=checker,
        reader_options={'history_terminal': True}, proof=lambda resolution: resolution['history'],
        action_id=reader.ACTION_ID, role=reader.ROLE)
