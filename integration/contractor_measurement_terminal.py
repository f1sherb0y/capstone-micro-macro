"""Archive measurement disposition without creating work, debt or paid cash."""
from integration.contractor_closeout_terminal import _reconcile_original_history
from src.coordination import contractor_measurement_conditions as measurement_conditions


def reconcile_contractor_measurement_history(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_original_history(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, checker=measurement_conditions.check_contractor_measurement_history)
