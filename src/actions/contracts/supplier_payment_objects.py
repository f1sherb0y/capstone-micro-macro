"""Order-node claims and actual supplier cash remain separate sourced records."""
from typing import Literal

from src.actions.contracts.common import Money, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.owner_financing_objects import FinancingApplicationDraft
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentAuthorizedLine, OwnerPaymentAccountView, OwnerPaymentSourceView,
    OwnerPaymentReservationView, OwnerPaymentObligationView, OwnerPaymentComponentView,
    OwnerPaymentExecutionView, OwnerPaymentReceiptView,
)
from src.actions.contracts.bank_objects import FundingPurposeView, FinanceProductProfileView
from src.methods.supplier_payment import SupplierClaimAmountInput, SupplierClaimAmountReport


class SupplierPaymentClaimLine(StrictRecord):
    order_line_ref: ref_type('OrderLine')
    scope_ref: ScopeRef
    claimed: Money
    evidence_refs: list[ref_type('Evidence')]
    prior_component_ref: ref_type('SettlementComponent') | None


class SupplierPaymentClaimDraft(StrictRecord):
    payer_id: TextId
    lines: list[SupplierPaymentClaimLine]
    settlement_rule_ref: ref_type('SettlementRule')
    prior_claim_refs: list[ref_type('PaymentClaim')]


class SupplierSettlementRuleView(CostSource):
    ref: ref_type('SettlementRule')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    currency: TextId
    choice: Literal['request_payment','authorize_payment','reconcile','dispute','seek_finance']
    business_key: TextId
    ledger_ref: ref_type('PaymentLedger')
    claim: SupplierPaymentClaimDraft | None
    node_refs: list[ref_type('OrderPaymentNode')]
    valuation_refs: list[ref_type('MethodResult')]
    account_ref: ref_type('Account') | None
    lines: list[OwnerPaymentAuthorizedLine]
    allow_partial: bool
    execution_refs: list[ref_type('PaymentExecution')]
    obligation_refs: list[ref_type('Obligation')]
    issue_refs: list[ref_type('PaymentIssue')]
    financing: FinancingApplicationDraft | None
    note: TextId


class SupplierPaymentLedgerView(CostSource):
    ref: ref_type('PaymentLedger')
    organization_id: TextId
    obligation_refs: list[ref_type('Obligation')]
    execution_refs: list[ref_type('PaymentExecution')]
    claim_refs: list[ref_type('PaymentClaim')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint
    producer: Literal['core']


class SupplierPaymentOrderView(CostSource):
    ref: ref_type('Order')
    supplier_id: TextId
    payer_id: TextId
    currency: TextId
    line_refs: list[ref_type('OrderLine')]
    node_refs: list[ref_type('OrderPaymentNode')]
    effective: ValueState[bool]


class SupplierPaymentOrderLineView(CostSource):
    ref: ref_type('OrderLine')
    order_ref: ref_type('Order')
    node_refs: list[ref_type('OrderPaymentNode')]


class SupplierOrderPaymentNodeView(GovReviewAuthored):
    ref: ref_type('OrderPaymentNode')
    order_ref: ref_type('Order')
    order_line_ref: ref_type('OrderLine')
    payer_id: TextId
    payee_id: TextId
    coverage_key: TextId
    purpose: Literal['advance','delivery','inspection','retention','other']
    node_authority_ref: ref_type('OrderPaymentNodeAuthority')
    data: SupplierClaimAmountInput
    delivery_evidence_refs: list[ref_type('DeliveryEvidence')]
    permitted: ValueState[bool]
    remaining_claimable: ValueState[Money]
    prior_component_ref: ref_type('SettlementComponent') | None
    as_of: TimePoint


class SupplierPaymentNodeAuthorityView(GovReviewAuthored):
    ref: ref_type('OrderPaymentNodeAuthority')
    order_ref: ref_type('Order')
    payer_id: TextId
    node_ref: ref_type('OrderPaymentNode')
    executor_organization_id: TextId
    executor_actor_id: TextId
    executor_function_ref: ref_type('FunctionAssignment')
    executor_authority_ref: ref_type('Authorization')
    executor_action_id: TextId
    permitted: ValueState[bool]


class SupplierClaimValuationView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    node_ref: ref_type('OrderPaymentNode')
    method_ref: ref_type('Method')
    data: SupplierClaimAmountInput
    input_sha256: Digest
    report: SupplierClaimAmountReport | None
    status: Literal['ok','unknown','failed','unsupported']


class SupplierPaymentDeliveryView(CostSource):
    ref: ref_type('DeliveryEvidence')
    order_ref: ref_type('Order')
    order_line_ref: ref_type('OrderLine')
    node_ref: ref_type('OrderPaymentNode')
    kind: Literal['actual_dispatch','actual_arrival','actual_receipt','actual_inspection']
    core_event_id: TextId
    occurred_at: TimePoint


class SupplierPaymentClaimView(GovReviewAuthored):
    ref: ref_type('PaymentClaim')
    organization_id: TextId
    business_key: TextId
    claim: SupplierPaymentClaimDraft
    node_refs: list[ref_type('OrderPaymentNode')]
    coverage_keys: list[TextId]
    status: Literal['submitted','pending','recognized','disputed','withdrawn','rejected']


class SupplierPaymentIssueView(CostSource):
    ref: ref_type('PaymentIssue')
    organization_id: TextId
    obligation_refs: list[ref_type('Obligation')]
    status: Literal['open','disputed','resolved']


def supplier_payment_schemas():
    return contractor_bid_schemas({
        'SettlementRule':SupplierSettlementRuleView,'PaymentLedger':SupplierPaymentLedgerView,
        'Order':SupplierPaymentOrderView,'OrderLine':SupplierPaymentOrderLineView,
        'OrderPaymentNode':SupplierOrderPaymentNodeView,'MethodResult':SupplierClaimValuationView,
        'OrderPaymentNodeAuthority':SupplierPaymentNodeAuthorityView,
        'DeliveryEvidence':SupplierPaymentDeliveryView,'PaymentClaim':SupplierPaymentClaimView,
        'PaymentIssue':SupplierPaymentIssueView,'Account':OwnerPaymentAccountView,
        'FundingSource':OwnerPaymentSourceView,'CashReservation':OwnerPaymentReservationView,
        'Obligation':OwnerPaymentObligationView,'SettlementComponent':OwnerPaymentComponentView,
        'PaymentExecution':OwnerPaymentExecutionView,'PaymentReceipt':OwnerPaymentReceiptView,
        'FundingPurpose':FundingPurposeView,'FinanceProductProfile':FinanceProductProfileView,
    })
