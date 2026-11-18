"""Contractor requests preserve measured work, receivables and actual own cash."""
from typing import Literal
from pydantic import Field

from src.actions.contracts.common import Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.contractor_execution_objects import ContractorWorkRecordView
from src.actions.contracts.owner_financing_objects import FinancingApplicationDraft
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentAuthorizedLine, OwnerPaymentAccountView, OwnerPaymentSourceView,
    OwnerPaymentReservationView, OwnerPaymentObligationView, OwnerPaymentComponentView,
    OwnerPaymentExecutionView, OwnerPaymentReceiptView,
)
from src.actions.contracts.bank_objects import FundingPurposeView, FinanceProductProfileView
from src.actions.contracts.qs_cost_objects import CostSource


class ContractorMeasurementWorkRecordView(ContractorWorkRecordView):
    """Host-supplied actual occurrence; availability is never a work timestamp.

    Missing occurrence remains unknown for legacy historical records. A new
    measurement requires both the real time and its observed source evidence.
    """
    occurred_at: TimePoint | None = None
    occurrence_evidence_refs: list[ref_type('Evidence')] = Field(default_factory=list)


def validate_contractor_measurement_work_events(works):
    """One actual execution event may contain several distinct work slices."""
    event_executions, execution_events = {}, {}
    for work in works:
        if not isinstance(work, ContractorWorkRecordView):
            raise ValueError('Measurement event history requires concrete original work records')
        execution = work.execution_ref.key()[:2]
        if (work.core_event_id in event_executions and event_executions[work.core_event_id] != execution
                or execution in execution_events and execution_events[execution] != work.core_event_id):
            raise ValueError('Measurement work reuses an event across commands or changes one execution event')
        event_executions[work.core_event_id] = execution
        execution_events[execution] = work.core_event_id


class ContractorMeasurementLine(StrictRecord):
    scope_ref: ScopeRef
    work_record_refs: list[ref_type('WorkRecord')]
    quantity: Measured
    valuation_basis_ref: ref_type('ValuationBasis')


class ContractorMeasurementDraft(StrictRecord):
    contract_ref: ref_type('Contract')
    measurement_window_ref: ref_type('TimeWindow')
    lines: list[ContractorMeasurementLine]
    prior_application_refs: list[ref_type('MeasurementApplication')]
    basis_refs: list[ref_type('Evidence')]


class ContractorPaymentContractView(CostSource):
    ref: ref_type('Contract')
    contractor_id: TextId
    client_id: TextId
    currency: TextId
    effective: ValueState[bool]
    settlement_rule_ref: ref_type('SettlementRule')
    measurement_application_refs: list[ref_type('MeasurementApplication')]
    measurement_history_complete: bool
    certificate_refs: list[ref_type('PaymentCertificate')]
    obligation_refs: list[ref_type('Obligation')]
    execution_refs: list[ref_type('PaymentExecution')]
    payment_history_complete: bool
    as_of: TimePoint


class ContractorSettlementRuleView(CostSource):
    ref: ref_type('SettlementRule')
    contract_ref: ref_type('Contract')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    procedure_ref: ref_type('SettlementProcedure')
    choice: Literal['apply_measurement', 'request_payment', 'authorize_payment', 'seek_finance', 'reconcile', 'dispute']
    business_key: TextId
    measurement: ContractorMeasurementDraft | None
    component_refs: list[ref_type('SettlementComponent')]
    account_ref: ref_type('Account') | None
    lines: list[OwnerPaymentAuthorizedLine]
    allow_partial: bool
    financing: FinancingApplicationDraft | None
    execution_refs: list[ref_type('PaymentExecution')]
    obligation_refs: list[ref_type('Obligation')]
    issue_refs: list[ref_type('Issue')]
    basis_refs: list[ref_type('Evidence')]
    note: TextId


class ContractorSettlementProcedureView(CostSource):
    ref: ref_type('SettlementProcedure')
    contract_ref: ref_type('Contract')
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    recipient_ids: list[TextId]
    valuation_basis_refs: list[ref_type('ValuationBasis')]


class ContractorValuationBasisView(CostSource):
    ref: ref_type('ValuationBasis')
    contract_ref: ref_type('Contract')
    quantity_unit: TextId
    effective: ValueState[bool]


class ContractorMeasurementApplicationView(CostSource):
    ref: ref_type('MeasurementApplication')
    organization_id: TextId
    business_key: TextId
    request: ContractorMeasurementDraft
    status: Literal['submitted', 'pending', 'certified', 'withdrawn', 'rejected']


class ContractorPaymentCertificateView(CostSource):
    ref: ref_type('PaymentCertificate')
    contract_ref: ref_type('Contract')
    component_refs: list[ref_type('SettlementComponent')]
    status: Literal['effective', 'superseded', 'withdrawn']


class ContractorRequestableComponentView(OwnerPaymentComponentView):
    contract_ref: ref_type('Contract')
    certificate_ref: ref_type('PaymentCertificate') | None
    requestable: ValueState[bool]


class ContractorPaymentIssueView(CostSource):
    ref: ref_type('Issue')
    contract_ref: ref_type('Contract')
    obligation_refs: list[ref_type('Obligation')]
    status: Literal['open', 'disputed', 'resolved']


def contractor_payment_schemas():
    return contractor_bid_schemas({
        'Contract': ContractorPaymentContractView, 'SettlementRule': ContractorSettlementRuleView,
        'SettlementProcedure': ContractorSettlementProcedureView,
        'WorkRecord': ContractorMeasurementWorkRecordView,
        'ValuationBasis': ContractorValuationBasisView,
        'MeasurementApplication': ContractorMeasurementApplicationView,
        'PaymentCertificate': ContractorPaymentCertificateView,
        'SettlementComponent': ContractorRequestableComponentView,
        'Account': OwnerPaymentAccountView, 'FundingSource': OwnerPaymentSourceView,
        'CashReservation': OwnerPaymentReservationView, 'Obligation': OwnerPaymentObligationView,
        'PaymentExecution': OwnerPaymentExecutionView, 'PaymentReceipt': OwnerPaymentReceiptView,
        'FundingPurpose': FundingPurposeView, 'FinanceProductProfile': FinanceProductProfileView,
        'Issue': ContractorPaymentIssueView,
    })
