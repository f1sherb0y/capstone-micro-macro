"""Original batch draw conditions, facility usage and proposed transfer identities."""
from typing import Literal

from src.actions.contracts.common import Money, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.bank_objects import FundingPurposeView
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.models import Digest


class BankDrawTransferLine(StrictRecord):
    obligation_refs: list[ref_type('Obligation')]
    beneficiary_id: TextId
    destination_ref: ref_type('Account')
    requested: Money
    fee_rule_refs: list[ref_type('FeeRule')]


class BankDrawRequestView(CostSource):
    ref: ref_type('DrawRequest')
    borrower_id: TextId
    lender_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    terms_ref: ref_type('FinanceTerms')
    purpose_ref: ref_type('FundingPurpose')
    requested_amount: Money
    transfer_lines: list[BankDrawTransferLine]
    condition_refs: list[ref_type('Requirement')]
    decision_profile_ref: ref_type('DrawDecisionProfile')
    batch_key: TextId
    status: Literal['submitted', 'withdrawn', 'superseded']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['OWN-A06', 'CONTRACTOR-A10', 'SUPPLIER-A10']


class OwnerDrawConditionRelation(StrictRecord):
    original_ref: ref_type('Requirement')
    original_sha256: Digest
    received_ref: ref_type('Requirement')
    received_sha256: Digest


class OwnerDrawRequestReceiptView(CostSource):
    """Observed original Owner draw request received by the bank, without approval."""
    ref: ref_type('OwnerDrawRequestReceipt')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    source_task_sha256: Digest
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    owner_draw_authorization_ref: ref_type('DrawAuthorization')
    owner_draw_authorization_sha256: Digest
    draw_request_ref: ref_type('DrawRequest')
    draw_request_sha256: Digest
    transfer_lines: list[BankDrawTransferLine]
    condition_relations: list[OwnerDrawConditionRelation]
    received_at: TimePoint
    native_record_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class BankDrawDecisionView(CostSource):
    ref: ref_type('DrawDecisionProfile')
    organization_id: TextId
    draw_request_ref: ref_type('DrawRequest')
    authority_ref: ref_type('Authorization')
    choice: Literal['approve_draw', 'decline_draw']
    approved_amount: Money | None
    transfer_lines: list[BankDrawTransferLine]
    note: TextId


class BankDrawArrangementView(CostSource):
    ref: ref_type('FinanceArrangement')
    borrower_id: TextId
    lender_id: TextId
    terms_ref: ref_type('FinanceTerms')
    status: Literal['active', 'signed_pending', 'suspended', 'expired', 'closed']
    formation_condition_refs: list[ref_type('Requirement')]
    first_draw_condition_refs: list[ref_type('Requirement')]
    each_draw_condition_refs: list[ref_type('Requirement')]
    continuing_condition_refs: list[ref_type('Requirement')]


class BankDrawTermsView(CostSource):
    ref: ref_type('FinanceTerms')
    arrangement_ref: ref_type('FinanceArrangement')
    borrower_id: TextId
    lender_id: TextId
    facility_limit: Money
    revolving: bool
    draw_window: TimeWindow
    allowed_purpose_codes: list[TextId]
    allowed_region_ids: list[TextId]
    allowed_beneficiary_ids: list[TextId]
    allowed_fee_rule_refs: list[ref_type('FeeRule')]
    allow_partial: bool
    principal_basis: Literal['net_transfers', 'transfers_plus_capitalized_fees']


class BankDrawCapacityView(CostSource):
    ref: ref_type('DrawCapacity')
    arrangement_ref: ref_type('FinanceArrangement')
    lender_id: TextId
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    approved_batch_refs: list[ref_type('DrawBatch')]
    reinstatement_refs: list[ref_type('CreditReinstatement')]
    execution_refs: list[ref_type('PaymentExecution')]


