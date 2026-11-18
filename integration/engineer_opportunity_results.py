"""Persist original Engineer A01 decisions without preparation or service effects."""
from dataclasses import dataclass

from integration.engineer_opportunity_actions import PreparedEngineerOpportunity, validate_engineer_opportunity_sources
from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from src.actions.contracts.engineer_opportunity_objects import engineer_opportunity_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerOpportunity(SavedContractorAmendment):
    """Own discovery evidence; preparation and professional service authority stay separate."""


class EngineerOpportunityResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-opportunity-result.v1'
    ACTION_ID = 'ENGINEER-A01'
    ROLE = 'Engineer'
    PREPARED_TYPE = PreparedEngineerOpportunity
    RESULT_TABLE = 'engineer_opportunity_results'
    WAIT_KIND = 'manual_engineer_opportunity_result_review'
    EXECUTION_ERROR_CODE = 'engineer_opportunity_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_opportunity_schemas)
    SAVED_TYPE = SavedEngineerOpportunity

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer discovery lacks complete original input source snapshots')
        validate_engineer_opportunity_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
