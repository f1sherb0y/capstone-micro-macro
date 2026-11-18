"""Freeze original Architect A11 service history, resource and document-right sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_transition_objects import (
    ArchitectTransitionEngagementView, ArchitectTransitionBasisView, ArchitectTransitionTaskView,
    ArchitectTransitionAllocationView, ArchitectAllocationReleaseView, ArchitectTransitionDeliverableView,
    ArchitectTransitionAccessView, ArchitectExistingUseRightView, ArchitectHandoverAcceptanceView,
    ArchitectRecallWorkProfileView, ArchitectTransitionExecutionView, architect_transition_schemas,
)
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedArchitectTransition(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A11'


class ArchitectTransitionActionAssembler(ArchitectOpportunityActionAssembler):
    """Preserve cross-service history, authorship, licensed use and remaining debt.

    Original processor checks selected tasks, recall capacity, atomic allocation
    replacement, document access and independent successor acceptance. Assembly
    releases no resources, reserves no capacity and clears no service obligation.
    """
    ACTION_ID = 'ARCHITECT-A11'
    SOURCE_SCHEMAS = staticmethod(architect_transition_schemas)

    def build(self, context, *, scope, engagement_ref, transition_basis_ref, task_refs,
            allocation_refs, usable_deliverable_refs, residual_obligation_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'engagement_ref': engagement_ref, 'transition_basis_ref': transition_basis_ref,
            'task_refs': task_refs, 'allocation_refs': allocation_refs,
            'usable_deliverable_refs': usable_deliverable_refs, 'residual_obligation_refs': residual_obligation_refs},
            prepared_type=PreparedArchitectTransition, validate_sources=validate_architect_transition_sources)


def validate_architect_transition_sources(action_input, *, context, organization_id, sources):
    """Check original service/actor/source identities without evaluating a transition."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect transition lacks its exact original concrete source')
        return row

    def same_engagement(row):
        if row.engagement_ref.key() != engagement.ref.key():
            raise TaskConflict('Architect transition source changes its original engagement')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect transition changes its original invocation scope')
    engagement = read(action_input.engagement_ref, ArchitectTransitionEngagementView)
    basis = same_engagement(read(action_input.transition_basis_ref, ArchitectTransitionBasisView))
    if (engagement.organization_id != organization_id or not scope_covers(engagement.scope, context.scope)
            or basis.scope != context.scope or basis.actor_id != context.actor_id
            or basis.function_ref.key() != context.function_ref.key()):
        raise TaskConflict('Architect transition changes its original organization, actor, function or scope')
    for field in ('task_refs', 'allocation_refs', 'usable_deliverable_refs', 'residual_obligation_refs'):
        unique_refs(getattr(action_input, field))
        unique_refs(getattr(engagement, field))
    unique_refs(engagement.execution_refs)
    unique_refs(basis.selected_task_refs)
    unique_refs(basis.recipient_acceptance_refs)
    for ref in action_input.task_refs:
        task = same_engagement(read(ref, ArchitectTransitionTaskView))
        if task.organization_id != organization_id or task.author_organization_id != organization_id:
            raise TaskConflict('Architect transition task changes its original firm or author organization')
        unique_refs(task.dependency_refs)
        if task.allocation_ref is not None and task.allocation_ref.key() in sources:
            allocation = same_engagement(read(task.allocation_ref, ArchitectTransitionAllocationView))
            if allocation.task_ref.key() != task.ref.key():
                raise TaskConflict('Architect transition task allocation changes its original task')
    for ref in action_input.allocation_refs:
        allocation = same_engagement(read(ref, ArchitectTransitionAllocationView))
        if allocation.organization_id != organization_id:
            raise TaskConflict('Architect transition allocation changes its original firm')
        unique_refs(allocation.commitment_refs)
        if allocation.release_permission_ref.key() in sources:
            permission = read(allocation.release_permission_ref, ArchitectAllocationReleaseView)
            if permission.allocation_ref.key() != allocation.ref.key():
                raise TaskConflict('Architect allocation release permission changes its original allocation')
    for ref in action_input.residual_obligation_refs:
        read(ref, OwnerPaymentObligationView)
    for ref in action_input.usable_deliverable_refs:
        document = same_engagement(read(ref, ArchitectTransitionDeliverableView))
        if document.historical_author_id != document.author_actor_id:
            raise TaskConflict('Architect transition document changes its historical author')
        unique_refs(document.existing_use_right_refs)
        for right_ref in document.existing_use_right_refs:
            if right_ref.key() in sources:
                right = read(right_ref, ArchitectExistingUseRightView)
                if right.deliverable_ref.key() != document.ref.key():
                    raise TaskConflict('Architect transition use right changes its original document')
    for ref in engagement.execution_refs:
        if ref.key() in sources:
            execution = read(ref, ArchitectTransitionExecutionView)
            if (execution.organization_id != organization_id or execution.run_id != context.run_id
                    or execution.engagement_ref.id != engagement.ref.id):
                raise TaskConflict('Architect transition history changes its original run, firm or service')
            if execution.business_key == basis.business_key and execution.basis_ref.key() in sources:
                original = read(execution.basis_ref, ArchitectTransitionBasisView)
                if (original.engagement_ref != execution.engagement_ref or original.scope != execution.scope
                        or original.business_key != execution.business_key):
                    raise TaskConflict('Architect transition execution substitutes its original basis or scope')
    if basis.recall_plan is not None:
        plan = basis.recall_plan
        unique_refs([item.task_ref for item in plan.items])
        for item in plan.items:
            unique_refs(item.dependency_refs)
        if plan.work_profile_ref.key() in sources:
            work = same_engagement(read(plan.work_profile_ref, ArchitectRecallWorkProfileView))
            if work.organization_id != organization_id or work.author_organization_id != organization_id:
                raise TaskConflict('Architect recall work profile changes its original firm or author')
            unique_refs([resource.ref for resource in work.resources])
            unique_refs([commitment.commitment_ref for commitment in work.commitments])
    if basis.package is not None:
        package = basis.package
        if package.engagement_ref.key() != engagement.ref.key() or package.basis_ref.key() != basis.ref.key():
            raise TaskConflict('Architect handover package changes its original service or basis')
        for field in ('deliverable_refs', 'access_basis_refs', 'release_allocation_refs',
                'retain_allocation_refs', 'remaining_task_refs', 'remaining_obligation_refs'):
            unique_refs(getattr(package, field))
        for ref in package.access_basis_refs:
            if ref.key() in sources:
                access = read(ref, ArchitectTransitionAccessView)
                if access.deliverable_ref.key() in sources:
                    document = read(access.deliverable_ref, ArchitectTransitionDeliverableView)
                    same_engagement(document)
                    if access.author_organization_id != document.rights_controller_organization_id:
                        raise TaskConflict('Architect handover access changes its original rights controller')
    for ref in basis.recipient_acceptance_refs:
        if ref.key() in sources:
            acceptance = same_engagement(read(ref, ArchitectHandoverAcceptanceView))
            if acceptance.recipient_id != acceptance.author_actor_id:
                raise TaskConflict('Architect handover acceptance changes its independent recipient author')
