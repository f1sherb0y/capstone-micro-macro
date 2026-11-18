"""Persist original OWN-A05 funding decisions without establishing financing."""
from dataclasses import dataclass

from integration.owner_financing_actions import PreparedOwnerFinancing, validate_owner_financing_sources
from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_financing_objects import owner_financing_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerFinancing(SavedOwnerObservation):
    """Own historical funding decision; actual financial records remain separate."""


class OwnerFinancingResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-financing-result.v1'
    ACTION_ID = 'OWN-A05'
    PREPARED_TYPE = PreparedOwnerFinancing
    RESULT_TABLE = 'owner_financing_results'
    WAIT_KIND = 'manual_owner_financing_result_review'
    EXECUTION_ERROR_CODE = 'owner_financing_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_financing_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A05'})
    SAVED_TYPE = SavedOwnerFinancing

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner financing lacks its complete original input source snapshots')
        validate_owner_financing_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
