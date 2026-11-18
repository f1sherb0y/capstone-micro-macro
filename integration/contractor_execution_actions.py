"""Assemble original Contractor A07 intentions, reports and execution history."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts import contractor_execution_objects as execution_objects
from src.actions.contracts.contractor_execution_objects import (
    ContractorExecutionConditionView, ContractorExecutionGateView,
    ContractorExecutionObservationView, ContractorExecutionProfileView,
    ContractorExecutionRequestView, ContractorExecutionRequirementView, ContractorExecutionTaskView,
    ContractorInventoryAllocationView, ContractorInventoryView, ContractorTaskReleaseView,
    ContractorReadyAllocationView, ContractorReadyAllocationFactView,
    ContractorWorkExecutionView, ContractorWorkRecordView, contractor_execution_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorExecution(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A07'


class ContractorExecutionActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze the explicitly selected ready/report/existing input branch.

    The actual application holds its current source/authorization guard. Original
    processor checks current release, engineering rules, actual inputs, reports
    and execution reconciliation. Historical reconciliation requires no current
    task release. Assembly never sends inputs, replays a command or creates work,
    inventory consumption, actual progress, cost or quality consequences.
    """
    ACTION_ID = 'CONTRACTOR-A07'
    SOURCE_SCHEMAS = staticmethod(contractor_execution_schemas)

    def build(self, context, *, scope_ref, execution_context):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'execution_context': execution_context},
            prepared_type=PreparedContractorExecution, validate_sources=validate_contractor_execution_sources)

    def build_from_supplier_receiving(self, context, *, supplier_decision, material_basis_refs,
            validate_reception, **execution_inputs):
        """Retain original material receipts and independent use release."""
        from integration.supplier_contractor_material_handoff import validate_received_contractor_materials

        prepared = self.build(context, **execution_inputs)
        validate_received_contractor_materials(supplier_decision, prepared=prepared,
            material_basis_refs=material_basis_refs, validate_reception=validate_reception)
        return prepared


