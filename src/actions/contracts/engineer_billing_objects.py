"""Original external billing proposals; internal costs and cash remain separate."""
from typing import Annotated, Literal

from pydantic import Field, model_serializer

from src.actions.contracts.common import DecimalString, Measured, Money, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.engineer_planning_objects import EngineerPlanningWorkFactView
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.service_objects import service_intake_schemas


class EngineerBillingEngagementView(CostSource):
    ref: ref_type('Engagement')
    organization_id: TextId
    client_id: TextId
    payer_id: TextId
    payer_organization_id: TextId
    contract_ref: ref_type('Contract')
    relation: Literal['external', 'internal']
    billing_clause_refs: list[ref_type('BillingClause')]
    billing_profile_ref: ref_type('BillingProfile')
    work_fact_refs: list[ref_type('WorkFact')]
    advance_credit_refs: list[ref_type('AdvanceCredit')]
    payable_obligation_refs: list[ref_type('Obligation')]
    claim_refs: list[ref_type('FeeClaim')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    cost_accounting_ref: ref_type('WorkCostAccounting') | None = None

    @model_serializer(mode='wrap')
    def preserve_original_projection(self, handler):
        result = handler(self)
        if self.cost_accounting_ref is None:
            result.pop('cost_accounting_ref', None)
        return result


class EngineerBillingCostAccountingLine(StrictRecord):
    """One independently posted native work investment."""
    work_fact_ref: ref_type('WorkFact')
    work_fact_sha256: Digest
    investment_key: TextId
    posting_key: TextId
    posted_at: TimePoint
    effort: Measured
    internal_cost: Money


class EngineerBillingCostAccountingView(CostSource):
    """Observed internal cost postings, separate from fees and received cash."""
    ref: ref_type('WorkCostAccounting')
    run_id: TextId
    organization_id: TextId
    engagement_ref: ref_type('Engagement')
    native_service_id: TextId
    ledger_key: TextId
    posting_authority_evidence_refs: list[ref_type('Evidence')]
    lines: list[EngineerBillingCostAccountingLine]
    totals: list[Money]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    status: Literal['posted', 'pending', 'unknown', 'failed']


class EngineerBillingProfileView(CostSource):
    ref: ref_type('BillingProfile')
    engagement_ref: ref_type('Engagement')
    authority_ref: ref_type('Authorization')
    choice: Literal['claim', 'correct', 'dispute', 'reconcile', 'remind']
    billing_key: TextId
    advance_credit_refs: list[ref_type('AdvanceCredit')]
    work_fact_refs: list[ref_type('WorkFact')]
    dispute_question_ref: ref_type('EvidenceTarget') | None
    reminder_recipient_id: TextId | None
    correction_basis_refs: list[ref_type('Evidence')]
    note: TextId


class EngineerBillingClauseView(CostSource):
    ref: ref_type('BillingClause')
    engagement_ref: ref_type('Engagement')
    contract_ref: ref_type('Contract')
    payer_id: TextId
    mode: Literal['fixed', 'effort', 'milestone', 'advance']
    fixed_amount: Money | None
    unit_rate: Money | None
    effort_unit: TextId | None
    minimum_effort: DecimalString
    currency: TextId
    conditions_satisfied: ValueState[bool]
    condition_evidence_refs: list[ref_type('Evidence')]
    eligible_work_fact_refs: list[ref_type('WorkFact')]
    minor_places: Annotated[int, Field(ge=0, le=8)]
    allowed_correction: bool
    cumulative_limit: Money
    reminder_recipient_ids: list[TextId]


class EngineerBillingWorkFactView(EngineerPlanningWorkFactView):
    engagement_ref: ref_type('Engagement')


class EngineerBillingCalculationView(CostSource):
    ref: ref_type('FeeCalculation')
    engagement_ref: ref_type('Engagement')
    billing_clause_ref: ref_type('BillingClause')
    billing_key: TextId
    advance_credit_refs: list[ref_type('AdvanceCredit')]
    work_fact_refs: list[ref_type('WorkFact')]
    prior_claim_ref: ref_type('FeeClaim') | None
    amount: Money
    executed_at: TimePoint
    status: Literal['succeeded', 'failed', 'unknown', 'unsupported']
    method: Literal['declared_fixed_or_effort_half_even_v1', 'declared_fixed_or_effort_with_sourced_advance_credit_half_even_v1']


class EngineerBillingClaimView(CostSource):
    ref: ref_type('FeeClaim')
    engagement_ref: ref_type('Engagement')
    billing_clause_ref: ref_type('BillingClause')
    payer_id: TextId
    payee_organization_id: TextId
    billing_key: TextId
    advance_credit_refs: list[ref_type('AdvanceCredit')]
    work_fact_refs: list[ref_type('WorkFact')]
    amount: Money
    actual_received: Money
    due_at: TimePoint | None
    receipt_refs: list[ref_type('PaymentReceipt')]
    recognized_event_ids: list[TextId]
    receipt_coverage: Literal['complete', 'partial', 'unknown']
    prior_claim_ref: ref_type('FeeClaim') | None
    status: Literal['submitted', 'confirmed', 'disputed', 'superseded', 'unknown', 'rejected']


class EngineerBillingReceiptView(CostSource):
    ref: ref_type('PaymentReceipt')
    claim_ref: ref_type('FeeClaim')
    engagement_ref: ref_type('Engagement')
    payer_id: TextId
    beneficiary_organization_id: TextId
    execution_ref: ref_type('PaymentExecution')
    command_id: TextId
    business_key: TextId
    event_id: TextId
    sequence: Annotated[int, Field(ge=0)]
    semantics: Literal['incremental', 'cumulative']
    amount: ValueState[Money]
    status: Literal['verified_partial', 'verified_final', 'unknown', 'failed', 'rejected']
    effective_at: TimePoint


class EngineerBillingExecutionView(CostSource):
    ref: ref_type('PaymentExecution')
    engagement_ref: ref_type('Engagement')
    claim_ref: ref_type('FeeClaim')
    payer_id: TextId
    beneficiary_organization_id: TextId
    command_id: TextId
    business_key: TextId
    receipt_refs: list[ref_type('PaymentReceipt')]


class EngineerBillingQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    engagement_ref: ref_type('Engagement')
    claim_ref: ref_type('FeeClaim')
    question: ArchitectOpportunityQuestion


class EngineerBillingAdvanceCreditView(CostSource):
    ref: ref_type('AdvanceCredit')
    engagement_ref: ref_type('Engagement')
    advance_claim_ref: ref_type('FeeClaim')
    credit_key: TextId
    billing_key: TextId | None
    amount: Money
    applied_claim_ref: ref_type('FeeClaim') | None
    status: Literal['available', 'applied', 'unknown']


class EngineerBillingPayableView(CostSource):
    ref: ref_type('Obligation')
    engagement_ref: ref_type('Engagement')
    payer_organization_id: TextId
    beneficiary_organization_id: TextId
    amount: Money
    due_at: TimePoint | None
    status: Literal['effective', 'disputed', 'settled', 'unknown']


def engineer_billing_schemas():
    return service_intake_schemas(overrides={
        'WorkCostAccounting': EngineerBillingCostAccountingView,
        'AdvanceCredit': EngineerBillingAdvanceCreditView, 'Obligation': EngineerBillingPayableView,
        'Engagement': EngineerBillingEngagementView, 'BillingProfile': EngineerBillingProfileView,
        'BillingClause': EngineerBillingClauseView, 'WorkFact': EngineerBillingWorkFactView,
        'FeeCalculation': EngineerBillingCalculationView, 'FeeClaim': EngineerBillingClaimView,
        'PaymentReceipt': EngineerBillingReceiptView, 'PaymentExecution': EngineerBillingExecutionView,
        'EvidenceTarget': EngineerBillingQuestionView,
    })
