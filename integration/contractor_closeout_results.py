"""Persist original Contractor A11 decisions without handover or settlement effects."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_closeout_actions import PreparedContractorCloseout, validate_contractor_closeout_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_closeout_objects import contractor_closeout_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorCloseout(SavedContractorAmendment):
    """Own handover/remedy/account evidence; acceptance and debt discharge are separate."""


class ContractorCloseoutResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-closeout-result.v1'
    ACTION_ID = 'CONTRACTOR-A11'
    PREPARED_TYPE = PreparedContractorCloseout
    RESULT_TABLE = 'contractor_closeout_results'
    WAIT_KIND = 'manual_contractor_closeout_result_review'
    EXECUTION_ERROR_CODE = 'contractor_closeout_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_closeout_schemas)
    SAVED_TYPE = SavedContractorCloseout

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved contractor closeout lacks complete original input source snapshots')
        validate_contractor_closeout_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
