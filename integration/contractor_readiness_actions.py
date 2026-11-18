"""Assemble original Contractor A06 inputs without granting a task release."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.contractor_readiness_objects import (
    ContractorReadyActionView, ContractorReadyAllocationFactView,
    ContractorReadyAllocationView, ContractorReadyApplicabilityView,
    ContractorReadyDesignView, ContractorReadyEvidenceView, ContractorReadyInputView,
    ContractorReadyProfileView, ContractorReadyRequirementView, ContractorReadySiteView,
    ContractorReadyTaskView, ContractorReadyVerificationView, ContractorWorkMandateView,
    GovPermitView, contractor_readiness_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorReadiness(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A06'


class ContractorReadinessActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze exact task gates, independent evidence and actual allocation identities.

    The application holds the current source/authorization guard. Original
    processor checks necessary coverage, applicability, verification, permits,
    execution windows, predecessors and actual physical inputs. Missing permit
    or design lists stay explicit; assembly creates no release or actual work.
    """
    ACTION_ID = 'CONTRACTOR-A06'
    SOURCE_SCHEMAS = staticmethod(contractor_readiness_schemas)

    def build(self, context, *, task_ref, readiness_requirement_refs, permit_refs,
            design_release_refs, site_refs, input_allocation_refs, readiness_profile_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'task_ref': task_ref, 'readiness_requirement_refs': readiness_requirement_refs,
            'permit_refs': permit_refs, 'design_release_refs': design_release_refs,
            'site_refs': site_refs, 'input_allocation_refs': input_allocation_refs,
            'readiness_profile_ref': readiness_profile_ref}, prepared_type=PreparedContractorReadiness,
            validate_sources=validate_contractor_readiness_sources)


