"""Persist original Architect A11 proposals while retaining rights and obligations."""
from dataclasses import dataclass

from integration.architect_transition_actions import PreparedArchitectTransition, validate_architect_transition_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_transition_objects import architect_transition_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectTransition(SavedArchitectOpportunity):
    """Own transition evidence; resource, successor and debt effects stay separate."""


class ArchitectTransitionResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-transition-result.v1'
    ACTION_ID = 'ARCHITECT-A11'
    PREPARED_TYPE = PreparedArchitectTransition
    RESULT_TABLE = 'architect_transition_results'
    WAIT_KIND = 'manual_architect_transition_result_review'
    EXECUTION_ERROR_CODE = 'architect_transition_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_transition_schemas)
    SAVED_TYPE = SavedArchitectTransition

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect transition lacks complete original input source snapshots')
        validate_architect_transition_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
