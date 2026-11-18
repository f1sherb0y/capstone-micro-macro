"""Original contract final-account histories and independent decision mechanisms."""
from typing import Literal

from src.actions.contracts.common import Money, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_change_objects import QSChangeEntitlementView, QSChangeClaimView
from src.actions.contracts.qs_payment_objects import QSPaymentContractView, QSPaymentCertificateView, QSPaymentStatementView, QSPaymentReceiptView, QSPaymentExecutionView
from src.actions.contracts.qs_cost_objects import CostSource
from src.methods.qs_final_account import FinalAccountInput, FinalAccountReport


class QSFinalContractView(QSPaymentContractView):
    base_component_key: TextId
    base_amount: ValueState[Money]
    final_profile_ref: ref_type('FinalAccountProfile')
    determined_change_refs: list[ref_type('EntitlementDecision')]
    all_certificate_refs: list[ref_type('Certificate')]
    unresolved_claim_refs: list[ref_type('ChangeClaim')]
    payment_execution_refs: list[ref_type('PaymentExecution')]
    adjustment_refs: list[ref_type('FinalAccountAdjustment')]
    execution_refs: list[ref_type('FinalAccountExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class QSFinalProfileView(GovReviewAuthored):
    ref: ref_type('FinalAccountProfile')
    contract_ref: ref_type('Contract')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['propose_account','request_evidence','determine_authorized']
    business_key: TextId
    question_refs: list[ref_type('EvidenceTarget')]
    determination_basis_ref: ref_type('DeterminationBasis') | None


class QSFinalEntitlementView(QSChangeEntitlementView):
    component_key: TextId
    direction: Literal['increase','decrease','signed']


class QSFinalEntitlementAuthorityView(GovReviewAuthored):
    ref: ref_type('Authority')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    permitted: ValueState[bool]
    effect: Literal['original_entitlement_decision_only']


class QSFinalCashExecutionView(QSPaymentExecutionView):
    run_id: TextId
    status: Literal['pending','unknown','verified','failed','rejected']
    as_of: TimePoint


class QSFinalAdjustmentView(GovReviewAuthored):
    ref: ref_type('FinalAccountAdjustment')
    contract_ref: ref_type('Contract')
    component_key: TextId
    kind: Literal['price_deduction','payment_setoff','verified_refund']
    amount: ValueState[Money]
    authority_ref: ref_type('FinalAccountAdjustmentBasis')
    event_key: TextId
    status: Literal['applied','unknown']
    as_of: TimePoint


class QSFinalAdjustmentBasisView(GovReviewAuthored):
    ref: ref_type('FinalAccountAdjustmentBasis')
    contract_ref: ref_type('Contract')
    adjustment_ref: ref_type('FinalAccountAdjustment')
    adjustment_sha256: TextId
    kind: Literal['price_deduction','payment_setoff','verified_refund']
    permitted: ValueState[bool]
    mechanism_ref: ref_type('SettlementMechanism')
    effect: Literal['independently_applied_original_adjustment']


class QSFinalResultView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    contract_ref: ref_type('Contract')
    method_ref: ref_type('Method')
    input_sha256: TextId
    data: FinalAccountInput
    report: FinalAccountReport | None
    executed_at: TimePoint
    status: Literal['ok','unknown','failed','unsupported']


class QSFinalDeterminationView(GovReviewAuthored):
    ref: ref_type('DeterminationBasis')
    contract_ref: ref_type('Contract')
    reconciliation_result_ref: ref_type('MethodResult')
    account_sha256: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    permitted: ValueState[bool]
    mechanism_ref: ref_type('SettlementMechanism')
    covered_component_keys: list[TextId]
    excluded_claim_refs: list[ref_type('ChangeClaim')]
    effect: Literal['covered_final_price_only']


class QSFinalMechanismView(GovReviewAuthored):
    ref: ref_type('SettlementMechanism')
    contract_ref: ref_type('Contract')
    decision_actor_id: TextId
    decision_function_ref: ref_type('FunctionAssignment')
    decision_action_id: TextId
    decision_at: TimePoint
    authorization_ref: ref_type('Authorization')
    purpose: Literal['final_price','price_deduction','payment_setoff','verified_refund']
    permitted: ValueState[bool]
    mode: Literal['all_parties','contract_delegated','external_determination']
    power_basis_ref: ref_type('SettlementPowerBasis') | None
    party_consent_refs: list[ref_type('SettlementConsent')]
    required_party_ids: list[TextId]


class QSFinalPowerBasisView(GovReviewAuthored):
    ref: ref_type('SettlementPowerBasis')
    contract_ref: ref_type('Contract')
    mechanism_ref: ref_type('SettlementMechanism')
    decision_actor_id: TextId
    decision_function_ref: ref_type('FunctionAssignment')
    issuer_actor_id: TextId
    mode: Literal['contract_delegated','external_determination']
    permitted: ValueState[bool]
    verified: ValueState[bool]


class QSFinalConsentView(GovReviewAuthored):
    ref: ref_type('SettlementConsent')
    contract_ref: ref_type('Contract')
    mechanism_ref: ref_type('SettlementMechanism')
    party_id: TextId
    accepted: ValueState[bool]


class QSFinalQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    contract_ref: ref_type('Contract')
    question: TextId
    recipient_ids: list[TextId]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSFinalResponseView(CostSource):
    ref: ref_type('ResponseRequirement')
    contract_ref: ref_type('Contract')
    recipient_ids: list[TextId]


class QSFinalExecutionView(CostSource):
    ref: ref_type('FinalAccountExecution')
    contract_ref: ref_type('Contract')
    run_id: TextId
    business_key: TextId
    profile_ref: ref_type('FinalAccountProfile')
    profile_sha256: TextId
    reconciliation_result_ref: ref_type('MethodResult') | None
    status: Literal['pending','unknown','succeeded','failed','rejected']


class QSFinalAccount(StrictRecord):
    contract_ref: ref_type('Contract')
    reconciliation_result_ref: ref_type('MethodResult')
    determined_total: ValueState[Money]
    certified_total: ValueState[Money]
    paid_total: ValueState[Money]
    unsettled_amount: ValueState[Money]
    unresolved_claim_refs: list[ref_type('ChangeClaim')]
    source_statement_refs: list[ref_type('ValuationStatement')]


def qs_final_account_schemas():
    return contractor_bid_schemas({'Contract':QSFinalContractView,'FinalAccountProfile':QSFinalProfileView,
        'EntitlementDecision':QSFinalEntitlementView,'Authority':QSFinalEntitlementAuthorityView,
        'Certificate':QSPaymentCertificateView,'ValuationStatement':QSPaymentStatementView,'ChangeClaim':QSChangeClaimView,
        'PaymentReceipt':QSPaymentReceiptView,'PaymentExecution':QSFinalCashExecutionView,
        'FinalAccountAdjustment':QSFinalAdjustmentView,'FinalAccountAdjustmentBasis':QSFinalAdjustmentBasisView,
        'MethodResult':QSFinalResultView,'DeterminationBasis':QSFinalDeterminationView,
        'SettlementMechanism':QSFinalMechanismView,'SettlementConsent':QSFinalConsentView,'SettlementPowerBasis':QSFinalPowerBasisView,
        'EvidenceTarget':QSFinalQuestionView,'ResponseRequirement':QSFinalResponseView,'FinalAccountExecution':QSFinalExecutionView})
