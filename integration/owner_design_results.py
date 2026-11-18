"""Persist original OWN-A07 decisions without releasing design or construction use."""
from dataclasses import dataclass

from integration.owner_design_actions import PreparedOwnerDesign, validate_owner_design_sources
from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_design_objects import owner_design_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerDesign(SavedOwnerObservation):
    """Own historical decision; actual acceptance and allowed use require separate evidence."""


class OwnerDesignResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-design-result.v1'
    ACTION_ID = 'OWN-A07'
    PREPARED_TYPE = PreparedOwnerDesign
    RESULT_TABLE = 'owner_design_results'
    WAIT_KIND = 'manual_owner_design_result_review'
    EXECUTION_ERROR_CODE = 'owner_design_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_design_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A07'})
    SAVED_TYPE = SavedOwnerDesign

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner design lacks its complete original input source snapshots')
        validate_owner_design_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
