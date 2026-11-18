"""Persist original Architect A04 plans without allocations or actual work effects."""
from dataclasses import dataclass

from integration.architect_planning_actions import PreparedArchitectPlanning, validate_architect_planning_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_planning_objects import architect_planning_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectPlanning(SavedArchitectOpportunity):
    """Own planning evidence; allocation and recorded investment stay separate."""


class ArchitectPlanningResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-planning-result.v1'
    ACTION_ID = 'ARCHITECT-A04'
    PREPARED_TYPE = PreparedArchitectPlanning
    RESULT_TABLE = 'architect_planning_results'
    WAIT_KIND = 'manual_architect_planning_result_review'
    EXECUTION_ERROR_CODE = 'architect_planning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_planning_schemas)
    SAVED_TYPE = SavedArchitectPlanning

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect planning lacks complete original input source snapshots')
        validate_architect_planning_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
