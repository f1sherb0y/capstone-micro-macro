"""Archive actual existing fee status without producing another fee or settling cash."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.engineer_billing_conditions import (
    check_engineer_billing_claim, check_engineer_billing_reminder, check_engineer_billing_internal_cost,
)


def reconcile_engineer_billing_claim(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_engineer_billing_claim)


def reconcile_engineer_billing_receipts(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_engineer_billing_reminder)


def reconcile_engineer_billing_internal_cost(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_engineer_billing_internal_cost)
