"""Persist BANK-A10 local resolutions without formal debt or legal effects."""
from dataclasses import dataclass

from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from integration.bank_resolution_actions import (
    PreparedBankResolution, validate_resolution_selection, validate_resolution_execution_history,
)
from src.actions.contracts.bank_resolution_objects import bank_resolution_schemas
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankResolution(SavedBankIntake):
    """Original local remedy/restructure/enforcement/writeoff decision, not formal execution."""


class BankResolutionResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-resolution-result.v1'
    ACTION_ID = 'BANK-A10'
    PREPARED_TYPE = PreparedBankResolution
    RESULT_TABLE = 'bank_resolution_results'
    WAIT_KIND = 'manual_bank_resolution_result_review'
    EXECUTION_ERROR_CODE = 'bank_resolution_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_resolution_schemas)
    SAVED_TYPE = SavedBankResolution
    READ_ACTION_IDS = frozenset({'BANK-A10'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved resolution lacks an original selected input source')
        try:
            validate_resolution_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
            validate_resolution_execution_history(action_input, organization_id=identity.organization_id, sources=originals)
        except ValueError as error:
            raise TaskConflict('Saved resolution substitutes original bank, facility, authority or remedy identity') from error
