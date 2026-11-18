"""Persist original Engineer A11 proposals while retaining rights and obligations."""
from dataclasses import dataclass

from integration.engineer_transition_actions import PreparedEngineerTransition, validate_engineer_transition_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.engineer_transition_objects import engineer_transition_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerTransition(SavedEngineerOpportunity):
    """Own transition evidence; resource, successor and debt effects stay separate."""


class EngineerTransitionResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-transition-result.v1'
    ACTION_ID = 'ENGINEER-A11'
    PREPARED_TYPE = PreparedEngineerTransition
    RESULT_TABLE = 'engineer_transition_results'
    WAIT_KIND = 'manual_engineer_transition_result_review'
    EXECUTION_ERROR_CODE = 'engineer_transition_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_transition_schemas)
    SAVED_TYPE = SavedEngineerTransition

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer transition lacks complete original input source snapshots')
        validate_engineer_transition_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
