"""Persist BANK-A05 evidence; formal arrangement and commitment remain host-owned."""
from dataclasses import dataclass

from integration.bank_arrangement_actions import PreparedBankArrangement, validate_arrangement_selection
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from integration.bank_quote_handoff import bank_quote_handoff_schemas
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankArrangement(SavedBankIntake):
    """Original local confirm/requote/decline, without formal finance effects."""


class BankArrangementResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-arrangement-result.v1'
    ACTION_ID = 'BANK-A05'
    PREPARED_TYPE = PreparedBankArrangement
    RESULT_TABLE = 'bank_arrangement_results'
    WAIT_KIND = 'manual_bank_arrangement_result_review'
    EXECUTION_ERROR_CODE = 'bank_arrangement_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_quote_handoff_schemas)
    SAVED_TYPE = SavedBankArrangement
    READ_ACTION_IDS = frozenset({'BANK-A05', 'BANK-A06'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved arrangement lacks an original selected input source')
        try:
            validate_arrangement_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved arrangement substitutes its original bank, offer, application or scope') from error
