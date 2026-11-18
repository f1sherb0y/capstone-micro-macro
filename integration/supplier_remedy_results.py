"""Persist original A11 remedy proposals without creating disposition or cash effects."""
from dataclasses import dataclass

from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from integration.supplier_remedy_actions import PreparedSupplierRemedy, validate_supplier_remedy_sources
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_remedy_objects import supplier_remedy_schemas


@dataclass(frozen=True)
class SavedSupplierRemedy(SavedSupplierQuote):
    """Historical Supplier proposal; liability, site rights and native effects stay separate."""


class SupplierRemedyResultWorker(SupplierQuoteResultWorker):
    """Reuse original claim-once, result-first and recovery rules in an A11 table."""
    SCHEMA = 'supplier-remedy-result.v1'
    ACTION_ID = 'SUPPLIER-A11'
    PREPARED_TYPE = PreparedSupplierRemedy
    RESULT_TABLE = 'supplier_remedy_results'
    WAIT_KIND = 'manual_supplier_remedy_result_review'
    EXECUTION_ERROR_CODE = 'supplier_remedy_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_remedy_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A11', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierRemedy

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        schemas = self.SOURCE_SCHEMAS()
        originals = {}
        # The parent first checks source shape, exact refs and duplicate rows.
        for row in sources:
            ref = Reference.model_validate(row['ref'])
            originals[ref.key()] = schemas.validate_projection(ref, row['projection'])
        validate_supplier_remedy_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A11 saved proposal is not an A03 quote, liability finding or native remedy receipt')
