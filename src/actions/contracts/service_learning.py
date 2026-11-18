"""Input-related guards for private judgments and training proposals."""


def validate_service_learning(action_input, payload, *, capability_from_input=True):
    if payload.scope != action_input.scope:
        raise ValueError('Service learning changes original input scope')
    from src.actions.contracts.architect_learning_objects import ArchitectLearningJudgment, ArchitectTrainingRequest
    from src.actions.contracts.owner_study_objects import unique_refs
    if payload.choice == 'record_feedback':
        unique_refs(payload.feedback_refs)
        if {r.key() for r in payload.feedback_refs} != {r.key() for r in action_input.feedback_refs}:
            raise ValueError('Feedback record must retain original received input identities')
    elif action_input.learning_profile_ref is None:
        raise ValueError('Judgment update or training needs explicitly selected learning profile')
    elif payload.choice == 'update_judgment':
        revision = ArchitectLearningJudgment.model_validate(payload.revision.model_dump(mode='python'))
        unique_refs(revision.evidence_refs)
        unique_refs([change.dimension_ref for change in revision.changes])
        if (revision.prior_strategy_ref != action_input.strategy_ref
                or revision.learning_profile_ref != action_input.learning_profile_ref
                or not revision.evidence_refs or not revision.changes):
            raise ValueError('Judgment update must preserve original strategy/profile and specific evidenced dimensions')
    else:
        request = ArchitectTrainingRequest.model_validate(payload.request.model_dump(mode='python'))
        for refs in (request.input_refs, request.output_requirement_refs, request.authority_basis_refs, request.dependency_refs):
            unique_refs(refs)
        original = {r.key() for r in [action_input.strategy_ref, action_input.learning_profile_ref,
                    *action_input.feedback_refs, *([action_input.capability_ref] if capability_from_input else [])]}
        if (payload.learning_profile_ref != action_input.learning_profile_ref or request.scope != action_input.scope
                or not original <= {r.key() for r in request.input_refs}
                or not request.output_requirement_refs or not request.authority_basis_refs
                or request.work_profile_ref is None):
            raise ValueError('Training must retain original capability, feedback, selected profile, independent authority and verifiable outputs')
