"""Persist original Engineer A04 plans without allocations or actual work effects."""
from dataclasses import dataclass

from integration.engineer_planning_actions import PreparedEngineerPlanning, validate_engineer_planning_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.engineer_planning_objects import engineer_planning_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerPlanning(SavedEngineerOpportunity):
    """Own planning evidence; allocation and recorded investment stay separate."""


class EngineerPlanningResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-planning-result.v1'
    ACTION_ID = 'ENGINEER-A04'
    PREPARED_TYPE = PreparedEngineerPlanning
    RESULT_TABLE = 'engineer_planning_results'
    WAIT_KIND = 'manual_engineer_planning_result_review'
    EXECUTION_ERROR_CODE = 'engineer_planning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_planning_schemas)
    SAVED_TYPE = SavedEngineerPlanning

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer planning lacks complete original input source snapshots')
        validate_engineer_planning_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
