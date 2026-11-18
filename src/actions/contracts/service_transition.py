"""Input-related guards for the common service transition payload shapes."""


def validate_service_transition(action_input, payload, *, document_input='usable_deliverable_refs'):
    if payload.scope != action_input.scope:
        raise ValueError('Service transition changes original input scope')
    from src.actions.contracts.architect_transition_objects import ArchitectRecallPlan, ArchitectTransitionPackage
    from src.actions.contracts.owner_study_objects import unique_refs

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    tasks = keys(action_input.task_refs)
    if payload.choice == 'pause':
        if (payload.basis_ref != action_input.transition_basis_ref or not payload.task_refs
                or not keys(payload.task_refs) <= tasks):
            raise ValueError('Pause must retain original basis and specific input tasks')
    elif payload.choice == 'recall':
        plan = ArchitectRecallPlan.model_validate(payload.plan.model_dump(mode='python'))
        if not plan.items or not keys([item.task_ref for item in plan.items]) <= tasks:
            raise ValueError('Recall must retain specific original input tasks')
        for item in plan.items:
            keys(item.dependency_refs)
            if (not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids)
                    or item.existing_allocation_ref is not None
                    and item.existing_allocation_ref.key() not in keys(action_input.allocation_refs)):
                raise ValueError('Recall substitutes original resources or allocation')
    else:
        package = ArchitectTransitionPackage.model_validate(payload.package.model_dump(mode='python'))
        released, retained = keys(package.release_allocation_refs), keys(package.retain_allocation_refs)
        if (package.engagement_ref != action_input.engagement_ref
                or package.basis_ref != action_input.transition_basis_ref
                or not package.recipient_ids or len(set(package.recipient_ids)) != len(package.recipient_ids)
                or released & retained or released | retained != keys(action_input.allocation_refs)
                or keys(package.deliverable_refs) != keys(getattr(action_input, document_input))
                or keys(package.remaining_obligation_refs) != keys(action_input.residual_obligation_refs)
                or not keys(package.remaining_task_refs) <= tasks):
            raise ValueError('Handover/exit must preserve original service, allocations, usable documents and obligations')
        keys(package.access_basis_refs)
