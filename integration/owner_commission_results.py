"""Persist original OWN-A04 intentions without creating service appointments."""
from dataclasses import dataclass

from integration.owner_commission_actions import PreparedOwnerCommission, validate_owner_commission_sources
from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_commission_objects import owner_commission_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerCommission(SavedOwnerObservation):
    """Original own commission decision; actual appointment evidence is separate."""


class OwnerCommissionResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-commission-result.v1'
    ACTION_ID = 'OWN-A04'
    PREPARED_TYPE = PreparedOwnerCommission
    RESULT_TABLE = 'owner_commission_results'
    WAIT_KIND = 'manual_owner_commission_result_review'
    EXECUTION_ERROR_CODE = 'owner_commission_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_commission_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A04'})
    SAVED_TYPE = SavedOwnerCommission

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner commission lacks its complete original input source snapshots')
        validate_owner_commission_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
