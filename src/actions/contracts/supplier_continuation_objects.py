"""Supplier continuation keeps original goods and execution identities intact."""
from typing import Literal

from src.actions.contracts.common import Measured, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.commercial_continuation_objects import (
    CommercialContinuationStateView, CommercialContinuationProfileView,
    CommercialMaterialView, CommercialMaterialDisposition, CommercialMaterialPlanView,
    CommercialAssetRightView, CommercialVerificationView, CommercialTransferPlanView,
    commercial_continuation_types, commercial_continuation_schemas,
)
from src.actions.contracts.supplier_execution_objects import SupplierProductionExecutionView
from src.actions.contracts.supplier_logistics_objects import SupplierShipmentView


class SupplierContinuationStateView(CommercialContinuationStateView):
    work_in_progress_refs: list[ref_type('ProductionPosition')]
    shipment_refs: list[ref_type('Shipment')]
    production_line_commitment_refs: list[ref_type('ResourceCommitment')]


class SupplierContinuationProfileView(CommercialContinuationProfileView):
    choice: Literal['protect','suspend','resume','handover','cancel','close_cleared_scope','record_lesson']


class SupplierContinuationInventoryView(CommercialMaterialView):
    total_remaining: ValueState[Measured]


class SupplierContinuationProductionView(SupplierContinuationInventoryView):
    ref: ref_type('ProductionPosition')
    task_ref: ref_type('SupplyTask')
    execution_ref: ref_type('ProductionExecution')
    status: Literal['in_progress','completed','held','damaged','unknown']


class SupplierContinuationShipmentView(SupplierShipmentView):
    physical_position_key: TextId
    owner_organization_id: TextId
    custodian_organization_id: TextId
    right_ref: ref_type('AssetRight')
    total_remaining: ValueState[Measured]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


SupplierGoodsRef = ref_type('InventoryPosition') | ref_type('ProductionPosition') | ref_type('Shipment')


class SupplierGoodsDisposition(CommercialMaterialDisposition):
    position_ref: SupplierGoodsRef
    choice: Literal['preserve','retain_custody','return','handover','query_original','resale','scrap','self_use']


class SupplierGoodsDispositionPlanView(CommercialMaterialPlanView):
    items: list[SupplierGoodsDisposition]


class SupplierGoodsRightView(CommercialAssetRightView):
    position_ref: SupplierGoodsRef


class SupplierResumeVerificationView(CommercialVerificationView):
    family: Literal['resources','materials','production','logistics','funding','safety']


class SupplierTransferPlanView(CommercialTransferPlanView):
    work_in_progress_refs: list[ref_type('ProductionPosition')]
    shipment_refs: list[ref_type('Shipment')]


def supplier_continuation_types():
    return {**commercial_continuation_types(),
        'ContinuationState':SupplierContinuationStateView,
        'ContinuationProfile':SupplierContinuationProfileView,
        'InventoryPosition':SupplierContinuationInventoryView,
        'ProductionPosition':SupplierContinuationProductionView,
        'ProductionExecution':SupplierProductionExecutionView,
        'Shipment':SupplierContinuationShipmentView,
        'MaterialDispositionPlan':SupplierGoodsDispositionPlanView,
        'AssetRight':SupplierGoodsRightView,
        'Verification':SupplierResumeVerificationView,
        'ContinuationTransferPlan':SupplierTransferPlanView}


def supplier_continuation_schemas():
    return commercial_continuation_schemas(supplier_continuation_types())
