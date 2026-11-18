"""Persist original Engineer A03 decisions without creating service relationships."""
from dataclasses import dataclass

from integration.engineer_appointment_actions import PreparedEngineerAppointment, validate_engineer_appointment_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.engineer_appointment_objects import engineer_appointment_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerAppointment(SavedEngineerOpportunity):
    """Own confirmation evidence; relationship and reservation effects stay separate."""


class EngineerAppointmentResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-appointment-result.v1'
    ACTION_ID = 'ENGINEER-A03'
    PREPARED_TYPE = PreparedEngineerAppointment
    RESULT_TABLE = 'engineer_appointment_results'
    WAIT_KIND = 'manual_engineer_appointment_result_review'
    EXECUTION_ERROR_CODE = 'engineer_appointment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_appointment_schemas)
    SAVED_TYPE = SavedEngineerAppointment

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer appointment lacks complete original input source snapshots')
        validate_engineer_appointment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
