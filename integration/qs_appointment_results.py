"""Persist original QS A03 decisions without creating service relationships."""
from dataclasses import dataclass

from integration.qs_appointment_actions import PreparedQSAppointment, validate_qs_appointment_sources
from integration.qs_market_results import QSMarketResultWorker, SavedQSMarket
from src.actions.contracts.qs_appointment_objects import qs_appointment_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedQSAppointment(SavedQSMarket):
    """Own confirmation evidence; relationship and reservation effects stay separate."""


class QSAppointmentResultWorker(QSMarketResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'qs-appointment-result.v1'
    ACTION_ID = 'QS-A03'
    PREPARED_TYPE = PreparedQSAppointment
    RESULT_TABLE = 'qs_appointment_results'
    WAIT_KIND = 'manual_qs_appointment_result_review'
    EXECUTION_ERROR_CODE = 'qs_appointment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(qs_appointment_schemas)
    SAVED_TYPE = SavedQSAppointment

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved QS appointment lacks complete original input source snapshots')
        validate_qs_appointment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
