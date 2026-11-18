"""Persist original OWN-A06 decisions without issuing or repeating payments."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_payment_actions import PreparedOwnerPayment, validate_owner_payment_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_payment_objects import owner_payment_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerPayment(SavedOwnerObservation):
    """Original own instruction; native execution and settlement evidence remain separate."""


class OwnerPaymentResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-payment-result.v1'
    ACTION_ID = 'OWN-A06'
    PREPARED_TYPE = PreparedOwnerPayment
    RESULT_TABLE = 'owner_payment_results'
    WAIT_KIND = 'manual_owner_payment_result_review'
    EXECUTION_ERROR_CODE = 'owner_payment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_payment_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A06'})
    SAVED_TYPE = SavedOwnerPayment

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner payment lacks its complete original input source snapshots')
        validate_owner_payment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
