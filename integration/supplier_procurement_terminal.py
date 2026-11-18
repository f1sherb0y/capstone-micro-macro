"""Archive original acceptance disposition without fulfilling upstream supply or creating stock."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.supplier_procurement_conditions import check_supplier_procurement_history


def reconcile_supplier_procurement_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_supplier_procurement_history)
