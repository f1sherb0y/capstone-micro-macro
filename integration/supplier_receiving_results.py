"""Persist original A09 Supplier responses without granting receiver or payment rights."""
from dataclasses import dataclass

from integration.supplier_logistics_handoff import supplier_logistics_handoff_schemas
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from integration.supplier_receiving_actions import PreparedSupplierReceiving
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_receiving_objects import (
    SupplierArrivalEvidenceView, SupplierCustomerReceiptView, SupplierDeliveryDiscrepancyView,
    SupplierDeliveryResponseProfileView, SupplierLogisticsOrderView, SupplierReceiptInspectionView,
    SupplierReceivingPartyView, SupplierReceivingShipmentView, supplier_receiving_schemas,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class SavedSupplierReceiving(SavedSupplierQuote):
    """Historical Supplier response; independent receipt, inspection and use rights stay separate."""


class SupplierReceivingResultWorker(SupplierQuoteResultWorker):
    """Reuse original claim, result-first, pending and recovery rules in an A09 table."""
    SCHEMA = 'supplier-receiving-result.v1'
    ACTION_ID = 'SUPPLIER-A09'
    PREPARED_TYPE = PreparedSupplierReceiving
    RESULT_TABLE = 'supplier_receiving_results'
    WAIT_KIND = 'manual_supplier_receiving_result_review'
    EXECUTION_ERROR_CODE = 'supplier_receiving_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_logistics_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A09', 'SUPPLIER-A10', 'SUPPLIER-A11', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierReceiving

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']) == ref]
        if len(originals) != 1:
            raise TaskConflict('Saved receiving lacks its exact original shipment or source version')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref != ref:
            raise TaskConflict('Saved receiving projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        shipment = self._original(sources, Reference.model_validate(action_input['shipment_ref']), SupplierReceivingShipmentView)
        profile = self._original(sources, shipment.response_profile_ref, SupplierDeliveryResponseProfileView)
        order = self._original(sources, shipment.order_ref, SupplierLogisticsOrderView)
        if (shipment.organization_id != identity.organization_id or shipment.run_id != identity.run_id
                or order.supplier_id != identity.organization_id or not scope_covers(order.scope, context.scope)
                or profile.shipment_ref != shipment.ref or profile.organization_id != identity.organization_id
                or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                or profile.scope != context.scope or profile.authority_ref not in context.authorization_refs):
            raise TaskConflict('Saved receiving changes original Supplier, shipment, order or profile authority')
        for field, schema in (('arrival_refs', SupplierArrivalEvidenceView), ('receipt_refs', SupplierCustomerReceiptView),
                ('inspection_refs', SupplierReceiptInspectionView), ('discrepancy_refs', SupplierDeliveryDiscrepancyView)):
            for raw_ref in action_input[field]:
                if self._original(sources, Reference.model_validate(raw_ref), schema).shipment_ref != shipment.ref:
                    raise TaskConflict('Saved receiving evidence changes its original shipment')
        for raw_ref in action_input['receiving_party_refs']:
            if self._original(sources, Reference.model_validate(raw_ref), SupplierReceivingPartyView).order_ref != order.ref:
                raise TaskConflict('Saved receiving party changes its original order')

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A09 saved Supplier response is not an A03 quote, receiver approval or payment entitlement')

    def prepare_payment_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, delivery_refs, order_refs, validate_history, validate_current):
        from integration.supplier_receiving_handoff import prepare_supplier_receiving_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_receiving_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, delivery_refs=delivery_refs, order_refs=order_refs, validate_current=validate_current)
