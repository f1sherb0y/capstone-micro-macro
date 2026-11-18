"""Persist original OWN-A16 private proposal outcomes and source evidence."""
from dataclasses import dataclass

from integration.owner_observation_results import OwnerObservationResultWorker, SavedOwnerObservation
from integration.owner_proposal_actions import PreparedOwnerProposal, validate_owner_proposal_sources
from src.actions.contracts.common import ActionContext, walk_references
from integration.owner_observation_handoff import owner_observation_handoff_schemas
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedOwnerProposal(SavedOwnerObservation):
    """Original private briefs/no-proposal decision, not a project or investment."""


class OwnerProposalResultWorker(OwnerObservationResultWorker):
    """Reuse original persistent snapshots, claim-once and result-first recovery."""
    SCHEMA = 'owner-proposal-result.v1'
    ACTION_ID = 'OWN-A16'
    PREPARED_TYPE = PreparedOwnerProposal
    RESULT_TABLE = 'owner_proposal_results'
    WAIT_KIND = 'manual_owner_proposal_result_review'
    EXECUTION_ERROR_CODE = 'owner_proposal_execution_exception'
    SOURCE_SCHEMAS = staticmethod(owner_observation_handoff_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A16'})
    SAVED_TYPE = SavedOwnerProposal

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved owner proposal lacks complete original input source snapshots')
        validate_owner_proposal_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)
