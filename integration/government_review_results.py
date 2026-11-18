"""Persist original Government A04 opinions without signed decisions or permissions."""
from dataclasses import dataclass

from integration.government_review_actions import PreparedGovernmentReview, validate_government_review_sources
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_review_objects import government_review_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentReview(SavedGovernmentAdvice):
    """Own scoped review; formal decisions and condition satisfaction stay separate."""


class GovernmentReviewResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-review-result.v1'
    ACTION_ID = 'GOV-A04'
    PREPARED_TYPE = PreparedGovernmentReview
    RESULT_TABLE = 'government_review_results'
    WAIT_KIND = 'manual_government_review_result_review'
    EXECUTION_ERROR_CODE = 'government_review_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_review_schemas)
    SAVED_TYPE = SavedGovernmentReview

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government review lacks complete original input source snapshots')
        validate_government_review_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
