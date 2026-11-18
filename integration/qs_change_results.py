"""Persist original QS A07 valuations without recognition or payment effects."""
from dataclasses import dataclass

from integration.qs_change_actions import PreparedQSChange, validate_qs_change_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_change_objects import qs_change_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSChange(SavedQSMarket):
    """Own change valuation; formal rights, obligations and cash remain separate."""


class QSChangeResultWorker(QSMarketResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-change-result.v1'
    ACTION_ID = 'QS-A07'
    PREPARED_TYPE = PreparedQSChange
    RESULT_TABLE = 'qs_change_results'
    WAIT_KIND = 'manual_qs_change_result_review'
    EXECUTION_ERROR_CODE = 'qs_change_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_change_schemas)
    SAVED_TYPE = SavedQSChange

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS change lacks complete original input source snapshots')
        validate_qs_change_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
