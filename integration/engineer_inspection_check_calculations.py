"""Produce an A08 code check on its original executed visible observation."""
from integration.engineer_parameter_calculations import _prepare_engineer_design_calculation


def prepare_engineer_inspection_check_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Execute the fixed code method once under the actual source guard.

    Original preparation checks the applicable design/content, observation,
    executor authorization, required site access and actual invested work.
    Preserve limited findings; retain the proof for separate save/publication.
    No observation, report assessment, zero-defect claim or approval is created.
    """
    return _prepare_engineer_design_calculation(context=context, action_input=action_input, reading=reading,
        preparation=preparation, author_authority_ref=author_authority_ref,
        validate_current=validate_current, result_kind='inspection_check')
