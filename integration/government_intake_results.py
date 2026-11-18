"""Persist original Government A02 intake choices without formal case effects."""
from dataclasses import dataclass

from integration.government_intake_actions import PreparedGovernmentIntake, validate_government_intake_sources
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_objects import government_intake_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentIntake(SavedGovernmentAdvice):
    """Own intake decision; case registration, receipts and permits stay separate."""


class GovernmentIntakeResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-intake-result.v1'
    ACTION_ID = 'GOV-A02'
    PREPARED_TYPE = PreparedGovernmentIntake
    RESULT_TABLE = 'government_intake_results'
    WAIT_KIND = 'manual_government_intake_result_review'
    EXECUTION_ERROR_CODE = 'government_intake_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_intake_schemas)
    SAVED_TYPE = SavedGovernmentIntake

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government intake lacks complete original input source snapshots')
        validate_government_intake_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
