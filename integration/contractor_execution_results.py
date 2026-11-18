"""Persist original Contractor A07 decisions without engineering side effects."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_execution_actions import PreparedContractorExecution, validate_contractor_execution_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_execution_objects import contractor_execution_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorExecution(SavedContractorAmendment):
    """Own input/report/reconciliation evidence; actual engineering effects are separate."""


class ContractorExecutionResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-execution-result.v1'
    ACTION_ID = 'CONTRACTOR-A07'
    PREPARED_TYPE = PreparedContractorExecution
    RESULT_TABLE = 'contractor_execution_results'
    WAIT_KIND = 'manual_contractor_execution_result_review'
    EXECUTION_ERROR_CODE = 'contractor_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_execution_schemas)
    SAVED_TYPE = SavedContractorExecution

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved work execution lacks complete original input source snapshots')
        validate_contractor_execution_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
