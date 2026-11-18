"""Produce an A06 check from its independently authorized original review task."""
from integration.engineer_parameter_calculations import _prepare_engineer_design_calculation


def prepare_engineer_review_check_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Run the fixed code method once without borrowing A05's author authority.

    Caller holds the actual source guard. A06 preparation retains original
    reviewer independence, target content, fact versions and unresolved issues.
    No assessment, technical approval or permitted use is produced here.
    """
    return _prepare_engineer_design_calculation(context=context, action_input=action_input, reading=reading,
        preparation=preparation, author_authority_ref=author_authority_ref,
        validate_current=validate_current, result_kind='review_check')
