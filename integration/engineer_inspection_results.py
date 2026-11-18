"""Persist original Engineer A05 choices without actual observation or site command effects."""
from dataclasses import dataclass

from integration.engineer_inspection_actions import PreparedEngineerInspection, validate_engineer_inspection_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.engineer_inspection_objects import engineer_inspection_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerInspection(SavedEngineerOpportunity):
    """Own professional evidence; submission and independent acceptance stay separate."""


class EngineerInspectionResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-inspection-result.v1'
    ACTION_ID = 'ENGINEER-A08'
    PREPARED_TYPE = PreparedEngineerInspection
    RESULT_TABLE = 'engineer_inspection_results'
    WAIT_KIND = 'manual_engineer_inspection_result_review'
    EXECUTION_ERROR_CODE = 'engineer_inspection_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_inspection_schemas)
    SAVED_TYPE = SavedEngineerInspection

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer inspection lacks complete original input source snapshots')
        validate_engineer_inspection_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
