"""ARCHITECT-A12 keeps its original private learning projections and behavior."""
from src.actions.roles.service_learning import update_service_experience


def update_architect_experience(context, action_input, reading):
    return update_service_experience(context, action_input, reading)


def prepare_architect_training_estimate_input(context, action_input, reading):
    """Prepare original sourced work without consuming its future estimate."""
    return update_service_experience(context, action_input, reading, prepare_training=True)


def prepare_architect_learning_assessment_input(context, action_input, reading):
    """Prepare original finite-rule input without consuming a future assessment."""
    result = update_service_experience(context, action_input, reading, prepare_assessment=True)
    if result['kind'] == 'prepared':
        return {**result, 'dependencies': {}}
    return result
