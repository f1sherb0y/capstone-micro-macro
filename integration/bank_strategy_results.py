"""Save original BANK-A01 strategy evidence without portfolio or contract mutations."""
from dataclasses import dataclass

from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from integration.bank_strategy_actions import PreparedBankStrategy, validate_strategy_selection
from src.actions.contracts.bank_strategy_objects import bank_strategy_schemas
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankStrategy(SavedBankIntake):
    """Original local strategy or investigation proposal, not an applied policy or loan."""


class BankStrategyResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-strategy-result.v1'
    ACTION_ID = 'BANK-A01'
    PREPARED_TYPE = PreparedBankStrategy
    RESULT_TABLE = 'bank_strategy_results'
    WAIT_KIND = 'manual_bank_strategy_result_review'
    EXECUTION_ERROR_CODE = 'bank_strategy_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_strategy_schemas)
    SAVED_TYPE = SavedBankStrategy
    READ_ACTION_IDS = frozenset({'BANK-A01'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved strategy decision lacks an original selected input source')
        try:
            validate_strategy_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved strategy substitutes original bank, portfolio, capacity or signal identity') from error
