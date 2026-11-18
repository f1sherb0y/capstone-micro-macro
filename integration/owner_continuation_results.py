"""Persist original OWN-A13 decisions without releasing resources or clearing debt."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_continuation_actions import PreparedOwnerContinuation, validate_owner_continuation_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_continuation_objects import owner_continuation_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerContinuation(SavedOwnerObservation):
    """Own historical transition decision; state changes, releases and debt clearance remain separate."""


class OwnerContinuationResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-continuation-result.v1'
    ACTION_ID = 'OWN-A13'
    PREPARED_TYPE = PreparedOwnerContinuation
    RESULT_TABLE = 'owner_continuation_results'
    WAIT_KIND = 'manual_owner_continuation_result_review'
    EXECUTION_ERROR_CODE = 'owner_continuation_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_continuation_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A13'})
    SAVED_TYPE = SavedOwnerContinuation

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner continuation decision lacks its complete original input source snapshots')
        validate_owner_continuation_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
