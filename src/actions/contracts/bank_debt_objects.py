"""Original debts, verified receipts and append-only accounting observations."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import DecimalString, Money, Reference, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.bank_debt import DebtAccrualInput, DebtAccrualReport


class BankDebtArrangementView(CostSource):
    ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    terms_ref: ref_type('FinanceTerms')
    currency: TextId
    debt_component_refs: list[ref_type('DebtComponent')]
    posting_refs: list[ref_type('LedgerPosting')]
    receipt_refs: list[ref_type('VerifiedReceipt')]
    execution_refs: list[ref_type('PaymentExecution')]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']


class BankDebtTermsView(CostSource):
    ref: ref_type('FinanceTerms')
    arrangement_ref: ref_type('FinanceArrangement')
    rate_mode: Literal['fixed', 'floating']
    fixed_annual_rate: DecimalString | None
    commitment_fee_annual_rate: DecimalString | None
    permitted_reset_refs: list[ref_type('RateReset')]
    permitted_calendar_refs: list[ref_type('DebtCalendar')]
    allocation_rule_ref: ref_type('SettlementAllocationRule')
    repayment_effective_rule: Literal['verified_product_effective_time']
    minor_places: Annotated[int, Field(ge=0, le=8)]
    rounding: Literal['half_even', 'floor', 'ceiling']


class BankDebtComponentView(CostSource):
    ref: ref_type('DebtComponent')
    debt_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    kind: Literal['principal', 'interest', 'fee', 'commitment_fee']
    opening_at: TimePoint
    opening_balance: Money
    actual_due: Money
    cash_paid: Money
    due_at: TimePoint
    balance_source_ref: Reference | None


class BankDebtProfileView(CostSource):
    ref: ref_type('DebtCalculationProfile')
    arrangement_ref: ref_type('FinanceArrangement')
    authority_ref: ref_type('Authorization')
    choice: Literal['calculate_due', 'allocate_receipt', 'reconcile', 'correct_accrual']
    basis_refs: list[ref_type('CommittedEvidence')]
    method_ref: ref_type('Method') | None
    accrual_input: DebtAccrualInput | None
    saved_report: DebtAccrualReport | None
    note: TextId


class BankDebtPrincipalEffect(StrictRecord):
    debt_component_ref: ref_type('DebtComponent')
    amount: Money


class BankDebtReceiptView(CostSource):
    ref: ref_type('VerifiedReceipt')
    arrangement_ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    execution_ref: ref_type('PaymentExecution')
    command_id: TextId
    business_key: TextId
    event_id: TextId
    kind: Literal['draw', 'repayment']
    amount: Money
    effective_at: TimePoint
    verified_at: TimePoint
    principal_effects: list[BankDebtPrincipalEffect]


class BankDebtPostingView(CostSource):
    ref: ref_type('LedgerPosting')
    business_key: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    debt_component_ref: ref_type('DebtComponent')
    kind: Literal['accrual', 'correction', 'allocation']
    amount: Money
    accrual_window: TimeWindow | None
    receipt_event_id: TextId | None
    original_posting_refs: list[ref_type('LedgerPosting')]


class BankDebtExecutionView(CostSource):
    ref: ref_type('PaymentExecution')
    arrangement_ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    command_id: TextId
    business_key: TextId
    receipt_refs: list[ref_type('VerifiedReceipt')]
    status: Literal['pending', 'partial', 'succeeded', 'failed', 'unknown']


class BankDebtEvidenceView(CostSource):
    ref: ref_type('CommittedEvidence')
    arrangement_ref: ref_type('FinanceArrangement')
    original_record_ref: Reference
    content_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    original_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class BankDebtAllocationRuleView(CostSource):
    ref: ref_type('SettlementAllocationRule')
    arrangement_ref: ref_type('FinanceArrangement')
    priority: Annotated[list[Literal['principal', 'interest', 'fee', 'commitment_fee']], Field(min_length=1)]
    allow_not_due: bool
    excess_treatment: Literal['retain_unallocated_for_refund_or_credit']


class BankDebtResetView(CostSource):
    ref: ref_type('RateReset')
    arrangement_ref: ref_type('FinanceArrangement')
    terms_ref: ref_type('FinanceTerms')
    reset_at: TimePoint
    annual_rate: DecimalString
    rate_basis_ref: ref_type('Evidence')
    rate_window: TimeWindow


class BankDebtCalendarView(CostSource):
    ref: ref_type('DebtCalendar')
    arrangement_ref: ref_type('FinanceArrangement')
    calendar_window: TimeWindow
    ticks_per_year: Annotated[int, Field(gt=0)]
    tick_rule: Literal['uniform_linear']
    calendar_basis_ref: ref_type('Evidence')


class BankDebtCommitmentView(CostSource):
    ref: ref_type('FinanceCommitment')
    arrangement_ref: ref_type('FinanceArrangement')
    opening_at: TimePoint
    opening_undrawn: Money
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    change_refs: list[ref_type('FinanceCommitmentChange')]


class BankDebtCommitmentChangeView(CostSource):
    ref: ref_type('FinanceCommitmentChange')
    commitment_ref: ref_type('FinanceCommitment')
    effective_at: TimePoint
    before: Money
    after: Money
    committed_basis_ref: ref_type('CommittedEvidence')


def bank_debt_schemas():
    registry = common_projection_schemas()
    schemas = {
        'FinanceArrangement': BankDebtArrangementView, 'FinanceTerms': BankDebtTermsView,
        'DebtComponent': BankDebtComponentView, 'DebtCalculationProfile': BankDebtProfileView,
        'VerifiedReceipt': BankDebtReceiptView, 'LedgerPosting': BankDebtPostingView,
        'PaymentExecution': BankDebtExecutionView, 'CommittedEvidence': BankDebtEvidenceView,
        'SettlementAllocationRule': BankDebtAllocationRuleView, 'RateReset': BankDebtResetView,
        'DebtCalendar': BankDebtCalendarView, 'FinanceCommitment': BankDebtCommitmentView,
        'FinanceCommitmentChange': BankDebtCommitmentChangeView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView, 'ClockProfile': ServiceClockView,
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
