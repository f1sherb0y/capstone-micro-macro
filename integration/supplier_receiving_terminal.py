"""Archive actual replacement proposal disposition without creating transport or received stock."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.supplier_receiving_conditions import check_supplier_receiving_history


def reconcile_supplier_receiving_replacement(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_supplier_receiving_history)
