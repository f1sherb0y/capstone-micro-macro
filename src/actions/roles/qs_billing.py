"""QS-A10 fees remain separate from clients' construction payment certificates."""
from src.actions.contracts.qs_billing_objects import qs_billing_types
from src.actions.roles.service_billing import handle_service_fees


def handle_qs_fees(context, action_input, reading):
    return handle_service_fees(context, action_input, reading, role='QS',
        action_id='QS-A10', billing_types=qs_billing_types())
