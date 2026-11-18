"""Persist original QS A02 choices without budget approval or incurred cost effects."""
from dataclasses import dataclass

from integration.qs_cost_actions import PreparedQSCost, validate_qs_cost_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_cost_objects import qs_cost_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSCost(SavedQSMarket):
    """Own costing evidence; quantities, prices and budget approval stay separate."""


class QSCostResultWorker(QSMarketResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-cost-result.v1'
    ACTION_ID = 'QS-A04'
    PREPARED_TYPE = PreparedQSCost
    RESULT_TABLE = 'qs_cost_results'
    WAIT_KIND = 'manual_qs_cost_result_review'
    EXECUTION_ERROR_CODE = 'qs_cost_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_cost_schemas)
    SAVED_TYPE = SavedQSCost

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS cost lacks complete original input source snapshots')
        validate_qs_cost_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
