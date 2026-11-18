"""Save original BANK-A03 risk-review evidence with no formal approval or reservation."""
from dataclasses import dataclass

from integration.bank_credit_actions import PreparedBankCredit
from integration.bank_intake_handoff import bank_intake_handoff_schemas
from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from src.actions.contracts.bank_credit_objects import CreditRiskMethodView
from src.actions.contracts.bank_objects import FinanceApplicationView, FinanceProductProfileView
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankCredit(SavedBankIntake):
    """Historical local recommendation, conditions or decline, not an approved facility."""


class BankCreditResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-credit-result.v1'
    ACTION_ID = 'BANK-A03'
    PREPARED_TYPE = PreparedBankCredit
    RESULT_TABLE = 'bank_credit_results'
    WAIT_KIND = 'manual_bank_credit_result_review'
    EXECUTION_ERROR_CODE = 'bank_credit_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_intake_handoff_schemas)
    SAVED_TYPE = SavedBankCredit
    READ_ACTION_IDS = frozenset({'BANK-A03', 'BANK-A04'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved credit review lacks an original selected input source')
        application = originals.get(action_input.application_ref.key())
        product = originals.get(action_input.product_ref.key())
        risk = originals.get(action_input.risk_method_ref.key())
        if (not isinstance(application, FinanceApplicationView) or application.ref != action_input.application_ref
                or not isinstance(product, FinanceProductProfileView) or product.ref != action_input.product_ref
                or not isinstance(risk, CreditRiskMethodView) or risk.ref != action_input.risk_method_ref
                or any(row.lender_id != identity.organization_id for row in (application, product, risk))
                or risk.product_ref != product.ref or product.ref not in application.product_candidates):
            raise TaskConflict('Saved credit review substitutes the original lender, application, product or method')
