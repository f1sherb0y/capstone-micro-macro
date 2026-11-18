"""Archive actual service execution results under the original application guard."""
from integration.architect_learning_terminal import _reconcile_learning_wait
from src.coordination.architect_transition_execution_query import EXECUTION_CODE, check_transition_execution


def reconcile_architect_transition_execution(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=EXECUTION_CODE, checker=check_transition_execution,
        reader_options={'execution_terminal': True}, proof=lambda resolution: resolution['query']['execution'],
        action_id='ARCHITECT-A11', role='Architect')
