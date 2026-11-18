"""Persist original QS A13 comparisons without research-spending or approval effects."""
from dataclasses import dataclass

from integration.qs_research_actions import PreparedQSResearch, validate_qs_research_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_research_objects import qs_research_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSResearch(SavedQSMarket):
    """Own preliminary comparison; spending and investment effects stay separate."""


class QSResearchResultWorker(QSMarketResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-research-result.v1'
    ACTION_ID = 'QS-A13'
    PREPARED_TYPE = PreparedQSResearch
    RESULT_TABLE = 'qs_research_results'
    WAIT_KIND = 'manual_qs_research_result_review'
    EXECUTION_ERROR_CODE = 'qs_research_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_research_schemas)
    SAVED_TYPE = SavedQSResearch

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS research lacks complete original input source snapshots')
        validate_qs_research_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
