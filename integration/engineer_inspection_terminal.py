"""Archive original fully invested planning waits without certifying inspection completion."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.engineer_inspection_conditions import check_engineer_inspection_investment


def reconcile_engineer_inspection_investment(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_engineer_inspection_investment)
