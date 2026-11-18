"""Persist original OWN-A03 decisions without authorizing native investment."""
from dataclasses import dataclass

from integration.owner_investment_actions import PreparedOwnerInvestment, validate_owner_investment_sources
from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_investment_objects import owner_investment_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerInvestment(SavedOwnerObservation):
    """Own historical decision; native project and commitment evidence remain separate."""


class OwnerInvestmentResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-investment-result.v1'
    ACTION_ID = 'OWN-A03'
    PREPARED_TYPE = PreparedOwnerInvestment
    RESULT_TABLE = 'owner_investment_results'
    WAIT_KIND = 'manual_owner_investment_result_review'
    EXECUTION_ERROR_CODE = 'owner_investment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_investment_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A03'})
    SAVED_TYPE = SavedOwnerInvestment

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner investment lacks its complete original input source snapshots')
        validate_owner_investment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
