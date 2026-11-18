"""Archive the observed author handoff without claiming revision or duty completion."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination.engineer_change_author_conditions import check_engineer_change_author_handoff


def reconcile_engineer_change_author_handoff(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=check_engineer_change_author_handoff)
