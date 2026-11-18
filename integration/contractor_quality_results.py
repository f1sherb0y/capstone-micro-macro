"""Persist original Contractor A08 decisions without closing defects."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_quality_actions import PreparedContractorQuality, validate_contractor_quality_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_quality_objects import contractor_quality_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorQuality(SavedContractorAmendment):
    """Own inspection/remedy evidence; independent acceptance and defect closure are separate."""


class ContractorQualityResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-quality-result.v1'
    ACTION_ID = 'CONTRACTOR-A08'
    PREPARED_TYPE = PreparedContractorQuality
    RESULT_TABLE = 'contractor_quality_results'
    WAIT_KIND = 'manual_contractor_quality_result_review'
    EXECUTION_ERROR_CODE = 'contractor_quality_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_quality_schemas)
    SAVED_TYPE = SavedContractorQuality

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved inspection lacks complete original input source snapshots')
        validate_contractor_quality_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
