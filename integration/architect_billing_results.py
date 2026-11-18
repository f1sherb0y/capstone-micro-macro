"""Persist original Architect A10 fee evidence without cash or billing effects."""
from dataclasses import dataclass

from integration.architect_billing_actions import PreparedArchitectBilling, validate_architect_billing_sources
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker, SavedArchitectOpportunity
from src.actions.contracts.architect_billing_objects import architect_billing_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedArchitectBilling(SavedArchitectOpportunity):
    """Own fee proposal evidence; receivable and cash effects stay independent."""


class ArchitectBillingResultWorker(ArchitectOpportunityResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'architect-billing-result.v1'
    ACTION_ID = 'ARCHITECT-A10'
    PREPARED_TYPE = PreparedArchitectBilling
    RESULT_TABLE = 'architect_billing_results'
    WAIT_KIND = 'manual_architect_billing_result_review'
    EXECUTION_ERROR_CODE = 'architect_billing_execution_exception'
    SOURCE_SCHEMAS = staticmethod(architect_billing_schemas)
    SAVED_TYPE = SavedArchitectBilling

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Architect billing lacks complete original input source snapshots')
        validate_architect_billing_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
