"""Bank transfer proposals and receipt observations; formal ledger stays host-owned."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Money, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.bank_draw_objects import BankDrawTransferLine
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView


class BankExecutionAmounts(StrictRecord):
    beneficiary_cash: Money
    principal: Money
    withheld_fee: Money
    capitalized_fee: Money
    separate_fee_cash: Money
    bank_debit: Money


class BankExecutionApprovedLine(StrictRecord):
    local_key: TextId
    transfer: BankDrawTransferLine
    amounts: BankExecutionAmounts


class BankExecutionArrangementView(CostSource):
    ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    terms_ref: ref_type('FinanceTerms')
    execution_profile_ref: ref_type('FundingExecutionProfile')
    status: Literal['active', 'suspended', 'expired', 'closed']


class BankExecutionProfileView(CostSource):
    ref: ref_type('FundingExecutionProfile')
    organization_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    authority_ref: ref_type('Authorization')
    existing_choice: Literal['reconcile', 'cancel_unexecuted']
    note: TextId


class BankExecutionApprovalView(CostSource):
    ref: ref_type('DrawApproval')
    lender_id: TextId
    borrower_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    terms_ref: ref_type('FinanceTerms')
    batch_key: TextId
    amount: Money
    lines: Annotated[list[BankExecutionApprovedLine], Field(min_length=1)]
    execution_refs: list[ref_type('PaymentExecution')]
    execution_coverage: Literal['complete', 'partial', 'unknown']
    status: Literal['approved', 'cancelled', 'expired']
    approved_at: TimePoint
    approver_actor_id: TextId
    approver_function_ref: ref_type('FunctionAssignment')
    approver_authority_ref: ref_type('Authorization')


class BankExecutionPathView(CostSource):
    ref: ref_type('FundingPath')
    lender_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    source_account_ref: ref_type('Account')
    currency: TextId
    destination_refs: list[ref_type('Account')]
    fee_rule_refs: list[ref_type('FeeRule')]
    conditions_satisfied: ValueState[bool]
    execution_window: TimeWindow
    permits_cancel_undispatched: bool
    status: Literal['available', 'unavailable']


class BankExecutionAccountView(CostSource):
    ref: ref_type('Account')
    organization_id: TextId
    currency: TextId
    as_of: TimePoint
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    reservation_refs: list[ref_type('CashReservation')]
    coverage: Literal['complete', 'partial', 'unknown']
    permitted_path_refs: list[ref_type('FundingPath')]


class BankExecutionReservationView(CostSource):
    ref: ref_type('CashReservation')
    organization_id: TextId
    account_ref: ref_type('Account')
    as_of: TimePoint
    amount: Money
    status: Literal['held', 'released', 'consumed']
    disposition_basis_ref: ref_type('Evidence')


class BankExecutionFeeRuleView(CostSource):
    ref: ref_type('FeeRule')
    arrangement_ref: ref_type('FinanceArrangement')
    approval_ref: ref_type('DrawApproval')
    destination_ref: ref_type('Account')
    withheld_fee: Money
    capitalized_fee: Money
    separate_fee_cash: Money


class BankExecutionObligationView(CostSource):
    ref: ref_type('Obligation')
    borrower_id: TextId
    payee_id: TextId
    unpaid_amount: ValueState[Money]
    payable: ValueState[bool]


class BankExecutionSavedView(CostSource):
    ref: ref_type('PaymentExecution')
    lender_id: TextId
    borrower_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    approval_ref: ref_type('DrawApproval')
    path_ref: ref_type('FundingPath')
    command_id: TextId
    business_key: TextId
    lines: Annotated[list[BankExecutionApprovedLine], Field(min_length=1)]
    receipt_refs: list[ref_type('PaymentReceipt')]
    receipt_coverage: Literal['complete', 'partial', 'unknown']
    dispatch_state: Literal['undispatched', 'dispatched', 'unknown']
    confirmed_unexecuted_amount: ValueState[Money]
    dispatch_evidence_ref: ref_type('Evidence')
    line_dispatch_states: dict[TextId, Literal['undispatched', 'dispatched', 'unknown']]
    cancel_line_keys: list[TextId]


class BankExecutionReceiptLine(StrictRecord):
    local_key: TextId
    destination_ref: ref_type('Account')
    beneficiary_id: TextId
    amounts: BankExecutionAmounts


class BankExecutionReceiptView(CostSource):
    ref: ref_type('PaymentReceipt')
    lender_id: TextId
    borrower_id: TextId
    execution_ref: ref_type('PaymentExecution')
    arrangement_ref: ref_type('FinanceArrangement')
    approval_ref: ref_type('DrawApproval')
    path_ref: ref_type('FundingPath')
    command_id: TextId
    business_key: TextId
    event_id: TextId
    sequence: Annotated[int, Field(ge=0)]
    semantics: Literal['incremental', 'cumulative']
    status: Literal['verified_partial', 'verified_final', 'unknown', 'failed', 'rejected']
    observed_at: TimePoint
    lines: list[BankExecutionReceiptLine]
    confirmed_unexecuted_amount: ValueState[Money]


def bank_execution_schemas():
    registry = common_projection_schemas()
    schemas = {
        'FinanceArrangement': BankExecutionArrangementView, 'FundingExecutionProfile': BankExecutionProfileView,
        'DrawApproval': BankExecutionApprovalView, 'FundingPath': BankExecutionPathView,
        'Account': BankExecutionAccountView, 'CashReservation': BankExecutionReservationView,
        'FeeRule': BankExecutionFeeRuleView, 'Obligation': BankExecutionObligationView,
        'PaymentExecution': BankExecutionSavedView, 'PaymentReceipt': BankExecutionReceiptView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView, 'ClockProfile': ServiceClockView,
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
