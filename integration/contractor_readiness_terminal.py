"""Archive original task disposition; release/working never implies work completion."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination import contractor_readiness_conditions as readiness_conditions


def reconcile_contractor_readiness_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=readiness_conditions.check_contractor_readiness_history)
