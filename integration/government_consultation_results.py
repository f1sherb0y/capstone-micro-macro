"""Persist original Government A05 consultation choices without delivery effects."""
from dataclasses import dataclass

from integration.government_consultation_actions import (
    PreparedGovernmentConsultation, validate_government_consultation_sources,
)
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_consultation_objects import government_consultation_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentConsultation(SavedGovernmentAdvice):
    """Own procedural choice; actual disclosure, registration and opinions stay separate."""


class GovernmentConsultationResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-consultation-result.v1'
    ACTION_ID = 'GOV-A05'
    PREPARED_TYPE = PreparedGovernmentConsultation
    RESULT_TABLE = 'government_consultation_results'
    WAIT_KIND = 'manual_government_consultation_result_review'
    EXECUTION_ERROR_CODE = 'government_consultation_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_consultation_schemas)
    SAVED_TYPE = SavedGovernmentConsultation

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government consultation lacks complete original input source snapshots')
        validate_government_consultation_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
