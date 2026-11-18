"""Produce private Architect training estimates using the fixed shared route."""
from integration.service_training_estimates import prepare_service_training_estimate


def prepare_architect_training_estimate(*, context, action_input, reading,
        estimate_ref, author_authority_ref, validate_current):
    """Prepare one estimate under the caller's actual source/authorization guard."""
    return prepare_service_training_estimate(context=context, action_input=action_input, reading=reading,
        estimate_ref=estimate_ref, author_authority_ref=author_authority_ref,
        validate_current=validate_current, action_id='ARCHITECT-A12')
