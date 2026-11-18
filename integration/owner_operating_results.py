"""Persist original OWN-A15 decisions without applying preferences, budgets or allocations."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_operating_actions import PreparedOwnerOperating, validate_owner_operating_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_operating_objects import owner_operating_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerOperating(SavedOwnerObservation):
    """Own historical operating decision; actual policy, learning and allocation effects remain separate."""


class OwnerOperatingResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-operating-result.v1'
    ACTION_ID = 'OWN-A15'
    PREPARED_TYPE = PreparedOwnerOperating
    RESULT_TABLE = 'owner_operating_results'
    WAIT_KIND = 'manual_owner_operating_result_review'
    EXECUTION_ERROR_CODE = 'owner_operating_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_operating_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A15'})
    SAVED_TYPE = SavedOwnerOperating

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner operating decision lacks its complete original input source snapshots')
        validate_owner_operating_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
