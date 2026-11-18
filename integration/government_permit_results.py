"""Persist original Government A08 results without granting execution permission."""
from dataclasses import dataclass

from integration.government_permit_actions import PreparedGovernmentPermit, validate_government_permit_sources
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_permit_objects import government_permit_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentPermit(SavedGovernmentAdvice):
    """Own scoped condition result; core execution and permit effects stay separate."""


class GovernmentPermitResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-permit-result.v1'
    ACTION_ID = 'GOV-A08'
    PREPARED_TYPE = PreparedGovernmentPermit
    RESULT_TABLE = 'government_permit_results'
    WAIT_KIND = 'manual_government_permit_result_review'
    EXECUTION_ERROR_CODE = 'government_permit_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_permit_schemas)
    SAVED_TYPE = SavedGovernmentPermit

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government permit result lacks complete original input source snapshots')
        validate_government_permit_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
