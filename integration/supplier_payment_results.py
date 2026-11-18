"""Persist original Supplier A10 decisions without creating claims, rights or cash."""
from dataclasses import dataclass

from integration.supplier_receiving_handoff import supplier_receiving_handoff_schemas
from integration.supplier_payment_actions import PreparedSupplierPayment
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.supplier_payment_objects import (
    OwnerPaymentAccountView, OwnerPaymentComponentView, OwnerPaymentExecutionView, OwnerPaymentObligationView,
    SupplierPaymentDeliveryView, SupplierPaymentOrderView,
    SupplierSettlementRuleView, supplier_payment_schemas,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedSupplierPayment(SavedSupplierQuote):
    """Historical local payment evidence; independent rights and cash receipts stay separate."""


class SupplierPaymentResultWorker(SupplierQuoteResultWorker):
    """Reuse original claim-once, pending and result recovery rules in an A10 table."""
    SCHEMA = 'supplier-payment-result.v1'
    ACTION_ID = 'SUPPLIER-A10'
    PREPARED_TYPE = PreparedSupplierPayment
    RESULT_TABLE = 'supplier_payment_results'
    WAIT_KIND = 'manual_supplier_payment_result_review'
    EXECUTION_ERROR_CODE = 'supplier_payment_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_receiving_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A10', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierPayment

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']) == ref]
        if len(originals) != 1:
            raise TaskConflict('Saved payment lacks its exact original settlement or source version')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref != ref:
            raise TaskConflict('Saved payment projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        rule = self._original(sources, Reference.model_validate(action_input['settlement_rule_ref']), SupplierSettlementRuleView)
        if (rule.organization_id != identity.organization_id or rule.actor_id != context.actor_id
                or rule.function_ref != context.function_ref or rule.scope != context.scope
                or rule.authority_ref not in context.authorization_refs):
            raise TaskConflict('Saved payment changes original Supplier, scope or settlement authority')
        # Preserve both incoming customer receipts and outgoing upstream cash.
        # Ownership and business effects remain the original processor checks.
        obligations, accounts = [], []
        for field, schema in (('order_refs', SupplierPaymentOrderView), ('obligation_refs', OwnerPaymentObligationView),
                ('delivery_evidence_refs', SupplierPaymentDeliveryView), ('account_refs', OwnerPaymentAccountView),
                ('execution_refs', OwnerPaymentExecutionView)):
            for raw_ref in action_input[field]:
                value = self._original(sources, Reference.model_validate(raw_ref), schema)
                if isinstance(value, OwnerPaymentObligationView):
                    obligations.append(value)
                elif isinstance(value, OwnerPaymentAccountView):
                    accounts.append(value)
        executions = {Reference.model_validate(row['ref']).key(): OwnerPaymentExecutionView.model_validate(row['projection'])
            for row in sources if Reference.model_validate(row['ref']).kind == 'PaymentExecution'}
        account_pending = {}
        for account in accounts:
            if account.organization_id != identity.organization_id:
                raise TaskConflict('Saved Supplier payment uses another organization account')
            unique_refs(account.pending_execution_refs)
            for ref in account.pending_execution_refs:
                key = ref.key()
                if key in account_pending and account_pending[key] != account.ref:
                    raise TaskConflict('Saved Supplier pending payment is attributed to multiple original accounts')
                account_pending[key] = account.ref
                prior = executions.get(key)
                if prior is not None and (prior.organization_id != identity.organization_id or prior.account_ref != account.ref):
                    raise TaskConflict('Saved Supplier account pending payment changes original legal payer or exact account')
        # Validate components already present in the original saved reading.
        # Early financing/first-claim branches need no invented or extra reads.
        components = {Reference.model_validate(row['ref']).key(): OwnerPaymentComponentView.model_validate(row['projection'])
            for row in sources if Reference.model_validate(row['ref']).kind == 'SettlementComponent'}
        for obligation in obligations:
            unique_refs(obligation.component_refs)
            for ref in obligation.component_refs:
                component = components.get(ref.key())
                if component is not None and (component.ref != ref or component.obligation_ref != obligation.ref
                        or component.debtor_id != obligation.debtor_id or component.payee_id != obligation.payee_id
                        or component.source_ref != obligation.source_ref or component.debt_ref != obligation.debt_ref):
                    raise TaskConflict('Saved Supplier payment changes original obligation component, loan, parties or funding source')

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A10 saved decision is not an A03 quote, certified payment right or native cash receipt')
