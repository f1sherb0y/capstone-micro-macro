"""Archive actual original A09 registration status without repeating revision work."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.engineer_change_design_conditions import check_engineer_change_design_submission


def reconcile_engineer_change_submission(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_engineer_change_design_submission)
