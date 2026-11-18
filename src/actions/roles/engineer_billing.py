"""ENGINEER-A10 binds its original projections to shared service billing."""
from src.actions.contracts.engineer_billing_objects import (
    EngineerBillingEngagementView, EngineerBillingProfileView, EngineerBillingClauseView,
    EngineerBillingWorkFactView, EngineerBillingCalculationView, EngineerBillingClaimView,
    EngineerBillingReceiptView, EngineerBillingExecutionView, EngineerBillingQuestionView,
    EngineerBillingAdvanceCreditView, EngineerBillingPayableView,
)
from src.actions.roles.service_billing import handle_service_fees


def handle_engineering_fees(context, action_input, reading):
    return handle_service_fees(context, action_input, reading, role='Engineer',
        action_id='ENGINEER-A10', billing_types={
            'Engagement': EngineerBillingEngagementView,
            'BillingProfile': EngineerBillingProfileView,
            'BillingClause': EngineerBillingClauseView,
            'WorkFact': EngineerBillingWorkFactView,
            'FeeCalculation': EngineerBillingCalculationView,
            'FeeClaim': EngineerBillingClaimView,
            'PaymentReceipt': EngineerBillingReceiptView,
            'PaymentExecution': EngineerBillingExecutionView,
            'EvidenceTarget': EngineerBillingQuestionView,
            'AdvanceCredit': EngineerBillingAdvanceCreditView,
            'Obligation': EngineerBillingPayableView,
        })
