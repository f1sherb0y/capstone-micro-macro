"""Archive actual A12 terminal outcomes without repeating commercial decisions."""
from integration.architect_learning_terminal import _reconcile_learning_wait
from src.coordination.commercial_execution_query import EXECUTION_CODE, check_commercial_execution
from src.coordination.tasks import TaskConflict


def reconcile_commercial_execution(*, identity, signal, reader, dispatcher, validate_relation):
    if validate_relation is not reader.bindings.validate_relation:
        raise TaskConflict('Commercial terminal reconciliation replaced its original native validator')
    role = {'CONTRACTOR-A12': 'Contractor', 'SUPPLIER-A12': 'Supplier'}.get(reader.ACTION_ID)
    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader,
        dispatcher=dispatcher, validate_relation=reader.validate_execution_relation,
        condition_code=EXECUTION_CODE, checker=check_commercial_execution,
        reader_options={'execution_terminal': True}, proof=lambda resolution: resolution['execution'],
        action_id=reader.ACTION_ID, role=role)
