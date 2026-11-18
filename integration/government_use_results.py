"""Persist original Government A11 proposals without use permission or release effects."""
from dataclasses import dataclass

from integration.government_use_actions import PreparedGovernmentUse, validate_government_use_sources
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_use_objects import government_use_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentUse(SavedGovernmentAdvice):
    """Own use-specific proposal; signing, supervision and formal closure stay separate."""


class GovernmentUseResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-use-result.v1'
    ACTION_ID = 'GOV-A11'
    PREPARED_TYPE = PreparedGovernmentUse
    RESULT_TABLE = 'government_use_results'
    WAIT_KIND = 'manual_government_use_result_review'
    EXECUTION_ERROR_CODE = 'government_use_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_use_schemas)
    SAVED_TYPE = SavedGovernmentUse

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government use lacks complete original input source snapshots')
        validate_government_use_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
