"""Actual production inputs, original commands and external delivery identities."""
from typing import Literal

from src.actions.contracts.common import Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_planning_objects import SupplierPlannedAllocation, SupplierMethodInput, QuoteProductLine


class SupplierActualInputUse(StrictRecord):
    batch_ref: ref_type('MaterialBatch')
    allocation_ref: ref_type('InventoryAllocation')
    quantity: Measured


class SupplierExecutionTaskView(CostSource):
    ref: ref_type('SupplyTask')
    organization_id: TextId
    mode: Literal['manufacture', 'purchase', 'rework']
    profile_ref: ref_type('SupplyExecutionProfile')
    production_method_ref: ref_type('ProductionMethod') | None
    purchase_order_ref: ref_type('Order') | None
    execution_window: TimeWindow
    remaining_target: Measured
    source_rework_batch_refs: list[ref_type('MaterialBatch')]
    state: Literal['planned', 'released', 'working', 'blocked', 'complete', 'cancelled']
    prior_execution_refs: list[ref_type('ProductionExecution')]
    upstream_delivery_refs: list[ref_type('ExternalDelivery')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class SupplierExecutionProfileView(CostSource):
    ref: ref_type('SupplyExecutionProfile')
    task_ref: ref_type('SupplyTask')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['execute', 'rebalance', 'reconcile_upstream', 'reconcile_execution', 'request_maintenance']
    inputs: list[SupplierActualInputUse]
    resources: list[SupplierPlannedAllocation]
    maintenance_resource_ref: ref_type('ResourcePool') | None
    issue_refs: list[ref_type('Issue')]
    note: TextId


class SupplierProductionReleaseView(CostSource):
    ref: ref_type('TaskRelease')
    organization_id: TextId
    task_ref: ref_type('SupplyTask')
    method_ref: ref_type('ProductionMethod')
    gate_ref: ref_type('ProductionGateSnapshot')
    core_event_id: TextId
    status: Literal['released', 'suspended', 'revoked', 'expired']


class SupplierProductionGateView(CostSource):
    ref: ref_type('ProductionGateSnapshot')
    task_ref: ref_type('SupplyTask')
    release_ref: ref_type('TaskRelease')
    satisfied: ValueState[bool]
    requirement_refs: list[ref_type('Requirement')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    producer: Literal['core']


class SupplierProductionRequirementView(CostSource):
    ref: ref_type('Requirement')
    task_ref: ref_type('SupplyTask')
    satisfied: ValueState[bool]


class SupplierProductionMethodView(CostSource):
    ref: ref_type('ProductionMethod')
    mode: Literal['manufacture', 'rework']
    supported: ValueState[bool]
    output_unit: TextId
    input_recipe: list[SupplierMethodInput]
    resource_kind: TextId
    minimum_resource: Measured
    consequence_rule_ref: ref_type('ProductionRule')
    accelerated: bool


class SupplierProductionRuleView(CostSource):
    ref: ref_type('ProductionRule')
    method_ref: ref_type('ProductionMethod')
    supported: ValueState[bool]
    acceleration_modeled: ValueState[bool]
    conversion_basis_ref: ref_type('Evidence')
    throughput_basis_ref: ref_type('Evidence')
    loss_basis_ref: ref_type('Evidence')
    quality_basis_ref: ref_type('Evidence')
    cost_basis_ref: ref_type('Evidence')


class SupplierActualResourceView(CostSource):
    ref: ref_type('ResourcePool')
    organization_id: TextId
    resource_kind: TextId
    actually_present: ValueState[bool]
    actual_capacity: ValueState[Measured]
    reservation_refs: list[ref_type('ProductionResourceReservation')]
    pending_execution_refs: list[ref_type('ProductionExecution')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class SupplierProductionAllocationView(CostSource):
    ref: ref_type('ResourceAllocation')
    organization_id: TextId
    task_ref: ref_type('SupplyTask')
    resource_ref: ref_type('ResourcePool')
    reservation_ref: ref_type('ProductionResourceReservation')
    quantity: Measured
    window: TimeWindow
    status: Literal['reserved', 'available', 'consumed', 'released', 'unknown']
    as_of: TimePoint


class SupplierProductionReservationView(CostSource):
    ref: ref_type('ProductionResourceReservation')
    task_ref: ref_type('SupplyTask')
    resource_ref: ref_type('ResourcePool')
    allocation_ref: ref_type('ResourceAllocation')
    quantity: Measured
    window: TimeWindow
    core_event_id: TextId
    status: Literal['reserved', 'released', 'consumed']


class SupplierActualStockPosition(StrictRecord):
    batch_ref: ref_type('MaterialBatch')
    product_ref: ref_type('ProductSpecification')
    actual: Measured
    usable: Measured
    reserved: Measured
    state: Literal['usable', 'awaiting_inspection', 'quarantined', 'awaiting_rework', 'scrapped']
    allocation_refs: list[ref_type('InventoryAllocation')]


class SupplierActualInventoryView(CostSource):
    ref: ref_type('InventorySnapshot')
    organization_id: TextId
    positions: list[SupplierActualStockPosition]
    pending_execution_refs: list[ref_type('ProductionExecution')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class SupplierActualMaterialView(CostSource):
    ref: ref_type('MaterialBatch')
    organization_id: TextId
    product_ref: ref_type('ProductSpecification')
    core_event_id: TextId
    actual_received: ValueState[bool]
    actual_quantity: Measured
    usable: Measured
    state: Literal['usable', 'awaiting_inspection', 'quarantined', 'awaiting_rework', 'scrapped']


class SupplierActualInventoryAllocationView(CostSource):
    ref: ref_type('InventoryAllocation')
    organization_id: TextId
    task_ref: ref_type('SupplyTask')
    inventory_ref: ref_type('InventorySnapshot')
    batch_ref: ref_type('MaterialBatch')
    quantity: Measured
    used_quantity: Measured
    core_event_id: TextId
    purpose: Literal['manufacture', 'rework']
    status: Literal['reserved', 'consumed', 'released', 'unknown']
    as_of: TimePoint


class SupplierProductionRequestView(CostSource):
    ref: ref_type('ProductionRequest')
    task_ref: ref_type('SupplyTask')
    organization_id: TextId
    run_id: TextId
    operation_id: TextId
    business_key: TextId
    release_ref: ref_type('TaskRelease')
    method_ref: ref_type('ProductionMethod')
    inputs: list[SupplierActualInputUse]
    resources: list[SupplierPlannedAllocation]


class SupplierProductionExecutionView(CostSource):
    ref: ref_type('ProductionExecution')
    organization_id: TextId
    task_ref: ref_type('SupplyTask')
    run_id: TextId
    operation_id: TextId
    business_key: TextId
    request_ref: ref_type('ProductionRequest')
    request_sha256: Digest
    status: Literal['submitted_unknown', 'recorded', 'rejected', 'failed']
    query_status: Literal['present', 'absent', 'unknown', 'not_queried']
    core_event_id: TextId | None
    recorded_at: TimePoint | None
    movement_refs: list[ref_type('StockMovement')]
    recovery_ref: ref_type('ProductionRecovery') | None


def validate_supplier_reconciliation_task(original, current, execution, *, run_id, organization_id):
    """Bind a current query task to the exact task saved by a production command."""
    if (not isinstance(original, SupplierExecutionTaskView) or not isinstance(current, SupplierExecutionTaskView)
            or not isinstance(execution, SupplierProductionExecutionView)
            or original.ref.key() != execution.task_ref.key()
            or (original.ref.kind, original.ref.id) != (current.ref.kind, current.ref.id)
            or execution.run_id != run_id
            or any(row.organization_id != organization_id for row in (original, current, execution))
            or execution.scope != original.scope
            or any(getattr(original, field) != getattr(current, field) for field in (
                'organization_id', 'mode', 'production_method_ref', 'purchase_order_ref', 'source_rework_batch_refs', 'scope'))
            or execution.ref.key() not in {ref.key() for ref in current.prior_execution_refs}
            or not {(ref.kind, ref.id) for ref in original.prior_execution_refs}
                <= {(ref.kind, ref.id) for ref in current.prior_execution_refs}):
        raise ValueError('Production reconciliation changes original physical task, method, purchase/rework lineage or command history')


class SupplierProductionRecoveryView(CostSource):
    ref: ref_type('ProductionRecovery')
    execution_ref: ref_type('ProductionExecution')
    organization_id: TextId
    task_ref: ref_type('SupplyTask')
    authority_ref: ref_type('Authorization')
    new_operation_id: TextId
    original_effects_absent: ValueState[bool]
    retry_permitted: ValueState[bool]


class SupplierStockMovementView(CostSource):
    ref: ref_type('StockMovement')
    organization_id: TextId
    execution_ref: ref_type('ProductionExecution')
    core_event_id: TextId
    physical_movement_key: TextId
    kind: Literal['input_consumed', 'wip_created', 'pending_inspection_created', 'loss_recorded', 'rework_return']
    quantity: Measured
    source_allocation_refs: list[ref_type('InventoryAllocation')]
    lineage_batch_refs: list[ref_type('MaterialBatch')]


class SupplierExecutionOrderLine(StrictRecord):
    line_ref: ref_type('OrderLine')
    product: QuoteProductLine


class SupplierExecutionOrderView(CostSource):
    ref: ref_type('Order')
    supplier_id: TextId
    buyer_id: TextId
    effective: ValueState[bool]
    lines: list[SupplierExecutionOrderLine]
    delivery_refs: list[ref_type('ExternalDelivery')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    core_event_id: TextId


class SupplierExternalDeliveryLine(StrictRecord):
    order_line_ref: ref_type('OrderLine')
    batch_ref: ref_type('MaterialBatch')
    product_ref: ref_type('ProductSpecification')
    actual_quantity: Measured


class SupplierExternalDeliveryView(CostSource):
    ref: ref_type('ExternalDelivery')
    order_ref: ref_type('Order')
    supplier_id: TextId
    buyer_id: TextId
    command_id: TextId
    business_key: TextId
    status: Literal['in_transit', 'arrived', 'receipt_recorded', 'rejected', 'unknown']
    core_event_id: TextId | None
    lines: list[SupplierExternalDeliveryLine]
    receipt_refs: list[ref_type('GoodsReceipt')]


class SupplierGoodsReceiptRuleView(CostSource):
    ref: ref_type('GoodsReceiptRule')
    order_ref: ref_type('Order')
    buyer_id: TextId
    supported: ValueState[bool]
    permitted: ValueState[bool]
    inspection_required: bool


class SupplierGoodsReceiptView(CostSource):
    ref: ref_type('GoodsReceipt')
    delivery_ref: ref_type('ExternalDelivery')
    order_ref: ref_type('Order')
    buyer_id: TextId
    command_id: TextId
    business_key: TextId
    core_event_id: TextId
    lines: list[SupplierExternalDeliveryLine]
    status: Literal['received_awaiting_inspection', 'accepted', 'quarantined', 'rejected']
    inspection_evidence_refs: list[ref_type('Evidence')]


class SupplierMaintenanceIssueView(CostSource):
    ref: ref_type('Issue')
    resource_ref: ref_type('ResourcePool')
    organization_id: TextId
    observation_ref: ref_type('ResourceObservation')
    status: Literal['open', 'under_maintenance', 'resolved']


class SupplierResourceObservationView(CostSource):
    ref: ref_type('ResourceObservation')
    resource_ref: ref_type('ResourcePool')
    organization_id: TextId
    actual: ValueState[bool]
    observed_at: TimePoint
    core_event_id: TextId


def supplier_execution_schemas():
    return contractor_bid_schemas({
        'SupplyTask': SupplierExecutionTaskView, 'SupplyExecutionProfile': SupplierExecutionProfileView,
        'TaskRelease': SupplierProductionReleaseView, 'ProductionGateSnapshot': SupplierProductionGateView,
        'Requirement': SupplierProductionRequirementView, 'ProductionMethod': SupplierProductionMethodView,
        'ProductionRule': SupplierProductionRuleView, 'ResourcePool': SupplierActualResourceView,
        'ResourceAllocation': SupplierProductionAllocationView, 'ProductionResourceReservation': SupplierProductionReservationView,
        'InventorySnapshot': SupplierActualInventoryView, 'MaterialBatch': SupplierActualMaterialView,
        'InventoryAllocation': SupplierActualInventoryAllocationView, 'ProductionRequest': SupplierProductionRequestView,
        'ProductionExecution': SupplierProductionExecutionView, 'StockMovement': SupplierStockMovementView,
        'ProductionRecovery': SupplierProductionRecoveryView,
        'Order': SupplierExecutionOrderView, 'ExternalDelivery': SupplierExternalDeliveryView,
        'GoodsReceiptRule': SupplierGoodsReceiptRuleView, 'GoodsReceipt': SupplierGoodsReceiptView,
        'Issue': SupplierMaintenanceIssueView, 'ResourceObservation': SupplierResourceObservationView,
    })
