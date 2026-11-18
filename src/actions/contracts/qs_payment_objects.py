"""Original payment applications, work, certificate history and cash/credit linkage."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, TextId, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_change_objects import ChangeAuthored, QSChangeContractView
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceUse, ServiceClockView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.qs_payment import PaymentValuationReport


class QSPaymentContractView(QSChangeContractView):
    payer_id: TextId
    beneficiary_id: TextId
    rate_refs: list[ref_type('ContractRate')]
    retention_fraction: DecimalString
    retention_cap: Money | None
    deduction_refs: list[ref_type('Deduction')]
    advance_credit_refs: list[ref_type('AdvanceCredit')]
    active_certificate_refs: list[ref_type('Certificate')]
    certificate_count: Annotated[int, Field(ge=0)]
    receipt_refs: list[ref_type('PaymentReceipt')]
    certified_cash_visibility: Literal['complete', 'unavailable']

    @model_validator(mode='after')
    def history(self):
        for refs in (self.rate_refs, self.deduction_refs, self.advance_credit_refs, self.active_certificate_refs, self.receipt_refs):
            unique_refs(refs)
        if len(self.active_certificate_refs) != self.certificate_count:
            raise ValueError('Contract projection must carry its complete original active certificate set')
        if self.payer_id not in self.party_ids or self.beneficiary_id not in self.party_ids or self.payer_id == self.beneficiary_id:
            raise ValueError('Contract payment parties must be distinct original parties')
        return self


class QSPaymentApplicationView(ChangeAuthored):
    ref: ref_type('PaymentApplication')
    contract_ref: ref_type('Contract')
    applicant_id: TextId
    period: TimeWindow
    basis: Literal['incremental', 'cumulative']
    work_refs: list[ref_type('WorkFact')]
    question_refs: list[ref_type('EvidenceTarget')]
    unresolved_question_refs: list[ref_type('EvidenceTarget')]
    valuation_result_ref: ref_type('MethodResult') | None
    retention_result_ref: ref_type('MethodResult') | None
    deduction_result_ref: ref_type('MethodResult') | None
    certification_basis_ref: ref_type('CertificationBasis') | None
    correction_basis_ref: ref_type('CorrectionBasis') | None
    status: Literal['submitted', 'withdrawn']

    @model_validator(mode='after')
    def refs(self):
        for refs in (self.work_refs, self.question_refs, self.unresolved_question_refs):
            unique_refs(refs)
        if not set(self.unresolved_question_refs) <= set(self.question_refs):
            raise ValueError('Application unresolved questions must be original registered questions')
        if self.certification_basis_ref is not None and self.correction_basis_ref is not None:
            raise ValueError('Application selects either original certification or correction basis')
        return self


class QSPaymentWorkView(ChangeAuthored):
    ref: ref_type('WorkFact')
    contract_ref: ref_type('Contract')
    work_key: TextId
    period: TimeWindow
    quantity: Measured
    rate_ref: ref_type('ContractRate')
    condition_ref: ref_type('PaymentCondition')


class QSPaymentRateView(CostSource):
    ref: ref_type('ContractRate')
    contract_ref: ref_type('Contract')
    amount: Money
    quantity_unit: TextId


class QSPaymentConditionView(ChangeAuthored):
    ref: ref_type('PaymentCondition')
    contract_ref: ref_type('Contract')
    work_ref: ref_type('WorkFact')
    fulfilled: ValueState[bool]
    condition_authority_ref: ref_type('Authority')


class QSPaymentResultView(ChangeAuthored):
    ref: ref_type('MethodResult')
    method_ref: ref_type('Method')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication')
    result_kind: Literal['valuation', 'retention', 'deduction']
    valuation_basis: Literal['incremental', 'cumulative']
    correction_of: ref_type('Certificate') | None
    input_sha256: TextId
    status: Literal['ok', 'failed', 'unsupported']
    report: PaymentValuationReport | None


class QSPaymentCertificateView(ChangeAuthored):
    ref: ref_type('Certificate')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication')
    statement_ref: ref_type('ValuationStatement')
    calculation_ref: ref_type('MethodResult')
    certification_authority_ref: ref_type('Authority')
    certificate_key: TextId
    sequence: Annotated[int, Field(ge=1)]
    status: Literal['active', 'superseded']
    predecessor_ref: ref_type('Certificate') | None
    work_keys: list[TextId]
    assessed_contribution: Money
    net_contribution: Money
    retention_contribution: Money
    advance_allocations: list['QSPaymentCreditAllocation']


class QSPaymentCreditAllocation(CostSource):
    ref: ref_type('CreditAllocation')
    contract_ref: ref_type('Contract')
    credit_ref: ref_type('AdvanceCredit')
    certificate_ref: ref_type('Certificate')
    amount: Money


class QSPaymentStatementView(ChangeAuthored):
    ref: ref_type('ValuationStatement')
    contract_ref: ref_type('Contract')
    certificate_ref: ref_type('Certificate')
    calculation_ref: ref_type('MethodResult')


class QSPaymentAdjustmentView(ChangeAuthored):
    ref: ref_type('Deduction')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication')
    amount: Money
    deduction_authority_ref: ref_type('Authority')


class QSPaymentCreditView(CostSource):
    ref: ref_type('AdvanceCredit')
    contract_ref: ref_type('Contract')
    source_receipt_refs: list[ref_type('PaymentReceipt')]
    received_amount: Money
    allocation_refs: list[ref_type('CreditAllocation')]
    allocation_count: Annotated[int, Field(ge=0)]
    application_ref: ref_type('PaymentApplication')
    offset_amount: Money

    @model_validator(mode='after')
    def history(self):
        unique_refs(self.source_receipt_refs); unique_refs(self.allocation_refs)
        if len(self.allocation_refs) != self.allocation_count:
            raise ValueError('Advance credit allocation history must be complete')
        return self


class QSPaymentReceiptView(CostSource):
    ref: ref_type('PaymentReceipt')
    contract_ref: ref_type('Contract')
    execution_ref: ref_type('PaymentExecution')
    certificate_ref: ref_type('Certificate') | None
    credit_ref: ref_type('AdvanceCredit') | None
    purpose: Literal['certified_payment', 'advance']
    payer_id: TextId
    beneficiary_id: TextId
    command_id: TextId
    business_key: TextId
    event_id: TextId
    sequence: Annotated[int, Field(ge=0)]
    semantics: Literal['incremental', 'cumulative']
    status: Literal['verified_partial', 'verified_final', 'unknown', 'failed', 'rejected']
    amount: ValueState[Money]


class QSPaymentExecutionView(CostSource):
    ref: ref_type('PaymentExecution')
    contract_ref: ref_type('Contract')
    certificate_ref: ref_type('Certificate') | None
    credit_ref: ref_type('AdvanceCredit') | None
    purpose: Literal['certified_payment', 'advance']
    payer_id: TextId
    beneficiary_id: TextId
    command_id: TextId
    business_key: TextId
    receipt_refs: list[ref_type('PaymentReceipt')]


class QSPaymentAuthorityView(CostSource):
    ref: ref_type('Authority')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication') | None
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    purposes: list[Literal['condition', 'deduct', 'certify', 'correct']]
    certificate_key: TextId | None


class QSPaymentCertificationView(ChangeAuthored):
    ref: ref_type('CertificationBasis')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication')
    authority_ref: ref_type('Authority')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    certificate_key: TextId
    statement_sha256: TextId


class QSPaymentCorrectionView(ChangeAuthored):
    ref: ref_type('CorrectionBasis')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication')
    authority_ref: ref_type('Authority')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    prior_certificate_ref: ref_type('Certificate')
    certificate_key: TextId
    statement_sha256: TextId


class QSPaymentQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication')
    question: TextId
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    blocking_uses: Annotated[list[ServiceUse], Field(min_length=1)]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSPaymentResponseView(CostSource):
    ref: ref_type('ResponseRequirement')
    contract_ref: ref_type('Contract')
    application_ref: ref_type('PaymentApplication')
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]


QSPaymentCertificateView.model_rebuild()


def qs_payment_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Contract': QSPaymentContractView, 'PaymentApplication': QSPaymentApplicationView,
        'WorkFact': QSPaymentWorkView, 'ContractRate': QSPaymentRateView,
        'PaymentCondition': QSPaymentConditionView, 'MethodResult': QSPaymentResultView,
        'Certificate': QSPaymentCertificateView, 'ValuationStatement': QSPaymentStatementView,
        'CreditAllocation': QSPaymentCreditAllocation, 'Deduction': QSPaymentAdjustmentView,
        'AdvanceCredit': QSPaymentCreditView, 'PaymentReceipt': QSPaymentReceiptView,
        'PaymentExecution': QSPaymentExecutionView, 'Authority': QSPaymentAuthorityView,
        'CertificationBasis': QSPaymentCertificationView, 'CorrectionBasis': QSPaymentCorrectionView,
        'EvidenceTarget': QSPaymentQuestionView, 'ResponseRequirement': QSPaymentResponseView,
        'ClockProfile': ServiceClockView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
