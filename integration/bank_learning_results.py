"""Persist BANK-A12 original private learning evidence without retroactive fact changes."""
from dataclasses import dataclass

from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from integration.bank_learning_actions import (
    PreparedBankLearning, validate_learning_selection, validate_learning_execution_history,
)
from src.actions.contracts.bank_learning_objects import bank_learning_schemas
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankLearning(SavedBankIntake):
    """Original local retain/lesson/strategy proposal, not applied or calibrated learning."""


class BankLearningResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-learning-result.v1'
    ACTION_ID = 'BANK-A12'
    PREPARED_TYPE = PreparedBankLearning
    RESULT_TABLE = 'bank_learning_results'
    WAIT_KIND = 'manual_bank_learning_result_review'
    EXECUTION_ERROR_CODE = 'bank_learning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_learning_schemas)
    SAVED_TYPE = SavedBankLearning
    READ_ACTION_IDS = frozenset({'BANK-A12'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        context = ActionContext.model_validate(snapshot['context'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved learning decision lacks an original selected input source')
        try:
            validate_learning_selection(action_input, scope=context.scope, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
            validate_learning_execution_history(action_input, scope=context.scope,
                organization_id=identity.organization_id, sources=originals)
        except ValueError as error:
            raise TaskConflict('Saved learning substitutes original private bank, scope, judgment or outcome identity') from error