def validate_contractor_execution_sources(action_input, *, context, organization_id, sources):
    """Check original task and command relationships, retaining unknown statuses."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Work execution lacks its exact original concrete source')
        return source

    def authored(row):
        points = (row.authored_at, row.available_at, row.effective_window.start, row.effective_window.end)
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or row.authored_at.offset > row.available_at.offset
                or row.available_at.offset > context.business_time.offset
                or not row.effective_window.contains(row.authored_at)):
            raise TaskConflict('Work observation changes its original signing time or availability')

    if action_input.scope_ref != context.scope:
        raise TaskConflict('Work execution changes its original authorized physical scope')
    operation = action_input.execution_context

    def history(refs, task=None):
        unique_refs(refs)
        for ref in refs:
            execution = read(ref, ContractorWorkExecutionView)
            if (execution.organization_id != organization_id or execution.run_id != context.run_id
                    or not scope_covers(action_input.scope_ref, execution.scope)
                    or task is not None and execution.task_ref.key() != task.ref.key()):
                raise TaskConflict('Work execution history changes original run, contractor or task')
            request = sources.get(execution.request_ref.key())
            if request is not None and (not isinstance(request, ContractorExecutionRequestView)
                    or request.ref != execution.request_ref
                    or request.task_ref.key() != execution.task_ref.key()
                    or request.operation_id != execution.operation_id or request.business_key != execution.business_key
                    or request.scope_ref != execution.scope):
                raise TaskConflict('Work execution history changes its original submitted request identity')
            if execution.recorded_at is not None:
                if (execution.recorded_at.clock_ref != context.business_time.clock_ref
                        or execution.available_at.clock_ref != context.business_time.clock_ref
                        or execution.recorded_at.offset > execution.available_at.offset):
                    raise TaskConflict('Work execution changes its original core recording chronology')
                if request is not None and (request.available_at.clock_ref != execution.recorded_at.clock_ref
                        or request.available_at.offset > execution.recorded_at.offset):
                    raise TaskConflict('Work execution predates its original submitted request source')
            for record_ref in execution.work_record_refs:
                record = sources.get(record_ref.key())
                if record is not None and (not isinstance(record, ContractorWorkRecordView)
                        or record.ref != record_ref
                        or record.core_event_id != execution.core_event_id
                        or not scope_covers(execution.scope, record.scope)):
                    raise TaskConflict('Work execution history changes the original core event or work record')
                if record is not None:
                    command = execution if record.execution_ref == execution.ref else read(record.execution_ref, ContractorWorkExecutionView)
                    try:
                        execution_objects.validate_contractor_work_record_execution(execution, record, command)
                    except ValueError as error:
                        raise TaskConflict('Work execution history changes the original submitted command source') from error

    if operation.kind == 'existing':
        history(operation.execution_refs)
        return
    task = read(operation.task_ref, ContractorExecutionTaskView)
    if task.organization_id != organization_id or task.scope != action_input.scope_ref:
        raise TaskConflict('Work execution changes the original contractor task or physical scope')
    profile = sources.get(task.execution_profile_ref.key())
    if profile is not None and (not isinstance(profile, ContractorExecutionProfileView)
            or profile.organization_id != organization_id or profile.task_ref.key() != task.ref.key()):
        raise TaskConflict('Work execution changes the original contractor task profile')
    if operation.kind == 'report':
        history(operation.execution_refs, task)
        unique_refs(operation.observation_refs)
        for ref in operation.observation_refs:
            observation = read(ref, ContractorExecutionObservationView)
            authored(observation)
            if (observation.task_ref.key() != task.ref.key() or observation.author_organization_id != organization_id
                    or observation.author_action_id != 'CONTRACTOR-A07'
                    or not scope_covers(action_input.scope_ref, observation.scope)
                    or task.available_at.clock_ref != observation.authored_at.clock_ref
                    or task.available_at.offset > observation.authored_at.offset):
                raise TaskConflict('Work progress observation changes original task or author organization/function')
            for requirement_ref in observation.requirement_refs:
                requirement = sources.get(requirement_ref.key())
                if requirement is not None and (not isinstance(requirement, ContractorExecutionRequirementView)
                        or requirement.ref != requirement_ref or requirement.task_ref != task.ref
                        or requirement.available_at.clock_ref != observation.authored_at.clock_ref
                        or requirement.available_at.offset > observation.authored_at.offset):
                    raise TaskConflict('Work progress observation changes an originally available task requirement')
        return
    history(operation.prior_execution_refs, task)
    for refs in (operation.available_input_refs, operation.inventory_refs, operation.condition_refs):
        unique_refs(refs)
    release = read(operation.release_ref, ContractorTaskReleaseView)
    if (release.organization_id != organization_id or release.task_ref.key() != task.ref.key()
            or release.action_ref.key() != task.action_ref.key()
            or release.work_method_ref.key() != operation.work_method_ref.key()):
        raise TaskConflict('Work execution changes the original core release task, action or method')
    gate = sources.get(release.current_gate_ref.key())
    if gate is not None and (not isinstance(gate, ContractorExecutionGateView)
            or gate.task_ref.key() != task.ref.key() or gate.release_ref.key() != release.ref.key()):
        raise TaskConflict('Work execution changes the original core gate snapshot task or release')
    for ref in operation.available_input_refs:
        allocation = read(ref, ContractorReadyAllocationView)
        if allocation.organization_id != organization_id or allocation.task_ref.key() != task.ref.key():
            raise TaskConflict('Work execution available allocation changes original task or owner')
        fact = sources.get(allocation.commitment_ref.key())
        if fact is not None and (not isinstance(fact, ContractorReadyAllocationFactView)
                or fact.allocation_ref.key() != allocation.ref.key() or fact.task_ref.key() != task.ref.key()
                or fact.resource_ref.key() != allocation.resource_ref.key()
                or fact.quantity != allocation.quantity or fact.execution_window != allocation.execution_window):
            raise TaskConflict('Work execution changes the original core input allocation identity')
    for ref in operation.condition_refs:
        condition = read(ref, ContractorExecutionConditionView)
        authored(condition)
        if condition.task_ref.key() != task.ref.key():
            raise TaskConflict('Work execution site condition changes the original task')
    for ref in operation.inventory_refs:
        inventory = read(ref, ContractorInventoryView)
        if inventory.organization_id != organization_id:
            raise TaskConflict('Work execution inventory changes the original owner')
        for allocation_ref in inventory.allocation_refs:
            allocation = sources.get(allocation_ref.key())
            if allocation is not None and (not isinstance(allocation, ContractorInventoryAllocationView)
                    or allocation.inventory_ref.key() != inventory.ref.key()
                    or allocation.batch_ref.key() != inventory.batch_ref.key()):
                raise TaskConflict('Work execution inventory ledger changes its original position or batch')
    if profile is not None:
        for material in profile.materials:
            if material.task_ref.key() != task.ref.key():
                raise TaskConflict('Work execution selected material changes the original task')
            allocation = sources.get(material.allocation_ref.key())
            if allocation is not None and (not isinstance(allocation, ContractorInventoryAllocationView)
                    or allocation.task_ref.key() != task.ref.key() or allocation.batch_ref.key() != material.batch_ref.key()):
                raise TaskConflict('Work execution selected material changes original task or allocated batch')
