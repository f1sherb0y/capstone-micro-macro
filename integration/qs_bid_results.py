"""Persist original QS A06 evaluations without exclusion or award effects."""
from dataclasses import dataclass

from integration.qs_bid_actions import PreparedQSBid, validate_qs_bid_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_bid_objects import qs_bid_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSBid(SavedQSMarket):
    """Own bid evaluation; bidder prices and buyer decisions remain separate."""


class QSBidResultWorker(QSMarketResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-bid-result.v1'
    ACTION_ID = 'QS-A06'
    PREPARED_TYPE = PreparedQSBid
    RESULT_TABLE = 'qs_bid_results'
    WAIT_KIND = 'manual_qs_bid_result_review'
    EXECUTION_ERROR_CODE = 'qs_bid_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_bid_schemas)
    SAVED_TYPE = SavedQSBid

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS bid lacks complete original input source snapshots')
        validate_qs_bid_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
