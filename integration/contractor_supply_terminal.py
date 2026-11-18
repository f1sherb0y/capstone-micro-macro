"""Archive original supply status without creating delivery, payment or actual work."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination import contractor_supply_conditions as supply_conditions


def reconcile_contractor_supply_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=supply_conditions.check_contractor_supply_history)
