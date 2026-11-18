"""Persist original Architect A05 design evidence without approval or investment effects."""
from dataclasses import dataclass

from integration.architect_design_actions import PreparedArchitectDesign, validate_architect_design_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_design_objects import architect_design_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectDesign(SavedArchitectOpportunity):
    """Own finite design result; submission and independent acceptance stay separate."""


class ArchitectDesignResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-design-result.v1'
    ACTION_ID = 'ARCHITECT-A05'
    PREPARED_TYPE = PreparedArchitectDesign
    RESULT_TABLE = 'architect_design_results'
    WAIT_KIND = 'manual_architect_design_result_review'
    EXECUTION_ERROR_CODE = 'architect_design_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_design_schemas)
    SAVED_TYPE = SavedArchitectDesign

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect design lacks complete original input source snapshots')
        validate_architect_design_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
