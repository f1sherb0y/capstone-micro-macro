"""Persist original Architect A07 proposals without recording publication effects."""
from dataclasses import dataclass

from integration.architect_deliverable_actions import PreparedArchitectDeliverable, validate_architect_deliverable_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_submission_objects import architect_submission_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectDeliverable(SavedArchitectOpportunity):
    """Own submission proposal; receipt, review and use release stay independent."""


class ArchitectDeliverableResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-deliverable-result.v1'
    ACTION_ID = 'ARCHITECT-A07'
    PREPARED_TYPE = PreparedArchitectDeliverable
    RESULT_TABLE = 'architect_deliverable_results'
    WAIT_KIND = 'manual_architect_deliverable_result_review'
    EXECUTION_ERROR_CODE = 'architect_deliverable_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_submission_schemas)
    SAVED_TYPE = SavedArchitectDeliverable

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect submission lacks complete original input source snapshots')
        validate_architect_deliverable_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
