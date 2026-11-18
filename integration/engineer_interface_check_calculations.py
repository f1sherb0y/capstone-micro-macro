"""Produce original A05 finite interface-check results without physical approval."""
from integration.engineer_parameter_calculations import _prepare_engineer_design_calculation


def prepare_engineer_interface_check_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Execute the fixed declared code rule once under the caller's actual guard.

    Binds original task/spec/target/facts and independent source checks. Missing
    codes remain undetermined; unsupported physical checks remain out_of_scope.
    This returns evidence for separate persistence/publication, not a design,
    independent review, technical approval or permitted use.
    """
    return _prepare_engineer_design_calculation(context=context, action_input=action_input, reading=reading,
        preparation=preparation, author_authority_ref=author_authority_ref,
        validate_current=validate_current, result_kind='interface_check')
