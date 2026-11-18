"""Persist original QS A01 decisions without preparation or service effects."""
from dataclasses import dataclass

from integration.qs_market_actions import PreparedQSMarket, validate_qs_market_sources
from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from src.actions.contracts.qs_market_objects import qs_market_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSMarket(SavedContractorAmendment):
    """Own discovery evidence; preparation and professional service authority stay separate."""


class QSMarketResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-market-result.v1'
    ACTION_ID = 'QS-A01'
    ROLE = 'QS'
    PREPARED_TYPE = PreparedQSMarket
    RESULT_TABLE = 'qs_market_results'
    WAIT_KIND = 'manual_qs_market_result_review'
    EXECUTION_ERROR_CODE = 'qs_market_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_market_schemas)
    SAVED_TYPE = SavedQSMarket

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS discovery lacks complete original input source snapshots')
        validate_qs_market_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
