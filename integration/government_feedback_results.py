"""Persist original Government A12 choices without applying policies or assignments."""
from dataclasses import dataclass

from integration.government_feedback_actions import PreparedGovernmentFeedback, validate_government_feedback_sources
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_feedback_objects import government_feedback_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentFeedback(SavedGovernmentAdvice):
    """Own observed feedback choice; formal policy, task and assignment effects stay separate."""


class GovernmentFeedbackResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-feedback-result.v1'
    ACTION_ID = 'GOV-A12'
    PREPARED_TYPE = PreparedGovernmentFeedback
    RESULT_TABLE = 'government_feedback_results'
    WAIT_KIND = 'manual_government_feedback_result_review'
    EXECUTION_ERROR_CODE = 'government_feedback_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_feedback_schemas)
    SAVED_TYPE = SavedGovernmentFeedback

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government feedback lacks complete original input source snapshots')
        validate_government_feedback_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
