"""Persist original Contractor A09 decisions without recognizing claim entitlement."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_claim_actions import PreparedContractorClaim, validate_contractor_claim_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_claim_objects import contractor_claim_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorClaim(SavedContractorAmendment):
    """Own notice/proposal/response evidence; contract recognition remains separate."""


class ContractorClaimResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-claim-result.v1'
    ACTION_ID = 'CONTRACTOR-A09'
    PREPARED_TYPE = PreparedContractorClaim
    RESULT_TABLE = 'contractor_claim_results'
    WAIT_KIND = 'manual_contractor_claim_result_review'
    EXECUTION_ERROR_CODE = 'contractor_claim_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_claim_schemas)
    SAVED_TYPE = SavedContractorClaim

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved contract claim lacks complete original input source snapshots')
        validate_contractor_claim_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
