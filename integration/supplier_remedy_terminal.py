"""Archive actual original Supplier remedy/refund history without issuing a new refund or disposition."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.supplier_remedy_conditions import check_supplier_remedy_history


def reconcile_supplier_remedy_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_supplier_remedy_history)
