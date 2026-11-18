"""Original owner cash instructions, actual balances and settlement identities."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Money, Reference, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_financing_objects import (
    FinancingAcceptanceView, FinancingAccountView, FinancingArrangementView, FinancingObligationView, FinancingTerms,
)
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.qs_payment_objects import QSPaymentCertificateView
from src.actions.contracts.service_objects import ServiceClockView, ServiceWorkScopeView
from src.methods.models import Digest


class OwnerPaymentScopeView(CostSource):
    ref: Reference
    organization_id: TextId
    payment_authorization_ref: ref_type('PaymentAuthorization') | None


class OwnerPaymentComponentAmount(StrictRecord):
    component_ref: ref_type('SettlementComponent')
    amount: Money


class OwnerPaymentAuthorizedLine(StrictRecord):
    obligation_ref: ref_type('Obligation')
    payee_id: TextId
    amount: Money
    component_amounts: Annotated[list[OwnerPaymentComponentAmount], Field(min_length=1)]
    priority: int


class OwnerPaymentAuthorizationView(CostSource):
    ref: ref_type('PaymentAuthorization')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['draw_request', 'pay', 'repay', 'dispute', 'negotiate', 'reconcile']
    account_ref: ref_type('Account') | None
    lines: list[OwnerPaymentAuthorizedLine]
    allow_partial: bool
    draw_authorization_ref: ref_type('DrawAuthorization') | None
    obligation_refs: list[ref_type('Obligation')]
    execution_refs: list[ref_type('PaymentExecution')]
    note: TextId


class OwnerPaymentAccountView(FinancingAccountView):
    reserved_cash: ValueState[Money]
    pending_execution_refs: list[ref_type('PaymentExecution')]
    execution_coverage: Literal['complete', 'partial', 'unknown']
    reservation_refs: list[ref_type('CashReservation')]


class OwnerPaymentSourceView(CostSource):
    ref: ref_type('FundingSource')
    organization_id: TextId
    account_ref: ref_type('Account')
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']


class OwnerPaymentReservationView(CostSource):
    ref: ref_type('CashReservation')
    account_ref: ref_type('Account')
    organization_id: TextId
    amount: ValueState[Money]
    status: Literal['held', 'released', 'consumed']
    as_of: TimePoint
    disposition_basis_ref: ref_type('Evidence')


class OwnerPaymentArrangementView(FinancingArrangementView):
    as_of: TimePoint
    draw_coverage: Literal['complete', 'partial', 'unknown']
    allowed_draw_authorization_refs: list[ref_type('DrawAuthorization')]
    allowed_beneficiary_ids: list[TextId]
    required_draw_condition_refs: list[ref_type('Requirement')]
    pending_execution_refs: list[ref_type('PaymentExecution')]


class OwnerPaymentArrangementReceiptView(CostSource):
    """Actually signed arrangement received from the bank, without available cash."""
    ref: ref_type('FinanceArrangementReceipt')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    arrangement_ref: ref_type('FinanceArrangement')
    arrangement_sha256: Digest
    accepted_terms: FinancingTerms
    confirmed_conditions_sha256: Digest
    signed_at: TimePoint
    received_at: TimePoint
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class OwnerPaymentDrawView(CostSource):
    ref: ref_type('DrawAuthorization')
    arrangement_ref: ref_type('FinanceArrangement')
    organization_id: TextId
    amount: Money
    beneficiary_id: TextId
    condition_refs: list[ref_type('Requirement')]
    condition_evidence_refs: list[ref_type('Evidence')]
    direct_payment_obligation_ref: ref_type('Obligation') | None
    additional_draw: bool
    original_execution_ref: ref_type('PaymentExecution') | None


class OwnerPaymentDrawConditionView(CostSource):
    ref: ref_type('Requirement')
    arrangement_ref: ref_type('FinanceArrangement')
    draw_authorization_ref: ref_type('DrawAuthorization')
    borrower_id: TextId
    evidence_ref: ref_type('Evidence')
    satisfied: ValueState[bool]
    verifier_organization_id: TextId
    verifier_actor_id: TextId
    verifier_function_ref: ref_type('FunctionAssignment')
    verifier_authority_ref: ref_type('Authorization')
    verifier_action_id: TextId
    verified_at: TimePoint


class OwnerPaymentDebtView(CostSource):
    ref: ref_type('Debt')
    borrower_id: TextId
    lender_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    terms_ref: ref_type('FinanceTerms')
    obligation_refs: list[ref_type('Obligation')]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']


class OwnerPaymentDebtTermsView(CostSource):
    ref: ref_type('FinanceTerms')
    debt_ref: ref_type('Debt')
    borrower_id: TextId
    lender_id: TextId
    principal_component_refs: list[ref_type('SettlementComponent')]
    interest_component_refs: list[ref_type('SettlementComponent')]
    fee_component_refs: list[ref_type('SettlementComponent')]


class OwnerPaymentObligationView(FinancingObligationView):
    status: Literal['effective', 'disputed', 'settled', 'cancelled']
    kind: Literal['works', 'supply', 'service', 'principal', 'interest', 'fee', 'other']
    actual_offset: ValueState[Money]
    payable: ValueState[bool]
    verification_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class OwnerPaymentCertificateAllocation(StrictRecord):
    """Observed signed certificate contribution to an original settlement component."""
    obligation_ref: ref_type('Obligation')
    component_ref: ref_type('SettlementComponent')
    amount: Money


class OwnerPaymentCertificateReceiptView(CostSource):
    """Actually issued certificate and received obligation link, never derived here."""
    ref: ref_type('PaymentCertificateReceipt')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    certificate: QSPaymentCertificateView
    obligation_ref: ref_type('Obligation') | None
    component_refs: Annotated[list[ref_type('SettlementComponent')], Field(min_length=1)]
    allocations: Annotated[list[OwnerPaymentCertificateAllocation], Field(min_length=1)] | None = None
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    received_at: TimePoint


class OwnerPaymentComponentView(CostSource):
    ref: ref_type('SettlementComponent')
    obligation_ref: ref_type('Obligation')
    debt_ref: ref_type('Debt') | None
    debtor_id: TextId
    payee_id: TextId
    source_ref: ref_type('FundingSource')
    as_of: TimePoint
    category: Literal['works', 'supply', 'service', 'principal', 'interest', 'fee', 'other']
    settlement_mode: Literal['cash', 'prepayment_offset', 'certified_adjustment']
    actual_due: ValueState[Money]
    actual_cash_paid: ValueState[Money]
    actual_offset: ValueState[Money]


class OwnerPaymentExecutionView(CostSource):
    ref: ref_type('PaymentExecution')
    organization_id: TextId
    command_id: TextId
    business_key: TextId
    authorization_ref: ref_type('PaymentAuthorization') | ref_type('DrawAuthorization')
    operation: Literal['draw_request', 'pay', 'repay']
    account_ref: ref_type('Account') | None
    arrangement_ref: ref_type('FinanceArrangement') | None
    obligation_refs: list[ref_type('Obligation')]
    component_refs: list[ref_type('SettlementComponent')]
    beneficiary_id: TextId
    amount: Money
    status: Literal['unknown', 'pending', 'succeeded', 'failed', 'rejected']
    receipt_ref: ref_type('PaymentReceipt') | None


class OwnerPaymentReceiptView(CostSource):
    ref: ref_type('PaymentReceipt')
    execution_ref: ref_type('PaymentExecution')
    command_id: TextId
    business_key: TextId
    amount: Money
    beneficiary_id: TextId
    status: Literal['succeeded', 'failed', 'rejected']


class OwnerBankExecutionReceptionView(CostSource):
    """Observed Bank reconciliation mapped to an original Owner draw execution."""
    ref: ref_type('BankExecutionReception')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    bank_execution_ref: ref_type('PaymentExecution')
    owner_execution_ref: ref_type('PaymentExecution')
    owner_execution_sha256: Digest
    received_at: TimePoint
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


def owner_payment_schemas():
    registry = common_projection_schemas()
    schemas = {
        'PaymentAuthorization': OwnerPaymentAuthorizationView, 'DrawAuthorization': OwnerPaymentDrawView,
        'Account': OwnerPaymentAccountView, 'FinanceArrangement': OwnerPaymentArrangementView,
        'FundingSource': OwnerPaymentSourceView, 'Debt': OwnerPaymentDebtView, 'FinanceTerms': OwnerPaymentDebtTermsView,
        'CashReservation': OwnerPaymentReservationView,
        'Requirement': OwnerPaymentDrawConditionView, 'Obligation': OwnerPaymentObligationView,
        'SettlementComponent': OwnerPaymentComponentView, 'PaymentExecution': OwnerPaymentExecutionView,
        'PaymentReceipt': OwnerPaymentReceiptView, 'ClockProfile': ServiceClockView, 'WorkScope': ServiceWorkScopeView,
        'PaymentCertificateReceipt': OwnerPaymentCertificateReceiptView,
        'FinanceArrangementReceipt': OwnerPaymentArrangementReceiptView,
        'PartyAcceptance': FinancingAcceptanceView,
        'BankExecutionReception': OwnerBankExecutionReceptionView,
        **{kind: OwnerPaymentScopeView for kind in ('Organization', 'OwnerCase', 'Project')},
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
