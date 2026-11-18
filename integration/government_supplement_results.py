"""Persist original Government A06 choices without formal issue or approval effects."""
from dataclasses import dataclass

from integration.government_supplement_actions import (
    PreparedGovernmentSupplement, validate_government_supplement_sources,
)
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_supplement_objects import government_supplement_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentSupplement(SavedGovernmentAdvice):
    """Own scoped supplement decision; formal issue and assignment effects stay separate."""


class GovernmentSupplementResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-supplement-result.v1'
    ACTION_ID = 'GOV-A06'
    PREPARED_TYPE = PreparedGovernmentSupplement
    RESULT_TABLE = 'government_supplement_results'
    WAIT_KIND = 'manual_government_supplement_result_review'
    EXECUTION_ERROR_CODE = 'government_supplement_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_supplement_schemas)
    SAVED_TYPE = SavedGovernmentSupplement

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government supplement lacks complete original input source snapshots')
        validate_government_supplement_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
