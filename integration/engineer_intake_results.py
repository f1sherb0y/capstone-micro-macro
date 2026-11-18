"""Persist original Engineer A02 choices without appointment or capacity effects."""
from dataclasses import dataclass

from integration.engineer_intake_actions import PreparedEngineerIntake, validate_engineer_intake_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.engineer_objects import engineer_intake_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerIntake(SavedEngineerOpportunity):
    """Own service choice; counterpart acceptance and appointment stay separate."""


class EngineerIntakeResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-intake-result.v1'
    ACTION_ID = 'ENGINEER-A02'
    PREPARED_TYPE = PreparedEngineerIntake
    RESULT_TABLE = 'engineer_intake_results'
    WAIT_KIND = 'manual_engineer_intake_result_review'
    EXECUTION_ERROR_CODE = 'engineer_intake_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_intake_schemas)
    SAVED_TYPE = SavedEngineerIntake

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer intake lacks complete original input source snapshots')
        validate_engineer_intake_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
