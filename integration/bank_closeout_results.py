"""Persist BANK-A11 local closure evidence without releasing actual finance obligations."""
from dataclasses import dataclass

from integration.bank_closeout_actions import (
    PreparedBankCloseout, validate_closeout_selection, validate_closeout_execution_history,
)
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from src.actions.contracts.bank_closeout_objects import bank_closeout_schemas
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankCloseout(SavedBankIntake):
    """Original local retain/close decision, not actual release or discharged debt."""


class BankCloseoutResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-closeout-result.v1'
    ACTION_ID = 'BANK-A11'
    PREPARED_TYPE = PreparedBankCloseout
    RESULT_TABLE = 'bank_closeout_results'
    WAIT_KIND = 'manual_bank_closeout_result_review'
    EXECUTION_ERROR_CODE = 'bank_closeout_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_closeout_schemas)
    SAVED_TYPE = SavedBankCloseout
    READ_ACTION_IDS = frozenset({'BANK-A11'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved closeout lacks an original selected input source')
        try:
            validate_closeout_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
            validate_closeout_execution_history(action_input, organization_id=identity.organization_id, sources=originals)
        except ValueError as error:
            raise TaskConflict('Saved closeout substitutes original bank, facility or remaining source identity') from error
