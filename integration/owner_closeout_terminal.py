"""Archive actual Owner closeout disposition without payment or duty discharge."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.owner_closeout_conditions import check_owner_closeout_history


def reconcile_owner_closeout_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_owner_closeout_history)
