"""Persist original Architect A09 support proposals without revising design or fee rights."""
from dataclasses import dataclass

from integration.architect_change_actions import PreparedArchitectChange, validate_architect_change_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_change_objects import architect_change_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectChange(SavedArchitectOpportunity):
    """Own design-support evidence; instruction, revision and fee effects stay separate."""


class ArchitectChangeResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-change-result.v1'
    ACTION_ID = 'ARCHITECT-A09'
    PREPARED_TYPE = PreparedArchitectChange
    RESULT_TABLE = 'architect_change_results'
    WAIT_KIND = 'manual_architect_change_result_review'
    EXECUTION_ERROR_CODE = 'architect_change_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_change_schemas)
    SAVED_TYPE = SavedArchitectChange

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect change lacks complete original input source snapshots')
        validate_architect_change_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
