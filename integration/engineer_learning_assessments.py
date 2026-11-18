"""Produce Engineer private assessments using the fixed shared learning route."""
from integration.service_learning_assessments import prepare_service_learning_assessment


def prepare_engineer_learning_assessment(*, context, action_input, reading,
        assessment_ref, author_authority_ref, validate_current):
    """Prepare one assessment under the caller's actual source/authorization guard."""
    return prepare_service_learning_assessment(context=context, action_input=action_input, reading=reading,
        assessment_ref=assessment_ref, author_authority_ref=author_authority_ref,
        validate_current=validate_current, action_id='ENGINEER-A12')
