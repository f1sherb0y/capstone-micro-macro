"""Persist original Architect A03 decisions without creating service relationships."""
from dataclasses import dataclass

from integration.architect_appointment_actions import PreparedArchitectAppointment, validate_architect_appointment_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_appointment_objects import architect_appointment_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectAppointment(SavedArchitectOpportunity):
    """Own confirmation evidence; relationship and reservation effects stay separate."""


class ArchitectAppointmentResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-appointment-result.v1'
    ACTION_ID = 'ARCHITECT-A03'
    PREPARED_TYPE = PreparedArchitectAppointment
    RESULT_TABLE = 'architect_appointment_results'
    WAIT_KIND = 'manual_architect_appointment_result_review'
    EXECUTION_ERROR_CODE = 'architect_appointment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_appointment_schemas)
    SAVED_TYPE = SavedArchitectAppointment

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect appointment lacks complete original input source snapshots')
        validate_architect_appointment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
