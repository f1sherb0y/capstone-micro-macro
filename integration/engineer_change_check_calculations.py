"""Produce an A09 recheck on its original issue and deliverable content version."""
from integration.engineer_parameter_calculations import _prepare_engineer_design_calculation


def prepare_engineer_change_check_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Execute the fixed code method once under the actual source guard.

    Original preparation checks obligation, affected scope, reassessment task,
    required reviewer independence, invested work and sourced versioned facts.
    Retain the original issue/content and findings for separate save/publication;
    no revision, obligation discharge, issue closure or use right is created.
    """
    return _prepare_engineer_design_calculation(context=context, action_input=action_input, reading=reading,
        preparation=preparation, author_authority_ref=author_authority_ref,
        validate_current=validate_current, result_kind='change_check')
