"""Persist original OWN-A02 bounded study decisions without commissioning work."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_study_actions import PreparedOwnerStudy, validate_owner_study_sources
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.owner_study_objects import owner_study_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerStudy(SavedOwnerObservation):
    """Own historical intention; not an actual study task, order or incurred cost."""


class OwnerStudyResultWorker(OwnerObservationResultWorker):
    """Reuse original snapshots, claim-once persistence and explicit recovery."""
    SCHEMA = 'owner-study-result.v1'
    ACTION_ID = 'OWN-A02'
    PREPARED_TYPE = PreparedOwnerStudy
    RESULT_TABLE = 'owner_study_results'
    WAIT_KIND = 'manual_owner_study_result_review'
    EXECUTION_ERROR_CODE = 'owner_study_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_study_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A02'})
    SAVED_TYPE = SavedOwnerStudy

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner study lacks its complete original input source snapshots')
        validate_owner_study_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
