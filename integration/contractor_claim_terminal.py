"""Archive original claim disposition without granting amount, time or entitlement."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination import contractor_claim_conditions as claim_conditions


def reconcile_contractor_claim_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=claim_conditions.check_contractor_claim_history)
