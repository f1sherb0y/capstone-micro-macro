"""Produce one finite parameter result for the original authorized A09 revision."""
from integration.engineer_parameter_calculations import _prepare_engineer_design_calculation


def prepare_engineer_change_parameter_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Execute the fixed parameter method once under the actual source guard.

    Preparation retains original issue, obligation, parent and change-basis
    versions, permitted parameter changes, affected dependencies, accepted
    professional terms and actual work. The independent gate rereads original
    sources before execution. Keep the complete input, registry and result proof
    with current A09 author identity; save and publish separately before ordinary
    revision consumption. A finite domain finding grants no revision registration,
    professional approval, use permission or discharge of an obligation.
    """
    return _prepare_engineer_design_calculation(context=context, action_input=action_input, reading=reading,
        preparation=preparation, author_authority_ref=author_authority_ref,
        validate_current=validate_current, result_kind='change_parameter')
