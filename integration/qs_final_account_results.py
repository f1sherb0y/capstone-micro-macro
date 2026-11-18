"""Persist original QS A09 opinions without settlement or cash-clearance effects."""
from dataclasses import dataclass

from integration.qs_final_account_actions import PreparedQSFinalAccount, validate_qs_final_account_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_final_account_objects import qs_final_account_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSFinalAccount(SavedQSMarket):
    """Own final-account opinion; actual cash and unresolved duties remain separate."""


class QSFinalAccountResultWorker(QSMarketResultWorker):
    """Reuse durable original snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-final-account-result.v1'
    ACTION_ID = 'QS-A09'
    PREPARED_TYPE = PreparedQSFinalAccount
    RESULT_TABLE = 'qs_final_account_results'
    WAIT_KIND = 'manual_qs_final_account_result_review'
    EXECUTION_ERROR_CODE = 'qs_final_account_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_final_account_schemas)
    SAVED_TYPE = SavedQSFinalAccount

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS final account lacks complete original input source snapshots')
        validate_qs_final_account_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
