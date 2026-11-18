"""Persist original A08 logistics requests without recording native cargo effects."""
from dataclasses import dataclass

from integration.supplier_quality_handoff import supplier_quality_handoff_schemas
from integration.supplier_logistics_actions import PreparedSupplierLogistics
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_logistics_objects import (
    SupplierDispatchableView, SupplierLogisticsOrderView, SupplierLogisticsProfileView,
    SupplierReceivingWindowView, SupplierShipmentView, SupplierTransportRequirementView,
    SupplierTransportTermsView, supplier_logistics_schemas,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class SavedSupplierLogistics(SavedSupplierQuote):
    """Historical local transport evidence; no native dispatch or arrival is implied."""


class SupplierLogisticsResultWorker(SupplierQuoteResultWorker):
    """Share original claim-once, result-first and interrupted-recovery rules for A08."""
    SCHEMA = 'supplier-logistics-result.v1'
    ACTION_ID = 'SUPPLIER-A08'
    PREPARED_TYPE = PreparedSupplierLogistics
    RESULT_TABLE = 'supplier_logistics_results'
    WAIT_KIND = 'manual_supplier_logistics_result_review'
    EXECUTION_ERROR_CODE = 'supplier_logistics_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_quality_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A08', 'SUPPLIER-A09', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierLogistics

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']) == ref]
        if len(originals) != 1:
            raise TaskConflict('Saved logistics lacks its exact original order or source version')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref != ref:
            raise TaskConflict('Saved logistics projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        order = self._original(sources, Reference.model_validate(action_input['order_ref']), SupplierLogisticsOrderView)
        profile = self._original(sources, Reference.model_validate(action_input['logistics_profile_ref']), SupplierLogisticsProfileView)
        terms = self._original(sources, order.terms_ref, SupplierTransportTermsView)
        if (order.supplier_id != identity.organization_id or not scope_covers(order.scope, context.scope)
                or profile.order_ref != order.ref or profile.organization_id != identity.organization_id
                or profile.scope != context.scope or profile.actor_id != context.actor_id
                or profile.function_ref != context.function_ref or profile.authority_ref not in context.authorization_refs
                or terms.order_ref != order.ref or terms.supplier_id != identity.organization_id
                or terms.buyer_id != order.buyer_id):
            raise TaskConflict('Saved logistics changes original order, Supplier, parties, scope or profile authority')
        for field, schema in (('dispatchable_refs', SupplierDispatchableView),
                ('receiving_window_refs', SupplierReceivingWindowView),
                ('requirement_refs', SupplierTransportRequirementView), ('shipment_refs', SupplierShipmentView)):
            for raw_ref in action_input[field]:
                if self._original(sources, Reference.model_validate(raw_ref), schema).order_ref != order.ref:
                    raise TaskConflict('Saved logistics source changes its original order')

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A08 saved request/query is not an A03 quote, dispatch receipt or arrival confirmation')

    def prepare_receiving_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, shipment_ref, validate_history, validate_current):
        from integration.supplier_logistics_handoff import prepare_supplier_logistics_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_logistics_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, shipment_ref=shipment_ref, validate_current=validate_current)
