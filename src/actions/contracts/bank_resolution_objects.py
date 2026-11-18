"""Debt-resolution proposals retain old balances and independent legal gates."""
from typing import Literal

from src.actions.contracts.common import Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_financing_objects import FinancingTerms
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.actions.contracts.bank_debt_objects import BankDebtExecutionView, BankDebtReceiptView
from src.actions.contracts.qs_cost_objects import CostSource


class BankResolutionArrangementView(CostSource):
    ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    currency: TextId
    rule_ref: ref_type('DebtResolutionRule')
    notice_refs: list[ref_type('DefaultNotice')]
    obligation_refs: list[ref_type('Obligation')]
    security_refs: list[ref_type('SecurityRight')]
    remedy_refs: list[ref_type('RemedyProposal')]
    payment_execution_refs: list[ref_type('PaymentExecution')]
    resolution_execution_refs: list[ref_type('DebtResolutionExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class BankResolutionObligationView(OwnerPaymentObligationView):
    arrangement_ref: ref_type('FinanceArrangement')


class BankRemedyItem(StrictRecord):
    local_key: TextId
    scope_ref: ScopeRef
    requirement_ref: ref_type('Requirement')
    basis_refs: list[ref_type('Evidence')]
    responsible_id: TextId


class BankResolutionProfileView(CostSource):
    ref: ref_type('DebtResolutionProfile')
    arrangement_ref: ref_type('FinanceArrangement')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['request_remedy','propose_restructure','accept_restructure','enforce','accounting_writeoff','decline_remedy']
    business_key: TextId
    basis_refs: list[ref_type('Evidence')]
    difficulty_ref: ref_type('DebtDifficultyAssessment') | None
    proposal_ref: ref_type('RestructureProposal') | None
    declined_remedy_ref: ref_type('RemedyProposal') | None
    acceptance_refs: list[ref_type('PartyAcceptance')]
    enforcement_right_refs: list[ref_type('EnforcementRight')]
    affected_scope: ScopeRef
    writeoff_policy_ref: ref_type('WriteoffPolicy') | None
    required_items: list[BankRemedyItem]
    response_window_ref: ref_type('TimeWindow') | None
    note: TextId


class BankResolutionRuleView(GovReviewAuthored):
    ref: ref_type('DebtResolutionRule')
    arrangement_ref: ref_type('FinanceArrangement')
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    required_party_ids: list[TextId]
    allowed_product_refs: list[ref_type('FinanceProductProfile')]
    allowed_pricing_refs: list[ref_type('PricingRule')]
    allowed_fee_refs: list[ref_type('FeeRule')]
    allowed_repayment_refs: list[ref_type('RepaymentRule')]
    maximum_principal_limit: Money
    require_notice_for_enforcement: bool
    require_expired_remedy_for_enforcement: bool


class BankDifficultyView(GovReviewAuthored):
    ref: ref_type('DebtDifficultyAssessment')
    arrangement_ref: ref_type('FinanceArrangement')
    kind: Literal['difficulty','contract_breach']
    obligation_refs: list[ref_type('Obligation')]
    supported: ValueState[bool]
    source_refs: list[Reference]
    status: Literal['ok','unknown','failed','unsupported']


class BankDefaultNoticeView(GovReviewAuthored):
    ref: ref_type('DefaultNotice')
    arrangement_ref: ref_type('FinanceArrangement')
    obligation_refs: list[ref_type('Obligation')]
    basis_kind: Literal['actual_due_unpaid','verified_contract_breach','risk_estimate']
    breach_assessment_ref: ref_type('DebtDifficultyAssessment') | None
    confirmed_default: ValueState[bool]
    delivery: Literal['verified_served','pending','unknown']
    served_at: TimePoint | None
    grace_deadline: TimePoint
    remedy_deadline: TimePoint
    status: Literal['active','withdrawn','resolved']


class BankSecurityRightView(GovReviewAuthored):
    ref: ref_type('SecurityRight')
    arrangement_ref: ref_type('FinanceArrangement')
    holder_id: TextId
    permitted: ValueState[bool]


class BankEnforcementRightView(GovReviewAuthored):
    ref: ref_type('EnforcementRight')
    arrangement_ref: ref_type('FinanceArrangement')
    security_ref: ref_type('SecurityRight')
    mechanism_ref: ref_type('EnforcementMechanism')
    notice_refs: list[ref_type('DefaultNotice')]
    permitted: ValueState[bool]
    procedure_satisfied: ValueState[bool]
    procedure_assessment_ref: ref_type('DebtDifficultyAssessment')


class BankEnforcementMechanismView(CostSource):
    ref: ref_type('EnforcementMechanism')
    supported: ValueState[bool]
    mode: Literal['modeled','external','uncovered']
    procedure_basis_refs: list[ref_type('Evidence')]


class BankRemedyProposalView(GovReviewAuthored):
    ref: ref_type('RemedyProposal')
    arrangement_ref: ref_type('FinanceArrangement')
    status: Literal['received','pending','accepted','rejected','withdrawn']


class BankResolutionRequirementView(GovReviewAuthored):
    ref: ref_type('Requirement')
    arrangement_ref: ref_type('FinanceArrangement')
    responsible_id: TextId
    permitted: ValueState[bool]
    satisfied: ValueState[bool]


class BankDebtCarryLine(StrictRecord):
    obligation_ref: ref_type('Obligation')
    obligation_sha256: Digest
    old_remaining: Money
    carry_amount: Money
    adjustment_amount: Money
    adjustment_kind: Literal['none','increase','decrease']
    basis_refs: list[ref_type('Evidence')]


class BankRestructureProposalView(GovReviewAuthored):
    ref: ref_type('RestructureProposal')
    arrangement_ref: ref_type('FinanceArrangement')
    revised_terms: FinancingTerms
    carry_lines: list[BankDebtCarryLine]
    effective_at: TimePoint
    status: Literal['proposal','pending','agreed','withdrawn']


class BankRestructureAcceptanceView(GovReviewAuthored):
    ref: ref_type('PartyAcceptance')
    proposal_ref: ref_type('RestructureProposal')
    proposal_sha256: Digest
    party_id: TextId
    accepted: ValueState[bool]
    status: Literal['active','withdrawn']


class BankWriteoffPolicyView(GovReviewAuthored):
    ref: ref_type('WriteoffPolicy')
    organization_id: TextId
    arrangement_refs: list[ref_type('FinanceArrangement')]
    obligation_refs: list[ref_type('Obligation')]
    permitted: ValueState[bool]
    classification: Literal['accounting_only_no_debt_forgiveness']


class BankResolutionExecutionView(CostSource):
    ref: ref_type('DebtResolutionExecution')
    arrangement_ref: ref_type('FinanceArrangement')
    organization_id: TextId
    run_id: TextId
    business_key: TextId
    profile_ref: ref_type('DebtResolutionProfile')
    profile_sha256: Digest
    status: Literal['pending','unknown','succeeded','failed','rejected']


class BankResolutionTermSourceView(CostSource):
    ref: Reference
    arrangement_ref: ref_type('FinanceArrangement')
    permitted: ValueState[bool]


def bank_resolution_schemas():
    return contractor_bid_schemas({
        'FinanceArrangement':BankResolutionArrangementView,'DebtResolutionProfile':BankResolutionProfileView,
        'DebtResolutionRule':BankResolutionRuleView,'Obligation':BankResolutionObligationView,
        'DebtDifficultyAssessment':BankDifficultyView,'DefaultNotice':BankDefaultNoticeView,
        'SecurityRight':BankSecurityRightView,'EnforcementRight':BankEnforcementRightView,
        'EnforcementMechanism':BankEnforcementMechanismView,'RemedyProposal':BankRemedyProposalView,
        'Requirement':BankResolutionRequirementView,'RestructureProposal':BankRestructureProposalView,
        'PartyAcceptance':BankRestructureAcceptanceView,'WriteoffPolicy':BankWriteoffPolicyView,
        'DebtResolutionExecution':BankResolutionExecutionView,'PaymentExecution':BankDebtExecutionView,
        'VerifiedReceipt':BankDebtReceiptView,
        **{kind:BankResolutionTermSourceView for kind in ('FinanceProductProfile','FundingPurpose','PricingRule','FeeRule','RepaymentRule')},
    })
