"""Archive actual prior registration status without producing or approving another design."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.architect_design_conditions import check_architect_design_submission


def reconcile_architect_design_submission(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_architect_design_submission)
