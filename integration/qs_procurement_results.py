"""Persist original QS A05 decisions without publication or approval effects."""
from dataclasses import dataclass

from integration.qs_procurement_actions import PreparedQSProcurement, validate_qs_procurement_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_procurement_objects import qs_procurement_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSProcurement(SavedQSMarket):
    """Own procurement decision; actual document registration remains separate."""


class QSProcurementResultWorker(QSMarketResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-procurement-result.v1'
    ACTION_ID = 'QS-A05'
    PREPARED_TYPE = PreparedQSProcurement
    RESULT_TABLE = 'qs_procurement_results'
    WAIT_KIND = 'manual_qs_procurement_result_review'
    EXECUTION_ERROR_CODE = 'qs_procurement_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_procurement_schemas)
    SAVED_TYPE = SavedQSProcurement

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS procurement lacks complete original input source snapshots')
        validate_qs_procurement_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)

    def prepare_document(self, identity, *, current_context, reading, execution_versions,
            validate_history, document_ref, author_authority_ref):
        """Derive a document only from the original persisted compile output."""
        from integration.qs_procurement_documents import prepare_saved_procurement_document

        return prepare_saved_procurement_document(worker=self, identity=identity,
            current_context=current_context, reading=reading, execution_versions=execution_versions,
            validate_history=validate_history, document_ref=document_ref,
            author_authority_ref=author_authority_ref)
