"""Persist BANK-A06 batch decisions without formal draw approval or payment effects."""
from dataclasses import dataclass

from integration.bank_arrangement_handoff import bank_arrangement_handoff_schemas
from integration.bank_draw_actions import PreparedBankDraw, validate_draw_selection
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankDraw(SavedBankIntake):
    """Original local approved amount/lines or decline, not released cash."""


class BankDrawResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-draw-result.v1'
    ACTION_ID = 'BANK-A06'
    PREPARED_TYPE = PreparedBankDraw
    RESULT_TABLE = 'bank_draw_results'
    WAIT_KIND = 'manual_bank_draw_result_review'
    EXECUTION_ERROR_CODE = 'bank_draw_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_arrangement_handoff_schemas)
    SAVED_TYPE = SavedBankDraw
    READ_ACTION_IDS = frozenset({'BANK-A06', 'BANK-A07'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved draw decision lacks an original selected input source')
        try:
            validate_draw_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved draw decision substitutes original lender, batch, facility or terms') from error
