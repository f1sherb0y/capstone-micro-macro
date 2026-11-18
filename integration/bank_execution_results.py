"""Save original BANK-A07 proposals and reconciliation evidence, without payment effects."""
from dataclasses import dataclass

from integration.bank_draw_handoff import bank_draw_handoff_schemas
from integration.bank_execution_actions import PreparedBankExecution, validate_execution_selection
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankExecution(SavedBankIntake):
    """Local execute/reconcile/cancel_unexecuted evidence, not a payment receipt."""


class BankExecutionResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-execution-result.v1'
    ACTION_ID = 'BANK-A07'
    PREPARED_TYPE = PreparedBankExecution
    RESULT_TABLE = 'bank_execution_results'
    WAIT_KIND = 'manual_bank_execution_result_review'
    EXECUTION_ERROR_CODE = 'bank_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_draw_handoff_schemas)
    SAVED_TYPE = SavedBankExecution
    READ_ACTION_IDS = frozenset({'BANK-A07'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved execution proposal lacks an original selected input source')
        try:
            validate_execution_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved execution substitutes its original bank, facility, approval or command identity') from error
