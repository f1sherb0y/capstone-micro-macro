"""Persist original Government A07 drafts without signed IDs or permission effects."""
from dataclasses import dataclass

from integration.government_decision_actions import PreparedGovernmentDecision, validate_government_decision_sources
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_decision_objects import government_decision_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentDecision(SavedGovernmentAdvice):
    """Own authorized draft; the formal service supplies signed records and effects."""


class GovernmentDecisionResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-decision-result.v1'
    ACTION_ID = 'GOV-A07'
    PREPARED_TYPE = PreparedGovernmentDecision
    RESULT_TABLE = 'government_decision_results'
    WAIT_KIND = 'manual_government_decision_result_review'
    EXECUTION_ERROR_CODE = 'government_decision_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_decision_schemas)
    SAVED_TYPE = SavedGovernmentDecision

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government decision lacks complete original input source snapshots')
        validate_government_decision_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
