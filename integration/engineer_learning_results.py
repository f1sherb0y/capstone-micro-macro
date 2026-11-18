"""Persist original Engineer A12 evidence without applying learning or training."""
from dataclasses import dataclass

from integration.engineer_learning_actions import PreparedEngineerLearning, validate_engineer_learning_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.engineer_learning_objects import engineer_learning_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerLearning(SavedEngineerOpportunity):
    """Own future-judgment evidence; capability and training effects stay independent."""


class EngineerLearningResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-learning-result.v1'
    ACTION_ID = 'ENGINEER-A12'
    PREPARED_TYPE = PreparedEngineerLearning
    RESULT_TABLE = 'engineer_learning_results'
    WAIT_KIND = 'manual_engineer_learning_result_review'
    EXECUTION_ERROR_CODE = 'engineer_learning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_learning_schemas)
    SAVED_TYPE = SavedEngineerLearning

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer learning lacks complete original input source snapshots')
        validate_engineer_learning_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
