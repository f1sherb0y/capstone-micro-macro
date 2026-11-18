"""CONTRACTOR-A12 requests transitions or records sourced private lessons."""
from src.actions.roles.commercial_continuation import transition_commercial_business


def continue_contractor_business(context, action_input, reading):
    return transition_commercial_business(context, action_input, reading)
