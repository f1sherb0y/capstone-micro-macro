"""Persist original Architect A12 evidence without applying learning or training."""
from dataclasses import dataclass

from integration.architect_learning_actions import PreparedArchitectLearning, validate_architect_learning_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_learning_objects import architect_learning_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectLearning(SavedArchitectOpportunity):
    """Own future-judgment evidence; capability and training effects stay independent."""


class ArchitectLearningResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-learning-result.v1'
    ACTION_ID = 'ARCHITECT-A12'
    PREPARED_TYPE = PreparedArchitectLearning
    RESULT_TABLE = 'architect_learning_results'
    WAIT_KIND = 'manual_architect_learning_result_review'
    EXECUTION_ERROR_CODE = 'architect_learning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_learning_schemas)
    SAVED_TYPE = SavedArchitectLearning

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect learning lacks complete original input source snapshots')
        validate_architect_learning_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
