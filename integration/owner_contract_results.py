"""Persist original OWN-A11 decisions without changing contracts or issuing payments."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_contract_actions import PreparedOwnerContract, validate_owner_contract_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_contract_objects import owner_contract_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerContract(SavedOwnerObservation):
    """Own historical management decision; instructions, changes and payment effects remain separate."""


class OwnerContractResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-contract-result.v1'
    ACTION_ID = 'OWN-A11'
    PREPARED_TYPE = PreparedOwnerContract
    RESULT_TABLE = 'owner_contract_results'
    WAIT_KIND = 'manual_owner_contract_result_review'
    EXECUTION_ERROR_CODE = 'owner_contract_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_contract_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A11'})
    SAVED_TYPE = SavedOwnerContract

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner contract decision lacks its complete original input source snapshots')
        validate_owner_contract_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
