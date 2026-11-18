"""Persist original QS A08 decisions without certificate or cash effects."""
from dataclasses import dataclass

from integration.qs_payment_actions import PreparedQSPayment, validate_qs_payment_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_payment_objects import qs_payment_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSPayment(SavedQSMarket):
    """Own payment valuation; formal certificates and received cash stay separate."""


class QSPaymentResultWorker(QSMarketResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-payment-result.v1'
    ACTION_ID = 'QS-A08'
    PREPARED_TYPE = PreparedQSPayment
    RESULT_TABLE = 'qs_payment_results'
    WAIT_KIND = 'manual_qs_payment_result_review'
    EXECUTION_ERROR_CODE = 'qs_payment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_payment_schemas)
    SAVED_TYPE = SavedQSPayment

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS payment lacks complete original input source snapshots')
        validate_qs_payment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
