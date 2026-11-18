"""Save original BANK-A09 evidence without debt, cash or posting mutations."""
from dataclasses import dataclass

from integration.bank_debt_actions import PreparedBankDebt, validate_debt_selection
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from src.actions.contracts.bank_debt_objects import bank_debt_schemas
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankDebt(SavedBankIntake):
    """Original local due/allocation/reconciliation/correction, not a posted ledger."""


class BankDebtResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-debt-result.v1'
    ACTION_ID = 'BANK-A09'
    PREPARED_TYPE = PreparedBankDebt
    RESULT_TABLE = 'bank_debt_results'
    WAIT_KIND = 'manual_bank_debt_result_review'
    EXECUTION_ERROR_CODE = 'bank_debt_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_debt_schemas)
    SAVED_TYPE = SavedBankDebt
    READ_ACTION_IDS = frozenset({'BANK-A09'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved debt decision lacks an original selected input source')
        try:
            validate_debt_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved debt decision substitutes original lender, facility, debt or receipt identity') from error
