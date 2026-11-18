"""Persist BANK-A13 original scenario advice without a financing offer or commitment."""
from dataclasses import dataclass

from integration.bank_advice_actions import PreparedBankAdvice, validate_advice_selection
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from src.actions.contracts.bank_advice_objects import bank_advice_schemas
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankAdvice(SavedBankIntake):
    """Original indicative opinion or decline, not a formal quotation or funds."""


class BankAdviceResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-advice-result.v1'
    ACTION_ID = 'BANK-A13'
    PREPARED_TYPE = PreparedBankAdvice
    RESULT_TABLE = 'bank_advice_results'
    WAIT_KIND = 'manual_bank_advice_result_review'
    EXECUTION_ERROR_CODE = 'bank_advice_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_advice_schemas)
    SAVED_TYPE = SavedBankAdvice
    READ_ACTION_IDS = frozenset({'BANK-A13'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved advice lacks an original selected input source')
        try:
            validate_advice_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved advice substitutes original lender, owner, brief or disclosed borrower identity') from error
