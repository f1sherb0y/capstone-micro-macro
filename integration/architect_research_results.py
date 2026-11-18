"""Persist original Architect A13 reports without creating further research or investment."""
from dataclasses import dataclass

from integration.architect_research_actions import PreparedArchitectResearch, validate_architect_research_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_research_objects import architect_research_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectResearch(SavedArchitectOpportunity):
    """Own finite research evidence; investigation, investment and approval stay separate."""


class ArchitectResearchResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-research-result.v1'
    ACTION_ID = 'ARCHITECT-A13'
    PREPARED_TYPE = PreparedArchitectResearch
    RESULT_TABLE = 'architect_research_results'
    WAIT_KIND = 'manual_architect_research_result_review'
    EXECUTION_ERROR_CODE = 'architect_research_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_research_schemas)
    SAVED_TYPE = SavedArchitectResearch

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect research lacks complete original input source snapshots')
        validate_architect_research_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
