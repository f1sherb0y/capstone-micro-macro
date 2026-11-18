"""Archive actual same-business Engineer results without replaying qualification/learning."""
from integration.architect_learning_terminal import _reconcile_learning_wait
from src.coordination.engineer_learning_execution_query import EXECUTION_CODE, check_engineer_learning_execution
from src.coordination.engineer_learning_applied_feedback import APPLIED_CODE, check_engineer_applied_feedback
from src.coordination.engineer_qualification_conditions import QUALIFICATION_CODE, check_qualification_application


def reconcile_engineer_learning_execution(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=EXECUTION_CODE, checker=check_engineer_learning_execution,
        reader_options={'execution_terminal': True}, proof=lambda resolution: resolution['query']['execution'],
        action_id='ENGINEER-A12', role='Engineer')


def reconcile_engineer_applied_feedback(*, identity, signal, reader, dispatcher, validate_relation):
    def proof(resolution):
        query = resolution['query']
        return (set(query['event_keys']), {tuple(sorted(ref.items())) for ref in query['application_execution_refs']})

    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=APPLIED_CODE, checker=check_engineer_applied_feedback,
        reader_options={'feedback_terminal': True}, proof=proof, action_id='ENGINEER-A12', role='Engineer')


def reconcile_engineer_qualification_application(*, identity, signal, reader, dispatcher, validate_relation):
    def proof(resolution):
        query = resolution['query']
        return (query['original_event_ref'], query['original_event_sha256'], query['verification_ref'], query['execution_ref'])

    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=QUALIFICATION_CODE, checker=check_qualification_application,
        reader_options={'qualification_terminal': True}, proof=proof, action_id='ENGINEER-A12', role='Engineer')
