"""Persist original Architect A01 decisions without preparation or appointment effects."""
from dataclasses import dataclass

from integration.architect_opportunity_actions import PreparedArchitectOpportunity, validate_architect_opportunity_sources
from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from src.actions.contracts.architect_opportunity_objects import architect_opportunity_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectOpportunity(SavedContractorAmendment):
    """Own discovery evidence; a saved intention does not create service authority."""


class ArchitectOpportunityResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-opportunity-result.v1'
    ACTION_ID = 'ARCHITECT-A01'
    ROLE = 'Architect'
    PREPARED_TYPE = PreparedArchitectOpportunity
    RESULT_TABLE = 'architect_opportunity_results'
    WAIT_KIND = 'manual_architect_opportunity_result_review'
    EXECUTION_ERROR_CODE = 'architect_opportunity_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_opportunity_schemas)
    SAVED_TYPE = SavedArchitectOpportunity

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect discovery lacks complete original input source snapshots')
        validate_architect_opportunity_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
