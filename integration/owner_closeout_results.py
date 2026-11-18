"""Persist original OWN-A12 decisions without recording acceptance or payment."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_closeout_actions import PreparedOwnerCloseout, validate_owner_closeout_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_closeout_objects import owner_closeout_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerCloseout(SavedOwnerObservation):
    """Own historical closeout decision; acceptance, use rights and payment remain separate."""


class OwnerCloseoutResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-closeout-result.v1'
    ACTION_ID = 'OWN-A12'
    PREPARED_TYPE = PreparedOwnerCloseout
    RESULT_TABLE = 'owner_closeout_results'
    WAIT_KIND = 'manual_owner_closeout_result_review'
    EXECUTION_ERROR_CODE = 'owner_closeout_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_closeout_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A12'})
    SAVED_TYPE = SavedOwnerCloseout

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner closeout decision lacks its complete original input source snapshots')
        validate_owner_closeout_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
