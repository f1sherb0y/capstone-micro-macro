"""Persist original Contractor A04 intentions without forming contracts."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_formation_actions import PreparedContractorFormation, validate_contractor_formation_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_formation_objects import contractor_formation_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorFormation(SavedContractorAmendment):
    """Own acceptance/revision/rejection evidence; contract effectiveness is separate."""


class ContractorFormationResultWorker(ContractorAmendmentResultWorker):
    """Reuse durable original snapshots, claim-once and result-first recovery."""
    SCHEMA = 'contractor-formation-result.v1'
    ACTION_ID = 'CONTRACTOR-A04'
    PREPARED_TYPE = PreparedContractorFormation
    RESULT_TABLE = 'contractor_formation_results'
    WAIT_KIND = 'manual_contractor_formation_result_review'
    EXECUTION_ERROR_CODE = 'contractor_formation_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_formation_schemas)
    SAVED_TYPE = SavedContractorFormation

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved contract formation lacks complete original input source snapshots')
        validate_contractor_formation_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
