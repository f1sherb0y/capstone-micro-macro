"""Persist original Supplier A01 screening outcomes without formal intention effects."""
from dataclasses import dataclass

from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from integration.supplier_screening_actions import PreparedSupplierScreening
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_objects import (
    SupplierCapabilityView, SupplierCapacityView, SupplyInquiryView,
    SupplyMarketObservationView, SupplyScreeningProfileView, supplier_screening_schemas,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedSupplierScreening(SavedSupplierQuote):
    """Historical own screening evidence; response is not a quote, order or reservation."""


class SupplierScreeningResultWorker(SupplierQuoteResultWorker):
    """Reuse original result-first, pending and recovery rules with an A01 schema/table."""
    SCHEMA = 'supplier-screening-result.v1'
    ACTION_ID = 'SUPPLIER-A01'
    PREPARED_TYPE = PreparedSupplierScreening
    RESULT_TABLE = 'supplier_screening_results'
    WAIT_KIND = 'manual_supplier_screening_result_review'
    EXECUTION_ERROR_CODE = 'supplier_screening_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_screening_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A01', 'SUPPLIER-A02', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierScreening

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']) == ref]
        if len(originals) != 1:
            raise TaskConflict('Saved screening lacks its exact original inquiry or private source')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref != ref:
            raise TaskConflict('Saved screening projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        private = [self._original(sources, Reference.model_validate(action_input[field]), schema)
            for field, schema in (('capability_ref', SupplierCapabilityView),
                ('capacity_ref', SupplierCapacityView), ('screening_profile_ref', SupplyScreeningProfileView))]
        if (any(row.organization_id != identity.organization_id for row in private)
                or context.scope.kind == 'organization' and context.scope.ref.id != identity.organization_id):
            raise TaskConflict('Saved screening changes original Supplier private facts or own scope')
        for raw_ref in action_input['inquiry_refs']:
            inquiry = self._original(sources, Reference.model_validate(raw_ref), SupplyInquiryView)
            if (inquiry.recipient_id != context.actor_id
                    or inquiry.recipient_organization_id != identity.organization_id):
                raise TaskConflict('Saved screening changes original private inquiry recipient')
        for raw_ref in action_input['market_refs']:
            self._original(sources, Reference.model_validate(raw_ref), SupplyMarketObservationView)

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A01 saved screening is not an A03 quote or a formal supply intention receipt')

    def prepare_product_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, inquiry_ref, requirement_refs, validate_history, validate_current):
        from integration.supplier_screening_handoff import prepare_supplier_screening_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_screening_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, inquiry_ref=inquiry_ref, requirement_refs=requirement_refs, validate_current=validate_current)
