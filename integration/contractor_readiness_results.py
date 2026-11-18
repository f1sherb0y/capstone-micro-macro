"""Persist original Contractor A06 decisions without granting task release."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_readiness_actions import PreparedContractorReadiness, validate_contractor_readiness_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_readiness_objects import contractor_readiness_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorReadiness(SavedContractorAmendment):
    """Own readiness evidence; core release and actual work remain separate."""


class ContractorReadinessResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-readiness-result.v1'
    ACTION_ID = 'CONTRACTOR-A06'
    PREPARED_TYPE = PreparedContractorReadiness
    RESULT_TABLE = 'contractor_readiness_results'
    WAIT_KIND = 'manual_contractor_readiness_result_review'
    EXECUTION_ERROR_CODE = 'contractor_readiness_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_readiness_schemas)
    SAVED_TYPE = SavedContractorReadiness

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved task readiness lacks complete original input source snapshots')
        validate_contractor_readiness_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
