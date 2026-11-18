"""Produce an A13 investigation estimate from its original sourced work basis."""
from integration.engineer_parameter_calculations import _prepare_engineer_design_calculation


def prepare_engineer_research_estimate_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Run the fixed estimate once under the caller's actual source guard.

    Current delegation, independence, cost/work limits and numeric sources are
    checked before execution. Retain existing check inputs; isolate the future
    estimate target. The computed cost/work and basis must match the original
    request exactly. Persist and publish separately before A13 consumes it.
    """
    return _prepare_engineer_design_calculation(context=context, action_input=action_input, reading=reading,
        preparation=preparation, author_authority_ref=author_authority_ref,
        validate_current=validate_current, result_kind='research_estimate')
