"""Persist original Engineer A05 choices without design publication effects."""
from dataclasses import dataclass

from integration.engineer_design_actions import PreparedEngineerDesign, validate_engineer_design_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.engineer_design_objects import engineer_design_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerDesign(SavedEngineerOpportunity):
    """Own professional evidence; submission and independent acceptance stay separate."""


class EngineerDesignResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-design-result.v1'
    ACTION_ID = 'ENGINEER-A05'
    PREPARED_TYPE = PreparedEngineerDesign
    RESULT_TABLE = 'engineer_design_results'
    WAIT_KIND = 'manual_engineer_design_result_review'
    EXECUTION_ERROR_CODE = 'engineer_design_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_design_schemas)
    SAVED_TYPE = SavedEngineerDesign

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer design lacks complete original input source snapshots')
        validate_engineer_design_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
