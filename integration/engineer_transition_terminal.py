"""Archive actual same-business engineering transitions without resubmitting them."""
from integration.architect_learning_terminal import _reconcile_learning_wait
from src.coordination.engineer_transition_execution_query import EXECUTION_CODE, check_engineer_transition_execution


def reconcile_engineer_transition_execution(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=EXECUTION_CODE, checker=check_engineer_transition_execution,
        reader_options={'execution_terminal': True}, proof=lambda resolution: resolution['query']['execution'],
        action_id='ENGINEER-A11', role='Engineer')
