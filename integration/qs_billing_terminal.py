"""Archive actual QS fee histories without issuing fees, recognizing cash or settling debts."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.qs_billing_conditions import (
    check_qs_billing_claim, check_qs_billing_receipts, check_qs_billing_internal_cost,
)


def reconcile_qs_billing_claim(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_qs_billing_claim)


def reconcile_qs_billing_receipts(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_qs_billing_receipts)


def reconcile_qs_billing_internal_cost(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_qs_billing_internal_cost)
