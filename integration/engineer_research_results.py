"""Persist original Engineer A13 reports without creating further research or investment."""
from dataclasses import dataclass

from integration.engineer_research_actions import PreparedEngineerResearch, validate_engineer_research_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.engineer_research_objects import engineer_research_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerResearch(SavedEngineerOpportunity):
    """Own finite research evidence; investigation, investment and approval stay separate."""


class EngineerResearchResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-research-result.v1'
    ACTION_ID = 'ENGINEER-A13'
    PREPARED_TYPE = PreparedEngineerResearch
    RESULT_TABLE = 'engineer_research_results'
    WAIT_KIND = 'manual_engineer_research_result_review'
    EXECUTION_ERROR_CODE = 'engineer_research_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_research_schemas)
    SAVED_TYPE = SavedEngineerResearch

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer research lacks complete original input source snapshots')
        validate_engineer_research_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
