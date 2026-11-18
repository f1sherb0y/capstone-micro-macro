"""Persist original QS A02 choices without appointment or capacity effects."""
from dataclasses import dataclass

from integration.qs_intake_actions import PreparedQSIntake, validate_qs_intake_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.qs_objects import qs_intake_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSIntake(SavedQSMarket):
    """Own service choice; counterpart acceptance and appointment stay separate."""


class QSIntakeResultWorker(QSMarketResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-intake-result.v1'
    ACTION_ID = 'QS-A02'
    PREPARED_TYPE = PreparedQSIntake
    RESULT_TABLE = 'qs_intake_results'
    WAIT_KIND = 'manual_qs_intake_result_review'
    EXECUTION_ERROR_CODE = 'qs_intake_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_intake_schemas)
    SAVED_TYPE = SavedQSIntake

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS intake lacks complete original input source snapshots')
        validate_qs_intake_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
