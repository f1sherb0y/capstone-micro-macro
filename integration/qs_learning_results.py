"""Persist original QS A12 evidence without applying learning or training."""
from dataclasses import dataclass

from integration.qs_learning_actions import PreparedQSLearning, validate_qs_learning_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.qs_learning_objects import qs_learning_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSLearning(SavedQSMarket):
    """Own future-judgment evidence; capability and training effects stay independent."""


class QSLearningResultWorker(QSMarketResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-learning-result.v1'
    ACTION_ID = 'QS-A12'
    PREPARED_TYPE = PreparedQSLearning
    RESULT_TABLE = 'qs_learning_results'
    WAIT_KIND = 'manual_qs_learning_result_review'
    EXECUTION_ERROR_CODE = 'qs_learning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_learning_schemas)
    SAVED_TYPE = SavedQSLearning

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS learning lacks complete original input source snapshots')
        validate_qs_learning_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
