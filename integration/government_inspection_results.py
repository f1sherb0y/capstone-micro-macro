"""Persist original Government A10 results without formal measures or remedy effects."""
from dataclasses import dataclass

from integration.government_inspection_actions import (
    PreparedGovernmentInspection, validate_government_inspection_sources,
)
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_inspection_objects import government_inspection_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentInspection(SavedGovernmentAdvice):
    """Own scoped inspection choice; actual work, measures and issue updates stay separate."""


class GovernmentInspectionResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-inspection-result.v1'
    ACTION_ID = 'GOV-A10'
    PREPARED_TYPE = PreparedGovernmentInspection
    RESULT_TABLE = 'government_inspection_results'
    WAIT_KIND = 'manual_government_inspection_result_review'
    EXECUTION_ERROR_CODE = 'government_inspection_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_inspection_schemas)
    SAVED_TYPE = SavedGovernmentInspection

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government inspection lacks complete original input source snapshots')
        validate_government_inspection_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
