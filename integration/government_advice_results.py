"""Persist original Government A01 decisions without approval or permit effects."""
from dataclasses import dataclass

from integration.government_advice_actions import PreparedGovernmentAdvice, validate_government_advice_sources
from integration.contractor_amendment_results import ContractorAmendmentResultWorker, SavedContractorAmendment
from src.actions.contracts.government_advice_objects import government_advice_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedGovernmentAdvice(SavedContractorAmendment):
    """Own procedural advice; approval, permit and investment effects stay separate."""


class GovernmentAdviceResultWorker(ContractorAmendmentResultWorker):
    """Reuse original durable snapshots, claim-once and saved-result recovery."""
    SCHEMA = 'government-advice-result.v1'
    ACTION_ID = 'GOV-A01'
    ROLE = 'Government'
    PREPARED_TYPE = PreparedGovernmentAdvice
    RESULT_TABLE = 'government_advice_results'
    WAIT_KIND = 'manual_government_advice_result_review'
    EXECUTION_ERROR_CODE = 'government_advice_execution_exception'
    SOURCE_SCHEMAS = staticmethod(government_advice_schemas)
    SAVED_TYPE = SavedGovernmentAdvice

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved Government advice lacks complete original input source snapshots')
        validate_government_advice_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
