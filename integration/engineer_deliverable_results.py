"""Persist original Engineer A07 proposals without recording publication effects."""
from dataclasses import dataclass

from integration.engineer_deliverable_actions import PreparedEngineerDeliverable, validate_engineer_deliverable_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.engineer_submission_objects import engineer_submission_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerDeliverable(SavedEngineerOpportunity):
    """Own submission proposal; receipt, review and use release stay independent."""


class EngineerDeliverableResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-deliverable-result.v1'
    ACTION_ID = 'ENGINEER-A07'
    PREPARED_TYPE = PreparedEngineerDeliverable
    RESULT_TABLE = 'engineer_deliverable_results'
    WAIT_KIND = 'manual_engineer_deliverable_result_review'
    EXECUTION_ERROR_CODE = 'engineer_deliverable_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_submission_schemas)
    SAVED_TYPE = SavedEngineerDeliverable

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer submission lacks complete original input source snapshots')
        validate_engineer_deliverable_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
