"""Partial finance closure preserves original balances, pending effects and security."""
from typing import Literal

from src.actions.contracts.common import Money, Reference, ScopeRef, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.bank_debt_objects import BankDebtComponentView, BankDebtExecutionView, BankDebtReceiptView
from src.actions.contracts.owner_continuation_objects import OwnerContinuationSourceDigest
from src.actions.contracts.qs_cost_objects import CostSource


class BankCloseoutArrangementView(CostSource):
    ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    currency: TextId
    closeout_profile_ref: ref_type('FinanceCloseoutProfile')
    rule_ref: ref_type('FinanceCloseoutRule')
    commitment_refs: list[ref_type('Commitment')]
    debt_refs: list[ref_type('DebtComponent')]
    payment_execution_refs: list[ref_type('PaymentExecution')]
    security_refs: list[ref_type('SecurityRight')]
    issue_refs: list[ref_type('FinanceIssue')]
    remaining_obligation_refs: list[ref_type('RemainingObligation')]
    closeout_execution_refs: list[ref_type('FinanceCloseoutExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint
    producer: Literal['core']


class BankCloseoutProfileView(CostSource):
    ref: ref_type('FinanceCloseoutProfile')
    arrangement_ref: ref_type('FinanceArrangement')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['retain','close_unused','close_cleared_scope']
    business_key: TextId
    scope_ref: ScopeRef
    release_candidate_refs: list[ref_type('Commitment')]
    security_close_refs: list[ref_type('SecurityRight')]
    basis_refs: list[ref_type('Evidence')]
    note: TextId


class BankCloseoutRuleView(GovReviewAuthored):
    ref: ref_type('FinanceCloseoutRule')
    arrangement_ref: ref_type('FinanceArrangement')
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    verification_refs: list[ref_type('FinanceCloseoutVerification')]


class BankCloseoutDebtView(BankDebtComponentView):
    physical_component_key: TextId
    actual_offset: Money
    outstanding_balance: ValueState[Money]
    accrual_complete_through: TimePoint
    as_of: TimePoint


class BankCloseoutCommitmentView(CostSource):
    ref: ref_type('Commitment')
    arrangement_ref: ref_type('FinanceArrangement')
    lender_id: TextId
    physical_commitment_key: TextId
    unused_amount: ValueState[Money]
    expiry_at: TimePoint
    release_rule_ref: ref_type('CommitmentCloseRule')
    execution_refs: list[ref_type('PaymentExecution')]
    status: Literal['active','closed','unknown']
    as_of: TimePoint


class BankCommitmentCloseRuleView(GovReviewAuthored):
    ref: ref_type('CommitmentCloseRule')
    commitment_ref: ref_type('Commitment')
    permitted: ValueState[bool]
    trigger: Literal['expired','authorized_revocation','cleared_scope']
    verification_refs: list[ref_type('FinanceCloseoutVerification')]


class BankCloseoutSecurityView(GovReviewAuthored):
    ref: ref_type('SecurityRight')
    arrangement_ref: ref_type('FinanceArrangement')
    holder_id: TextId
    debt_refs: list[ref_type('DebtComponent')]
    release_verification_refs: list[ref_type('FinanceCloseoutVerification')]
    status: Literal['active','released','unknown']


class BankCloseoutIssueView(CostSource):
    ref: ref_type('FinanceIssue')
    arrangement_ref: ref_type('FinanceArrangement')
    subject_refs: list[Reference]
    status: Literal['open','unknown','resolved']


class BankRemainingObligationView(CostSource):
    ref: ref_type('RemainingObligation')
    arrangement_ref: ref_type('FinanceArrangement')
    source_ref: ref_type('DebtComponent') | ref_type('Commitment') | ref_type('PaymentExecution') | ref_type('SecurityRight') | ref_type('FinanceIssue')
    source_sha256: Digest
    producer: Literal['core']
    as_of: TimePoint


class BankCloseoutVerificationView(GovReviewAuthored):
    ref: ref_type('FinanceCloseoutVerification')
    arrangement_ref: ref_type('FinanceArrangement')
    choice: Literal['close_unused','close_cleared_scope']
    target_ref: Reference
    checked_scope: ScopeRef
    supported: ValueState[bool]
    status: Literal['ok','unknown','failed','unsupported']
    source_digests: list[OwnerContinuationSourceDigest]
    as_of: TimePoint


class BankCloseoutExecutionView(CostSource):
    ref: ref_type('FinanceCloseoutExecution')
    arrangement_ref: ref_type('FinanceArrangement')
    organization_id: TextId
    run_id: TextId
    business_key: TextId
    profile_ref: ref_type('FinanceCloseoutProfile')
    profile_sha256: Digest
    affected_scope: ScopeRef
    status: Literal['pending','unknown','succeeded','failed','rejected']


def bank_closeout_schemas():
    return contractor_bid_schemas({
        'FinanceArrangement':BankCloseoutArrangementView,'FinanceCloseoutProfile':BankCloseoutProfileView,
        'FinanceCloseoutRule':BankCloseoutRuleView,'DebtComponent':BankCloseoutDebtView,
        'Commitment':BankCloseoutCommitmentView,'CommitmentCloseRule':BankCommitmentCloseRuleView,
        'SecurityRight':BankCloseoutSecurityView,'FinanceIssue':BankCloseoutIssueView,
        'RemainingObligation':BankRemainingObligationView,'FinanceCloseoutVerification':BankCloseoutVerificationView,
        'FinanceCloseoutExecution':BankCloseoutExecutionView,'PaymentExecution':BankDebtExecutionView,'VerifiedReceipt':BankDebtReceiptView,
    })
