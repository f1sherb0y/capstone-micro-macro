"""Persist original OWN-A08 decisions without submitting regulatory applications."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_regulatory_actions import PreparedOwnerRegulatory, validate_owner_regulatory_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_regulatory_objects import owner_regulatory_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerRegulatory(SavedOwnerObservation):
    """Own historical application/response decision; formal receipt and permit remain separate."""


class OwnerRegulatoryResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-regulatory-result.v1'
    ACTION_ID = 'OWN-A08'
    PREPARED_TYPE = PreparedOwnerRegulatory
    RESULT_TABLE = 'owner_regulatory_results'
    WAIT_KIND = 'manual_owner_regulatory_result_review'
    EXECUTION_ERROR_CODE = 'owner_regulatory_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_regulatory_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A08'})
    SAVED_TYPE = SavedOwnerRegulatory

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner regulatory decision lacks its complete original input source snapshots')
        validate_owner_regulatory_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
