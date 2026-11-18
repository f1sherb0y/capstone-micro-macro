"""Persist original Supplier A02 proposals without independent approval or offer effects."""
from dataclasses import dataclass

from integration.supplier_screening_handoff import supplier_screening_handoff_schemas
from integration.supplier_product_actions import PreparedSupplierProduct
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_product_objects import (
    ProductCompatibilityMethodView, ProductDesignView, ProductRequirementView,
    ProductSpecificationView, SupplyInquiryView, supplier_product_schemas,
)
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class SavedSupplierProduct(SavedSupplierQuote):
    """Historical own proposal evidence; it is not a formal ProductProposal projection."""


class SupplierProductResultWorker(SupplierQuoteResultWorker):
    """Reuse original result-first, pending and recovery rules in an A02 schema/table."""
    SCHEMA = 'supplier-product-result.v1'
    ACTION_ID = 'SUPPLIER-A02'
    PREPARED_TYPE = PreparedSupplierProduct
    RESULT_TABLE = 'supplier_product_results'
    WAIT_KIND = 'manual_supplier_product_result_review'
    EXECUTION_ERROR_CODE = 'supplier_product_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_screening_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A02', 'SUPPLIER-A03', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierProduct

    def prepare_quote_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, validate_history, validate_current):
        """Load the actual stored A02 result before validating its current A03 source relation."""
        from integration.supplier_product_handoff import prepare_supplier_product_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_product_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, validate_current=validate_current)

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']) == ref]
        if len(originals) != 1:
            raise TaskConflict('Saved product proposal lacks its exact original inquiry or source version')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref != ref:
            raise TaskConflict('Saved product projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        inquiry = self._original(sources, Reference.model_validate(action_input['inquiry_ref']), SupplyInquiryView)
        method = self._original(sources, Reference.model_validate(action_input['compatibility_method_ref']), ProductCompatibilityMethodView)
        if (inquiry.recipient_id != context.actor_id or inquiry.recipient_organization_id != identity.organization_id
                or not scope_covers(context.scope, inquiry.scope) or method.organization_id != identity.organization_id):
            raise TaskConflict('Saved product proposal changes original Supplier, inquiry recipient, scope or method')
        for field, schema in (('requirement_refs', ProductRequirementView), ('design_refs', ProductDesignView)):
            for raw_ref in action_input[field]:
                if self._original(sources, Reference.model_validate(raw_ref), schema).inquiry_ref != inquiry.ref:
                    raise TaskConflict('Saved product requirement or design changes original inquiry')
        # Preserve the independent design authority and original product facts;
        # historical storage does not grant the Supplier professional approval.
        for field, schema in (('product_candidates', ProductSpecificationView), ('design_authority_refs', Authorization)):
            for raw_ref in action_input[field]:
                self._original(sources, Reference.model_validate(raw_ref), schema)

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A02 saved product proposal is not an A03 quote or independent product approval')
