"""Persist original Architect A06 interface evidence without author overrides."""
from dataclasses import dataclass

from integration.architect_integration_actions import PreparedArchitectIntegration, validate_architect_integration_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_integration_objects import architect_integration_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectIntegration(SavedArchitectOpportunity):
    """Own integration evidence; author acceptance and issue closure stay independent."""


class ArchitectIntegrationResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-integration-result.v1'
    ACTION_ID = 'ARCHITECT-A06'
    PREPARED_TYPE = PreparedArchitectIntegration
    RESULT_TABLE = 'architect_integration_results'
    WAIT_KIND = 'manual_architect_integration_result_review'
    EXECUTION_ERROR_CODE = 'architect_integration_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_integration_schemas)
    SAVED_TYPE = SavedArchitectIntegration

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect integration lacks complete original input source snapshots')
        validate_architect_integration_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
