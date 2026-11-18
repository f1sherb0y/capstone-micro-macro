"""Persist original Contractor A10 decisions without posting measured work or cash."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_payment_actions import PreparedContractorPayment, validate_contractor_payment_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_payment_objects import contractor_payment_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorPayment(SavedContractorAmendment):
    """Own measurement/payment evidence; certification, debt and cash remain separate."""


class ContractorPaymentResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-payment-result.v1'
    ACTION_ID = 'CONTRACTOR-A10'
    PREPARED_TYPE = PreparedContractorPayment
    RESULT_TABLE = 'contractor_payment_results'
    WAIT_KIND = 'manual_contractor_payment_result_review'
    EXECUTION_ERROR_CODE = 'contractor_payment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_payment_schemas)
    SAVED_TYPE = SavedContractorPayment

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved contractor payment lacks complete original input source snapshots')
        validate_contractor_payment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
