"""Persist original QS A10 fee evidence without cash or billing effects."""
from dataclasses import dataclass

from integration.qs_billing_actions import PreparedQSBilling, validate_qs_billing_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.qs_billing_objects import qs_billing_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSBilling(SavedQSMarket):
    """Own fee proposal evidence; receivable and cash effects stay independent."""


class QSBillingResultWorker(QSMarketResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-billing-result.v1'
    ACTION_ID = 'QS-A10'
    PREPARED_TYPE = PreparedQSBilling
    RESULT_TABLE = 'qs_billing_results'
    WAIT_KIND = 'manual_qs_billing_result_review'
    EXECUTION_ERROR_CODE = 'qs_billing_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_billing_schemas)
    SAVED_TYPE = SavedQSBilling

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS billing lacks complete original input source snapshots')
        validate_qs_billing_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
