"""Persist original Engineer A05 choices without approval or target content effects."""
from dataclasses import dataclass

from integration.engineer_review_actions import PreparedEngineerReview, validate_engineer_review_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.engineer_review_objects import engineer_review_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerReview(SavedEngineerOpportunity):
    """Own professional evidence; submission and independent acceptance stay separate."""


class EngineerReviewResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-review-result.v1'
    ACTION_ID = 'ENGINEER-A06'
    PREPARED_TYPE = PreparedEngineerReview
    RESULT_TABLE = 'engineer_review_results'
    WAIT_KIND = 'manual_engineer_review_result_review'
    EXECUTION_ERROR_CODE = 'engineer_review_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_review_schemas)
    SAVED_TYPE = SavedEngineerReview

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer review lacks complete original input source snapshots')
        validate_engineer_review_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