def validate_contractor_readiness_sources(action_input, *, context, organization_id, sources):
    """Check supplied source identities while retaining unknown and unmet gates."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Task readiness lacks its exact original concrete source')
        return source

    def authored(row):
        points = (row.authored_at, row.available_at, row.effective_window.start, row.effective_window.end)
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or row.authored_at.offset > row.available_at.offset
                or row.available_at.offset > context.business_time.offset
                or not row.effective_window.contains(row.authored_at)):
            raise TaskConflict('Task readiness source changes its original signing time or availability')

    def original_inputs(row, inputs):
        for source in inputs:
            if (source.available_at.clock_ref != row.authored_at.clock_ref
                    or source.available_at.offset > row.authored_at.offset):
                raise TaskConflict('Task readiness source predates its original task or requirement inputs')

    for refs in (action_input.readiness_requirement_refs, action_input.permit_refs,
            action_input.design_release_refs, action_input.site_refs, action_input.input_allocation_refs):
        unique_refs(refs)
    task = read(action_input.task_ref, ContractorReadyTaskView)
    profile = read(action_input.readiness_profile_ref, ContractorReadyProfileView)
    if (task.organization_id != organization_id or task.scope != context.scope
            or profile.organization_id != organization_id or profile.task_ref.key() != task.ref.key()
            or task.readiness_profile_ref.key() != profile.ref.key()):
        raise TaskConflict('Task readiness changes original contractor, task scope or profile')
    mandate = sources.get(task.mandate_ref.key())
    if mandate is not None and (not isinstance(mandate, ContractorWorkMandateView)
            or mandate.organization_id != organization_id or not scope_covers(mandate.scope, task.scope)):
        raise TaskConflict('Task readiness changes the original contract/preparation mandate or scope')
    action = sources.get(task.action_ref.key())
    if action is not None and (not isinstance(action, ContractorReadyActionView)
            or action.mandate_ref.key() != task.mandate_ref.key() or action.purpose != task.purpose):
        raise TaskConflict('Task readiness changes the original action definition or work purpose')
    for ref in action_input.readiness_requirement_refs:
        requirement = read(ref, ContractorReadyRequirementView)
        if requirement.task_ref.key() != task.ref.key() or not scope_covers(task.scope, requirement.scope):
            raise TaskConflict('Task readiness requirement changes its original task or scope')
        for dependency_ref, schema in ((requirement.applicability_ref, ContractorReadyApplicabilityView),
                (requirement.verification_ref, ContractorReadyVerificationView)):
            if dependency_ref is None:
                continue
            dependency = sources.get(dependency_ref.key())
            if dependency is not None and (not isinstance(dependency, schema)
                    or dependency.ref != dependency_ref
                    or dependency.task_ref.key() != task.ref.key()
                    or dependency.requirement_ref.key() != requirement.ref.key()
                    or not scope_covers(dependency.scope, requirement.scope)):
                raise TaskConflict('Task readiness substitutes another requirement applicability or verification')
            if dependency is not None:
                authored(dependency)
                original_inputs(dependency, (task, requirement))
                if isinstance(dependency, ContractorReadyVerificationView):
                    applicability = sources.get(requirement.applicability_ref.key())
                    if applicability is not None:
                        original_inputs(dependency, (applicability,))
        for source_ref in requirement.source_refs:
            evidence = sources.get(source_ref.key())
            if source_ref.kind == 'ReadinessEvidence' and evidence is not None and (
                    not isinstance(evidence, ContractorReadyEvidenceView)
                    or evidence.task_ref.key() != task.ref.key()
                    or evidence.requirement_ref.key() != requirement.ref.key()
                    or evidence.category != requirement.category):
                raise TaskConflict('Task readiness evidence changes the original task, requirement or category')
            if source_ref.kind == 'ReadinessEvidence' and evidence is not None:
                authored(evidence)
    for ref in action_input.permit_refs:
        read(ref, GovPermitView)
        # Original permit applicability and status remain business checks.
    for ref in action_input.design_release_refs:
        design = read(ref, ContractorReadyDesignView)
        authored(design)
        if design.mandate_ref.key() != task.mandate_ref.key():
            raise TaskConflict('Task readiness design release changes its original mandate')
    for ref in action_input.site_refs:
        site = read(ref, ContractorReadySiteView)
        authored(site)
        if site.task_ref.key() != task.ref.key() or site.organization_id != organization_id:
            raise TaskConflict('Task readiness site source changes the original task or organization')
    for ref in action_input.input_allocation_refs:
        allocation = read(ref, ContractorReadyAllocationView)
        if allocation.task_ref.key() != task.ref.key() or allocation.organization_id != organization_id:
            raise TaskConflict('Task readiness allocation changes the original task or input owner')
        resource = sources.get(allocation.resource_ref.key())
        if resource is not None and (not isinstance(resource, ContractorReadyInputView)
                or resource.organization_id != organization_id):
            raise TaskConflict('Task readiness changes the original physical input owner')
        fact = sources.get(allocation.commitment_ref.key())
        if fact is not None and (not isinstance(fact, ContractorReadyAllocationFactView)
                or fact.task_ref.key() != task.ref.key() or fact.allocation_ref.key() != allocation.ref.key()
                or fact.resource_ref.key() != allocation.resource_ref.key()
                or fact.quantity != allocation.quantity or fact.execution_window != allocation.execution_window):
            raise TaskConflict('Task readiness changes original core allocation identity, quantity or window')
        if resource is not None:
            for fact_ref in resource.allocations:
                other = sources.get(fact_ref.key())
                if other is not None and (not isinstance(other, ContractorReadyAllocationFactView)
                        or other.resource_ref.key() != resource.ref.key()):
                    raise TaskConflict('Task readiness physical input ledger changes the original resource')
    for ref in profile.replacement_task_refs:
        replacement = sources.get(ref.key())
        if replacement is not None and (not isinstance(replacement, ContractorReadyTaskView)
                or replacement.organization_id != organization_id
                or replacement.mandate_ref.key() != task.mandate_ref.key()):
            raise TaskConflict('Task readiness replacement changes original contractor or work mandate')