class BankDrawBatchView(CostSource):
    ref: ref_type('DrawBatch')
    arrangement_ref: ref_type('FinanceArrangement')
    draw_request_ref: ref_type('DrawRequest')
    lender_id: TextId
    batch_key: TextId
    approved_amount: Money
    released_amount: Money
    executed_principal: Money
    release_basis_ref: ref_type('Evidence') | None
    release_receipt_refs: list[ref_type('PaymentReceipt')]
    execution_refs: list[ref_type('PaymentExecution')]


class BankDrawReinstatementView(CostSource):
    ref: ref_type('CreditReinstatement')
    arrangement_ref: ref_type('FinanceArrangement')
    lender_id: TextId
    amount: Money
    receipt_ref: ref_type('PaymentReceipt')
    authorized: ValueState[bool]


class BankDrawExecutionView(CostSource):
    ref: ref_type('PaymentExecution')
    lender_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    batch_ref: ref_type('DrawBatch')
    draw_request_ref: ref_type('DrawRequest')
    command_id: TextId
    amount: Money
    status: Literal['unknown', 'pending', 'succeeded', 'failed', 'rejected']
    receipt_ref: ref_type('PaymentReceipt') | None


class BankDrawReceiptView(CostSource):
    ref: ref_type('PaymentReceipt')
    arrangement_ref: ref_type('FinanceArrangement')
    lender_id: TextId
    batch_ref: ref_type('DrawBatch') | None
    command_id: TextId
    amount: Money
    kind: Literal['draw', 'principal_repayment', 'draw_cancelled']
    status: Literal['succeeded', 'failed', 'rejected']


class BankDrawConditionView(CostSource):
    ref: ref_type('Requirement')
    arrangement_ref: ref_type('FinanceArrangement')
    draw_request_ref: ref_type('DrawRequest') | None
    stage: Literal['formation', 'first_draw', 'each_draw', 'continuing', 'batch']
    responsible_id: TextId
    dependency_refs: list[ref_type('Requirement')]
    outcome: ValueState[bool]
    verifier_organization_id: TextId
    verifier_actor_id: TextId
    verifier_function_ref: ref_type('FunctionAssignment')
    verifier_authority_ref: ref_type('Authorization')
    verifier_action_id: TextId
    permitted_verifier_ids: list[TextId]
    permitted_verifier_action_ids: list[TextId]
    verified_at: TimePoint
    verification_evidence_refs: list[ref_type('Evidence')]


class BankDrawDestinationView(CostSource):
    ref: ref_type('Account')
    organization_id: TextId
    currency: TextId
    permitted_arrangement_refs: list[ref_type('FinanceArrangement')]
    available: ValueState[bool]


class BankDrawObligationView(CostSource):
    ref: ref_type('Obligation')
    borrower_id: TextId
    payee_id: TextId
    purpose_ref: ref_type('FundingPurpose')
    unpaid_amount: ValueState[Money]
    payable: ValueState[bool]


class BankDrawFeeRuleView(CostSource):
    ref: ref_type('FeeRule')
    arrangement_ref: ref_type('FinanceArrangement')
    destination_ref: ref_type('Account')
    basis: Literal['capitalized', 'separate_cash']
    fixed_amount: Money


def bank_draw_schemas():
    registry = common_projection_schemas()
    schemas = {
        'DrawRequest': BankDrawRequestView, 'DrawDecisionProfile': BankDrawDecisionView,
        'OwnerDrawRequestReceipt': OwnerDrawRequestReceiptView,
        'FinanceArrangement': BankDrawArrangementView, 'FinanceTerms': BankDrawTermsView,
        'DrawCapacity': BankDrawCapacityView, 'DrawBatch': BankDrawBatchView,
        'CreditReinstatement': BankDrawReinstatementView, 'PaymentExecution': BankDrawExecutionView,
        'PaymentReceipt': BankDrawReceiptView, 'Requirement': BankDrawConditionView,
        'Account': BankDrawDestinationView, 'Obligation': BankDrawObligationView,
        'FeeRule': BankDrawFeeRuleView, 'FundingPurpose': FundingPurposeView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView, 'ClockProfile': ServiceClockView,
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
