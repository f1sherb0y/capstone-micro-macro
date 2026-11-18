"""Save BANK-A04 local quotation evidence without formal offers or reservations."""
from dataclasses import dataclass

from integration.bank_credit_handoff import bank_credit_handoff_schemas
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from integration.bank_quote_actions import PreparedBankQuote, validate_quote_selection
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankQuote(SavedBankIntake):
    """Historical local terms or decline; completed is not a registered offer."""


class BankQuoteResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-quote-result.v1'
    ACTION_ID = 'BANK-A04'
    PREPARED_TYPE = PreparedBankQuote
    RESULT_TABLE = 'bank_quote_results'
    WAIT_KIND = 'manual_bank_quote_result_review'
    EXECUTION_ERROR_CODE = 'bank_quote_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_credit_handoff_schemas)
    SAVED_TYPE = SavedBankQuote
    READ_ACTION_IDS = frozenset({'BANK-A04', 'BANK-A05'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved quote lacks an original selected input source')
        try:
            validate_quote_selection(action_input, run_id=identity.run_id, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved quote substitutes its original run, bank, application, assessment or authority') from error
