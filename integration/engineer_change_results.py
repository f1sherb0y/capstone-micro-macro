"""Persist original Engineer A05 choices without revision or obligation discharge effects."""
from dataclasses import dataclass

from integration.engineer_change_actions import PreparedEngineerChange, validate_engineer_change_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.engineer_change_objects import engineer_change_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerChange(SavedEngineerOpportunity):
    """Own professional evidence; submission and independent acceptance stay separate."""


class EngineerChangeResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-change-result.v1'
    ACTION_ID = 'ENGINEER-A09'
    PREPARED_TYPE = PreparedEngineerChange
    RESULT_TABLE = 'engineer_change_results'
    WAIT_KIND = 'manual_engineer_change_result_review'
    EXECUTION_ERROR_CODE = 'engineer_change_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_change_schemas)
    SAVED_TYPE = SavedEngineerChange

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer change lacks complete original input source snapshots')
        validate_engineer_change_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
