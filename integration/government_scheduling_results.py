"""Persist original Government A03 plans without assignments or reservations."""
from dataclasses import dataclass

from integration.government_scheduling_actions import (
    PreparedGovernmentScheduling, validate_government_scheduling_sources,
)
from integration.government_advice_results import GovernmentAdviceResultWorker, SavedGovernmentAdvice
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.government_scheduling_objects import government_scheduling_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentScheduling(SavedGovernmentAdvice):
    """Own scheduling decision; actual review work and occupancy stay separate."""


class GovernmentSchedulingResultWorker(GovernmentAdviceResultWorker):
    """Reuse durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-scheduling-result.v1'
    ACTION_ID = 'GOV-A03'
    PREPARED_TYPE = PreparedGovernmentScheduling
    RESULT_TABLE = 'government_scheduling_results'
    WAIT_KIND = 'manual_government_scheduling_result_review'
    EXECUTION_ERROR_CODE = 'government_scheduling_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_scheduling_schemas)
    SAVED_TYPE = SavedGovernmentScheduling

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government scheduling lacks complete original input source snapshots')
        validate_government_scheduling_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
