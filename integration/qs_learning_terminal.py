"""Archive authenticated same-business QS learning execution without applying learning again."""
from integration.architect_learning_terminal import _reconcile_learning_wait
from src.coordination.qs_learning_execution_query import EXECUTION_CODE, check_qs_learning_execution
from src.coordination.qs_learning_applied_feedback import APPLIED_CODE, check_qs_applied_feedback
from src.coordination.tasks import TaskConflict


def reconcile_qs_learning_execution(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_qs_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=EXECUTION_CODE, checker=check_qs_learning_execution,
        reader_options={'execution_terminal': True}, proof=lambda resolution: resolution['query']['execution'])


def reconcile_qs_applied_feedback(*, identity, signal, reader, dispatcher, validate_relation):
    def application_proof(resolution):
        query = resolution['query']
        return (set(query['event_keys']), {tuple(sorted(ref.items())) for ref in query['application_execution_refs']})

    return _reconcile_qs_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=APPLIED_CODE, checker=check_qs_applied_feedback,
        reader_options={'feedback_terminal': True}, proof=application_proof)


def _reconcile_qs_learning_wait(*, identity, signal, reader, dispatcher, validate_relation,
        condition_code, checker, reader_options, proof):
    snapshot = reader.snapshots.get(identity)

    def authenticate(**kwargs):
        resolution = kwargs['resolution']
        if (resolution['original_action_input'] != snapshot['action_input']
                or resolution['original_context'] != snapshot['context']):
            raise TaskConflict('QS learning terminal authentication replaces the original persisted invocation')
        try:
            return validate_relation(**kwargs)
        finally:
            reader._check()
            if reader.snapshots.get(identity) != snapshot:
                raise TaskConflict('QS learning terminal authentication rewrites the original persisted invocation')

    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=authenticate, condition_code=condition_code, checker=checker,
        reader_options=reader_options, proof=proof,
        action_id='QS-A12', role='QS')
