"""Persist original Contractor A13 advice without authorizing consulting work."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_advice_actions import PreparedContractorAdvice, validate_contractor_advice_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_advice_objects import contractor_advice_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorAdvice(SavedContractorAmendment):
    """Own advisory evidence; service authority and actual fees remain separate."""


class ContractorAdviceResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-advice-result.v1'
    ACTION_ID = 'CONTRACTOR-A13'
    PREPARED_TYPE = PreparedContractorAdvice
    RESULT_TABLE = 'contractor_advice_results'
    WAIT_KIND = 'manual_contractor_advice_result_review'
    EXECUTION_ERROR_CODE = 'contractor_advice_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_advice_schemas)
    SAVED_TYPE = SavedContractorAdvice

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved contractor advice lacks complete original input source snapshots')
        validate_contractor_advice_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
