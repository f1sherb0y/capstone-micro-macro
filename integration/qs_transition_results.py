"""Persist original QS A11 proposals while retaining rights and obligations."""
from dataclasses import dataclass

from integration.qs_transition_actions import PreparedQSTransition, validate_qs_transition_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.qs_transition_objects import qs_transition_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSTransition(SavedQSMarket):
    """Own transition evidence; resource, successor and debt effects stay separate."""


class QSTransitionResultWorker(QSMarketResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-transition-result.v1'
    ACTION_ID = 'QS-A11'
    PREPARED_TYPE = PreparedQSTransition
    RESULT_TABLE = 'qs_transition_results'
    WAIT_KIND = 'manual_qs_transition_result_review'
    EXECUTION_ERROR_CODE = 'qs_transition_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_transition_schemas)
    SAVED_TYPE = SavedQSTransition

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS transition lacks complete original input source snapshots')
        validate_qs_transition_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
