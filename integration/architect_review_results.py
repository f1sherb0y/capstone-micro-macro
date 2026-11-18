"""Persist original Architect A08 review evidence without approval or content edits."""
from dataclasses import dataclass

from integration.architect_review_actions import PreparedArchitectReview, validate_architect_review_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_review_objects import architect_review_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectReview(SavedArchitectOpportunity):
    """Own review/response evidence; revised content and approval stay independent."""


class ArchitectReviewResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-review-result.v1'
    ACTION_ID = 'ARCHITECT-A08'
    PREPARED_TYPE = PreparedArchitectReview
    RESULT_TABLE = 'architect_review_results'
    WAIT_KIND = 'manual_architect_review_result_review'
    EXECUTION_ERROR_CODE = 'architect_review_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_review_schemas)
    SAVED_TYPE = SavedArchitectReview

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect review lacks complete original input source snapshots')
        validate_architect_review_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
