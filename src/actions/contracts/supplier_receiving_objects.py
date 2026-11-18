"""Supplier responses preserve arrival, receipt, inspection and use boundaries."""
from typing import Literal

from src.actions.contracts.common import Measured, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_logistics_objects import SupplierShipmentView, SupplierLogisticsOrderView
from src.actions.contracts.supplier_quote_objects import QuoteProductLine
from src.actions.contracts.supplier_planning_objects import SupplierPlanningProductView


class SupplierReceivingShipmentView(SupplierShipmentView):
    response_profile_ref: ref_type('DeliveryResponseProfile')
    arrival_refs: list[ref_type('ArrivalEvidence')]
    receipt_refs: list[ref_type('GoodsReceipt')]
    inspection_refs: list[ref_type('InspectionResult')]
    discrepancy_refs: list[ref_type('DeliveryDiscrepancy')]
    receiving_party_refs: list[ref_type('ReceivingParty')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class SupplierDeliveryResponseProfileView(CostSource):
    ref: ref_type('DeliveryResponseProfile')
    shipment_ref: ref_type('Shipment')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['acknowledge_receipt', 'supplement_evidence', 'propose_replacement', 'contest_discrepancy']
    receipt_ref: ref_type('GoodsReceipt') | None
    accepted_fact_refs: list[ref_type('ReceiptComponent')]
    supplement_ref: ref_type('DeliverySupplement') | None
    issue_ref: ref_type('DeliveryDiscrepancy') | None
    replacement_ref: ref_type('DeliveryReplacementProposal') | None
    component_refs: list[ref_type('ReceiptComponent')]
    evidence_refs_received: list[ref_type('Evidence')]
    note: TextId


class SupplierArrivalEvidenceView(CostSource):
    ref: ref_type('ArrivalEvidence')
    shipment_ref: ref_type('Shipment')
    physical_batch_key: TextId
    destination_ref: ref_type('Location')
    quantity: Measured
    arrived_at: TimePoint
    core_event_id: TextId
    producer: Literal['core']


class SupplierReceivingPartyView(CostSource):
    ref: ref_type('ReceivingParty')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    allowed_action_ids: list[TextId]
    allowed_purposes: list[Literal['receipt', 'inspection', 'use_release']]
    order_ref: ref_type('Order')
    destination_ref: ref_type('Location')
    permitted: ValueState[bool]
    mandate_ref: ref_type('ReceivingMandate')


class SupplierReceivingMandateView(GovReviewAuthored):
    ref: ref_type('ReceivingMandate')
    order_ref: ref_type('Order')
    receiving_party_ref: ref_type('ReceivingParty')
    recipient_organization_id: TextId
    allowed_purposes: list[Literal['receipt', 'inspection', 'use_release']]
    permitted: ValueState[bool]


class SupplierCustomerReceiptView(GovReviewAuthored):
    ref: ref_type('GoodsReceipt')
    shipment_ref: ref_type('Shipment')
    arrival_refs: list[ref_type('ArrivalEvidence')]
    receiving_party_ref: ref_type('ReceivingParty')
    component_refs: list[ref_type('ReceiptComponent')]
    command_id: TextId
    business_key: TextId
    core_event_id: TextId
    status: Literal['recorded', 'pending', 'rejected', 'unknown']


class SupplierReceiptComponentView(CostSource):
    ref: ref_type('ReceiptComponent')
    shipment_ref: ref_type('Shipment')
    receipt_ref: ref_type('GoodsReceipt')
    physical_slice_key: TextId
    product_ref: ref_type('ProductSpecification')
    expected_quantity: Measured
    received_quantity: Measured
    damaged_quantity: Measured
    rejected_quantity: Measured
    quarantined_quantity: Measured
    usable_quantity: Measured
    specification_matches: ValueState[bool]
    status: Literal['received', 'short', 'damaged', 'rejected', 'quarantined', 'disputed']
    inspection_refs: list[ref_type('InspectionResult')]
    use_release_refs: list[ref_type('GoodsUseRelease')]


class SupplierReceiptInspectionView(GovReviewAuthored):
    ref: ref_type('InspectionResult')
    shipment_ref: ref_type('Shipment')
    component_refs: list[ref_type('ReceiptComponent')]
    receiving_party_ref: ref_type('ReceivingParty')
    method_ref: ref_type('GoodsInspectionMethod')
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    passed: ValueState[bool]
    covered_quantity: Measured
    use_codes: list[TextId]


class SupplierGoodsInspectionMethodView(CostSource):
    ref: ref_type('GoodsInspectionMethod')
    supported: ValueState[bool]
    product_refs: list[ref_type('ProductSpecification')]
    use_codes: list[TextId]
    allowed_author_action_ids: list[TextId]


class SupplierGoodsUseReleaseView(GovReviewAuthored):
    ref: ref_type('GoodsUseRelease')
    shipment_ref: ref_type('Shipment')
    component_ref: ref_type('ReceiptComponent')
    receiving_party_ref: ref_type('ReceivingParty')
    inspection_ref: ref_type('InspectionResult')
    quantity: Measured
    use_codes: list[TextId]
    permitted: ValueState[bool]
    core_event_id: TextId


class SupplierDeliveryDiscrepancyView(GovReviewAuthored):
    ref: ref_type('DeliveryDiscrepancy')
    shipment_ref: ref_type('Shipment')
    component_refs: list[ref_type('ReceiptComponent')]
    status: Literal['open', 'pending', 'disputed', 'resolved']
    replacement_remaining: Measured
    replacement_proposal_refs: list[ref_type('DeliveryReplacementProposal')]
    replacement_history_complete: bool
    as_of: TimePoint


class SupplierDeliverySupplementView(GovReviewAuthored):
    ref: ref_type('DeliverySupplement')
    shipment_ref: ref_type('Shipment')
    discrepancy_refs: list[ref_type('DeliveryDiscrepancy')]
    receipt_component_refs: list[ref_type('ReceiptComponent')]
    attachment_refs: list[ref_type('Evidence')]
    purpose: Literal['supplement', 'contest']


class SupplierDeliveryReplacementView(GovReviewAuthored):
    ref: ref_type('DeliveryReplacementProposal')
    shipment_ref: ref_type('Shipment')
    discrepancy_ref: ref_type('DeliveryDiscrepancy')
    business_key: TextId
    lines: list[QuoteProductLine]
    status: Literal['proposal', 'pending', 'accepted', 'withdrawn', 'rejected']


class SupplierReplacementRequirementView(CostSource):
    ref: ref_type('Requirement')
    discrepancy_ref: ref_type('DeliveryDiscrepancy')
    product_refs: list[ref_type('ProductSpecification')]


class SupplierReplacementDeviationView(GovReviewAuthored):
    ref: ref_type('SpecificationDeviation')
    discrepancy_ref: ref_type('DeliveryDiscrepancy')
    product_ref: ref_type('ProductSpecification')
    requirement_refs: list[ref_type('Requirement')]
    status: Literal['proposal', 'pending', 'approved', 'rejected']


def supplier_receiving_schemas():
    return contractor_bid_schemas({
        'Shipment': SupplierReceivingShipmentView, 'Order': SupplierLogisticsOrderView,
        'DeliveryResponseProfile': SupplierDeliveryResponseProfileView, 'ArrivalEvidence': SupplierArrivalEvidenceView,
        'ReceivingParty': SupplierReceivingPartyView, 'GoodsReceipt': SupplierCustomerReceiptView,
        'ReceivingMandate': SupplierReceivingMandateView,
        'ReceiptComponent': SupplierReceiptComponentView, 'InspectionResult': SupplierReceiptInspectionView,
        'GoodsInspectionMethod': SupplierGoodsInspectionMethodView, 'GoodsUseRelease': SupplierGoodsUseReleaseView,
        'DeliveryDiscrepancy': SupplierDeliveryDiscrepancyView, 'DeliverySupplement': SupplierDeliverySupplementView,
        'DeliveryReplacementProposal': SupplierDeliveryReplacementView, 'Requirement': SupplierReplacementRequirementView,
        'SpecificationDeviation': SupplierReplacementDeviationView, 'ProductSpecification': SupplierPlanningProductView,
    })
