"""Persist original Architect A02 choices without appointment or capacity effects."""
from dataclasses import dataclass

from integration.architect_intake_actions import PreparedArchitectIntake, validate_architect_intake_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.service_objects import service_intake_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectIntake(SavedArchitectOpportunity):
    """Own service choice; counterpart acceptance and appointment stay separate."""


class ArchitectIntakeResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-intake-result.v1'
    ACTION_ID = 'ARCHITECT-A02'
    PREPARED_TYPE = PreparedArchitectIntake
    RESULT_TABLE = 'architect_intake_results'
    WAIT_KIND = 'manual_architect_intake_result_review'
    EXECUTION_ERROR_CODE = 'architect_intake_execution_exception'
    SOURCE_SCHEMAS = staticmethod(service_intake_schemas)
    SAVED_TYPE = SavedArchitectIntake

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect intake lacks complete original input source snapshots')
        validate_architect_intake_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
