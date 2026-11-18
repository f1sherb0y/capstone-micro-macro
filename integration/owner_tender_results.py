"""Persist original OWN-A09 decisions without publishing or awarding tenders."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_tender_actions import PreparedOwnerTender, validate_owner_tender_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_tender_objects import owner_tender_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerTender(SavedOwnerObservation):
    """Own historical procurement decision; publication, award and contract remain separate."""


class OwnerTenderResultWorker(OwnerObservationResultWorker):
    """Reuse durable snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-tender-result.v1'
    ACTION_ID = 'OWN-A09'
    PREPARED_TYPE = PreparedOwnerTender
    RESULT_TABLE = 'owner_tender_results'
    WAIT_KIND = 'manual_owner_tender_result_review'
    EXECUTION_ERROR_CODE = 'owner_tender_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_tender_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A09'})
    SAVED_TYPE = SavedOwnerTender

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner tender decision lacks its complete original input source snapshots')
        validate_owner_tender_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
