"""Archive original claim disposition without recognizing debt, offset or actual cash."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.supplier_payment_conditions import check_supplier_payment_claim_history


def reconcile_supplier_payment_claim(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_supplier_payment_claim_history)
