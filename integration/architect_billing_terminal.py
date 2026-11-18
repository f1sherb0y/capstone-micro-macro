"""Archive original fee claim status without issuing a claim, recognizing cash or settling debt."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.architect_billing_conditions import (
    check_architect_billing_claim, check_architect_billing_reminder, check_architect_billing_internal_cost,
)


def reconcile_architect_billing_claim(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_architect_billing_claim)


def reconcile_architect_billing_received_reminder(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_architect_billing_reminder)


def reconcile_architect_billing_internal_cost(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_architect_billing_internal_cost)
