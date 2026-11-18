"""Persist original Contractor A05 intentions without work or supply effects."""
from dataclasses import dataclass

from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from integration.contractor_planning_actions import PreparedContractorPlanning, validate_contractor_planning_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_planning_objects import contractor_planning_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedContractorPlanning(SavedContractorAmendment):
    """Own plan/procurement evidence; formal orders, resources and work remain separate."""


class ContractorPlanningResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'contractor-planning-result.v1'
    ACTION_ID = 'CONTRACTOR-A05'
    PREPARED_TYPE = PreparedContractorPlanning
    RESULT_TABLE = 'contractor_planning_results'
    WAIT_KIND = 'manual_contractor_planning_result_review'
    EXECUTION_ERROR_CODE = 'contractor_planning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(contractor_planning_schemas)
    SAVED_TYPE = SavedContractorPlanning

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved work planning lacks complete original input source snapshots')
        validate_contractor_planning_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
