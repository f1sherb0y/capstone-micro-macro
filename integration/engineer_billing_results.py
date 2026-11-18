"""Persist original Engineer A10 fee evidence without cash or billing effects."""
from dataclasses import dataclass

from integration.engineer_billing_actions import PreparedEngineerBilling, validate_engineer_billing_sources
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker, SavedEngineerOpportunity
from src.actions.contracts.engineer_billing_objects import engineer_billing_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedEngineerBilling(SavedEngineerOpportunity):
    """Own fee proposal evidence; receivable and cash effects stay independent."""


class EngineerBillingResultWorker(EngineerOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'engineer-billing-result.v1'
    ACTION_ID = 'ENGINEER-A10'
    PREPARED_TYPE = PreparedEngineerBilling
    RESULT_TABLE = 'engineer_billing_results'
    WAIT_KIND = 'manual_engineer_billing_result_review'
    EXECUTION_ERROR_CODE = 'engineer_billing_execution_exception'
    SOURCE_SCHEMAS = staticmethod(engineer_billing_schemas)
    SAVED_TYPE = SavedEngineerBilling

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Engineer billing lacks complete original input source snapshots')
        validate_engineer_billing_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
