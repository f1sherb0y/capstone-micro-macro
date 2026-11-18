"""Explicit branch field assignments from the Bank action cards."""

BRANCH_FIELDS = {
    "BANK-A01": [("revise_strategy", "strategy_ref:Ref<LendingStrategyProfile>"), ("investigate", "issue_refs:List<Ref<Issue>>,scope_ref:ScopeRef")],
    "BANK-A02": [("accept_for_review", "product_ref:Ref<FinanceProductProfile>,required_condition_refs:List<Ref<Requirement>>")],
    "BANK-A03": [],
    "BANK-A04": [("offer/conditional_offer", "terms:BankTermDraft,reservation_policy_ref:Ref<ReservationPolicy>")],
    "BANK-A05": [("confirm", "offer_ref:Ref<FinanceOffer>,acceptance_ref:Ref<PartyAcceptance>,conditions:List<BankCondition>"), ("requote", "affected_requirement_refs:List<Ref<Requirement>>")],
    "BANK-A06": [("approve_draw", "approved_amount:Money,transfer_lines:List<BankTransferLine>")],
    "BANK-A07": [("execute", "approval_ref:Ref<DrawApproval>,path_ref:Ref<FundingPath>,lines:List<BankTransferLine>"), ("reconcile/cancel_unexecuted", "execution_refs:List<Ref<PaymentExecution>>")],
    "BANK-A08": [("issue_notice/restrict_scope/release_restriction", "covenant_ref:Ref<Covenant>,affected_scope:ScopeRef,basis_refs:List<Ref<Evidence>>"), ("request_evidence", "requirement_refs:List<Ref<Requirement>>")],
    "BANK-A09": [("calculate_due/correct_accrual", "calculation_profile_ref:Ref<DebtCalculationProfile>,basis_refs:List<Ref<CommittedEvidence>>"), ("allocate_receipt", "allocations:List<BankAllocation>"), ("reconcile", "execution_refs:List<Ref<PaymentExecution>>")],
    "BANK-A10": [("propose_restructure", "revised_terms:BankTermDraft"), ("accept_restructure", "proposal_ref:Ref<RestructureProposal>,acceptance_refs:List<Ref<PartyAcceptance>>"), ("enforce", "scope_ref:ScopeRef,right_refs:List<Ref<EnforcementRight>>"), ("accounting_writeoff", "scope_ref:ScopeRef,authority_ref:Ref<Authorization>,accounting_policy_ref:Ref<WriteoffPolicy>"), ("request_remedy", "required_items:List<BankRemedyRequirementDraft>,response_window_ref:Ref<TimeWindow>"), ("decline_remedy", "proposal_ref:Ref<RemedyProposal>")],
    "BANK-A11": [],
    "BANK-A12": [("record_lesson", "affected_dimension_refs:List<Ref<RiskDimension>>"), ("revise_strategy", "strategy_ref:Ref<LendingStrategyProfile>")],
    "BANK-A13": [("indicative_opinion", "basis:BankAdviceBasis,range:BankIndicativeRange,findings:List<BankFinding>,conditions:List<BankCondition>,permitted_use_ref:Ref<PermittedUse>,unresolved_refs:List<Ref<Issue>>")],
}
