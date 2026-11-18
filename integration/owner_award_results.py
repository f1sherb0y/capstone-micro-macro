"""Persist original OWN-A10 decisions without forming contracts or commitments."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_award_actions import PreparedOwnerAward, validate_owner_award_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_award_objects import owner_award_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerAward(SavedOwnerObservation):
    """Own historical award decision; independent acceptance and contract formation remain separate."""


class OwnerAwardResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-award-result.v1'
    ACTION_ID = 'OWN-A10'
    PREPARED_TYPE = PreparedOwnerAward
    RESULT_TABLE = 'owner_award_results'
    WAIT_KIND = 'manual_owner_award_result_review'
    EXECUTION_ERROR_CODE = 'owner_award_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_award_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A10'})
    SAVED_TYPE = SavedOwnerAward

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner award decision lacks its complete original input source snapshots')
        validate_owner_award_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
