"""Persist original Government A09 choices without changing prior decision effects."""
from dataclasses import dataclass

from integration.government_transition_actions import (
    PreparedGovernmentTransition, validate_government_transition_sources,
)
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_transition_objects import government_transition_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentTransition(SavedGovernmentAdvice):
    """Own transition choice; actual formal changes, expiry and delivery stay separate."""


class GovernmentTransitionResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-transition-result.v1'
    ACTION_ID = 'GOV-A09'
    PREPARED_TYPE = PreparedGovernmentTransition
    RESULT_TABLE = 'government_transition_results'
    WAIT_KIND = 'manual_government_transition_result_review'
    EXECUTION_ERROR_CODE = 'government_transition_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_transition_schemas)
    SAVED_TYPE = SavedGovernmentTransition

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government transition lacks complete original input source snapshots')
        validate_government_transition_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
