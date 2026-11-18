"""Persist original OWN-A14 decisions without creating revenue or cash movements."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_asset_actions import PreparedOwnerAsset, validate_owner_asset_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_asset_objects import owner_asset_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerAsset(SavedOwnerObservation):
    """Own historical asset decision; forecasts, transactions and actual cash remain separate."""


class OwnerAssetResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-asset-result.v1'
    ACTION_ID = 'OWN-A14'
    PREPARED_TYPE = PreparedOwnerAsset
    RESULT_TABLE = 'owner_asset_results'
    WAIT_KIND = 'manual_owner_asset_result_review'
    EXECUTION_ERROR_CODE = 'owner_asset_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_asset_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A14'})
    SAVED_TYPE = SavedOwnerAsset

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner asset decision lacks its complete original input source snapshots')
        validate_owner_asset_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
