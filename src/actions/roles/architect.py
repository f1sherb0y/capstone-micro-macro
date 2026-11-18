"""Architect A02 retains its exact role contract over shared intake checks."""
from src.actions.roles.service_intake import assess_professional_service


def assess_service_request(context, action_input, reading):
    return assess_professional_service(context, action_input, reading)
