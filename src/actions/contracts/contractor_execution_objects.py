"""Released task input intentions and immutable original execution provenance."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import ContractorBidAllocation, ContractorBidMethodView
from src.actions.contracts.contractor_readiness_objects import (
    ContractorReadyTaskView, ContractorReadyAllocationView, ContractorReadyInputView,
    ContractorReadyAllocationFactView, ContractorReadyActionView, ContractorWorkMandateView,
)
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView


class ContractorExecutionMaterial(StrictRecord):
    batch_ref: ref_type('MaterialBatch')
    allocation_ref: ref_type('InventoryAllocation')
    quantity: Measured
    task_ref: ref_type('Task')


class ContractorExecutionTaskView(ContractorReadyTaskView):
    work_method_ref: ref_type('WorkMethod')
    execution_profile_ref: ref_type('WorkExecutionProfile')
    prior_execution_refs: list[ref_type('WorkExecution')]
    inventory_refs: list[ref_type('InventoryPosition')]
    condition_refs: list[ref_type('SiteCondition')]


class ContractorExecutionProfileView(CostSource):
    ref: ref_type('WorkExecutionProfile')
    organization_id: TextId
    task_ref: ref_type('Task')
    authority_ref: ref_type('Authorization')
    choice: Literal['execute', 'rebalance', 'report']
    allocations: list[ContractorBidAllocation]
    materials: list[ContractorExecutionMaterial]
    reported_status: Literal['working', 'blocked', 'awaiting_check']
    requested_requirement_refs: list[ref_type('Requirement')]
    note: TextId


class ContractorTaskReleaseView(CostSource):
    ref: ref_type('TaskRelease')
    organization_id: TextId
    task_ref: ref_type('Task')
    action_ref: ref_type('ActionDefinition')
    work_method_ref: ref_type('WorkMethod')
    current_gate_ref: ref_type('ExecutionGateSnapshot')
    core_event_id: TextId
    status: Literal['released', 'suspended', 'revoked', 'expired']


class ContractorExecutionGateView(CostSource):
    ref: ref_type('ExecutionGateSnapshot')
    task_ref: ref_type('Task')
    release_ref: ref_type('TaskRelease')
    requirement_refs: list[ref_type('Requirement')]
    satisfied: ValueState[bool]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    producer: Literal['core']


class ContractorExecutionMethodView(ContractorBidMethodView):
    minimum_resource_quantity: Measured
    minimum_material_quantity: Measured | None
    material_product_ref: ref_type('ProductSpecification') | None
    required_condition_codes: list[TextId]
    accelerated: bool
    consequence_rule_ref: ref_type('ProductionRule')


class ContractorExecutionInputView(ContractorReadyInputView):
    region_id: TextId
    resource_kind: TextId
    actually_present: ValueState[bool]


class ContractorProductionRuleView(CostSource):
    ref: ref_type('ProductionRule')
    work_method_ref: ref_type('WorkMethod')
    supported: ValueState[bool]
    acceleration_modeled: ValueState[bool]
    throughput_basis_ref: ref_type('Evidence')
    cost_basis_ref: ref_type('Evidence')
    quality_basis_ref: ref_type('Evidence')


class ContractorInventoryView(CostSource):
    ref: ref_type('InventoryPosition')
    organization_id: TextId
    batch_ref: ref_type('MaterialBatch')
    product_ref: ref_type('ProductSpecification')
    usable: ValueState[Measured]
    allocation_refs: list[ref_type('InventoryAllocation')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class ContractorInventoryAllocationView(CostSource):
    ref: ref_type('InventoryAllocation')
    inventory_ref: ref_type('InventoryPosition')
    batch_ref: ref_type('MaterialBatch')
    task_ref: ref_type('Task')
    quantity: Measured
    already_consumed: Measured
    status: Literal['allocated', 'released', 'consumed', 'unknown']
    core_event_id: TextId


class ContractorReceivedMaterialView(CostSource):
    """Actual receipt-to-stock mapping, supplied by the receiving application."""
    ref: ref_type('ReceivedMaterialBasis')
    run_id: TextId
    organization_id: TextId
    supplier_organization_id: TextId
    receiving_task_sha256: Digest
    receiving_record_sha256: Digest
    receiving_result_sha256: Digest
    receiving_source_reading_sha256: Digest
    receipt_ref: ref_type('GoodsReceipt')
    component_ref: ref_type('ReceiptComponent')
    physical_slice_key: TextId
    use_release_refs: list[ref_type('GoodsUseRelease')]
    use_code: TextId
    inventory_ref: ref_type('InventoryPosition')
    inventory_sha256: Digest
    batch_ref: ref_type('MaterialBatch')
    batch_sha256: Digest
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    received_at: TimePoint


class ContractorExecutionConditionView(GovReviewAuthored):
    ref: ref_type('SiteCondition')
    task_ref: ref_type('Task')
    condition_code: TextId
    actual_satisfied: ValueState[bool]
    as_of: TimePoint


class ContractorWorkExecutionView(CostSource):
    ref: ref_type('WorkExecution')
    organization_id: TextId
    run_id: TextId
    task_ref: ref_type('Task')
    operation_id: TextId
    business_key: TextId
    request_sha256: Digest
    request_ref: ref_type('WorkExecutionRequest')
    core_event_id: TextId | None
    status: Literal['recorded', 'submitted_unknown', 'failed', 'not_executed']
    query_status: Literal['present', 'absent', 'unknown', 'not_queried']
    recorded_at: TimePoint | None
    work_record_refs: list[ref_type('WorkRecord')]


class ContractorExecutionRequestView(CostSource):
    ref: ref_type('WorkExecutionRequest')
    task_ref: ref_type('Task')
    operation_id: TextId
    business_key: TextId
    scope_ref: ScopeRef
    allocations: list[ContractorBidAllocation]
    materials: list[ContractorExecutionMaterial]


class ContractorWorkRecordView(CostSource):
    ref: ref_type('WorkRecord')
    execution_ref: ref_type('WorkExecution')
    core_event_id: TextId
    physical_work_key: TextId
    work_kind: Literal['new_work', 'rework']
    gross_quantity: Measured
    net_quantity: Measured
    original_work_record_ref: ref_type('WorkRecord') | None


def validate_contractor_work_record_execution(execution, record, command):
    """Bind an immutable work record to its exact original command projection."""
    if (not isinstance(execution, ContractorWorkExecutionView)
            or not isinstance(record, ContractorWorkRecordView) or not isinstance(command, ContractorWorkExecutionView)
            or execution.status != 'recorded' or execution.core_event_id is None
            or record.ref not in execution.work_record_refs or record.core_event_id != execution.core_event_id
            or command.ref != record.execution_ref or command.ref.key()[:2] != execution.ref.key()[:2]
            or command.status not in {'submitted_unknown', 'recorded'}
            or any(getattr(command, field) != getattr(execution, field) for field in (
                'organization_id', 'run_id', 'task_ref', 'operation_id', 'business_key', 'request_ref', 'request_sha256', 'scope'))
            or command.available_at.clock_ref != execution.available_at.clock_ref
            or command.available_at.offset > execution.available_at.offset
            or command.status == 'recorded' and (
                command.core_event_id != execution.core_event_id or command.recorded_at != execution.recorded_at)):
        raise ValueError('Contractor work record changes its exact original command, request or known execution event')


def validate_contractor_recorded_work_history(original, current, before, after):
    """Preserve known physical work while query versions and metadata advance."""
    if (not isinstance(original, ContractorWorkExecutionView)
            or not isinstance(current, ContractorWorkExecutionView)
            or not isinstance(before, ContractorWorkRecordView) or not isinstance(after, ContractorWorkRecordView)
            or original.status != 'recorded' or current.status != 'recorded'
            or original.ref.key()[:2] != current.ref.key()[:2]
            or original.core_event_id is None or current.core_event_id != original.core_event_id
            or current.recorded_at != original.recorded_at
            or before.ref not in original.work_record_refs or after.ref not in current.work_record_refs
            or before.ref.key()[:2] != after.ref.key()[:2]
            or before.execution_ref.key()[:2] != original.ref.key()[:2]
            or after.execution_ref != before.execution_ref
            or before.core_event_id != original.core_event_id or after.core_event_id != current.core_event_id
            or any(getattr(before, field) != getattr(after, field) for field in (
                'scope', 'physical_work_key', 'work_kind', 'gross_quantity', 'net_quantity', 'original_work_record_ref'))):
        raise ValueError('Recorded Contractor work query changes known engineering quantities, scope or provenance')


class ContractorExecutionObservationView(GovReviewAuthored):
    ref: ref_type('Observation')
    task_ref: ref_type('Task')
    status: Literal['working', 'blocked', 'awaiting_check']
    requirement_refs: list[ref_type('Requirement')]


class ContractorExecutionRequirementView(CostSource):
    ref: ref_type('Requirement')
    task_ref: ref_type('Task')
    responsible: ValueState[TextId]
    disposition: Literal['investigate', 'clarify', 'isolate', 'rectify', 'dispute']


def contractor_execution_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Task': ContractorExecutionTaskView, 'WorkExecutionProfile': ContractorExecutionProfileView,
        'TaskRelease': ContractorTaskReleaseView, 'ExecutionGateSnapshot': ContractorExecutionGateView,
        'WorkMethod': ContractorExecutionMethodView, 'ProductionRule': ContractorProductionRuleView,
        'ResourceAllocation': ContractorReadyAllocationView, 'ResourcePool': ContractorExecutionInputView,
        'ReadinessAllocationFact': ContractorReadyAllocationFactView, 'MaterialBatch': ContractorReadyInputView,
        'InventoryPosition': ContractorInventoryView, 'InventoryAllocation': ContractorInventoryAllocationView,
        'ReceivedMaterialBasis': ContractorReceivedMaterialView,
        'SiteCondition': ContractorExecutionConditionView, 'WorkExecution': ContractorWorkExecutionView,
        'WorkExecutionRequest': ContractorExecutionRequestView, 'WorkRecord': ContractorWorkRecordView,
        'Observation': ContractorExecutionObservationView, 'Requirement': ContractorExecutionRequirementView,
        'ActionDefinition': ContractorReadyActionView, 'Contract': ContractorWorkMandateView,
        'WorkAuthorization': ContractorWorkMandateView, 'ClockProfile': ServiceClockView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
