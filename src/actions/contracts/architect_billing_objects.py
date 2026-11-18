"""Original external billing proposals; internal costs and cash remain separate."""
from typing import Annotated, Literal

from pydantic import Field, model_serializer

from src.actions.contracts.common import DecimalString, Measured, Money, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_planning_objects import ArchitectPlanningWorkFactView
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.service_objects import service_intake_schemas
from src.actions.contracts.architect_review_objects import Digest


class ArchitectBillingEngagementView(CostSource):
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


class ArchitectBillingCostAccountingLine(StrictRecord):
    """One native posted investment; the action never writes this line."""
    work_fact_ref: ref_type('WorkFact')
    work_fact_sha256: Digest
    investment_key: TextId
    posting_key: TextId
    posted_at: TimePoint
    effort: Measured
    internal_cost: Money


class ArchitectBillingCostAccountingView(CostSource):
    """Observed native cost ledger coverage, separate from fee and cash recognition."""
    ref: ref_type('WorkCostAccounting')
    run_id: TextId
    organization_id: TextId
    engagement_ref: ref_type('Engagement')
    native_service_id: TextId
    ledger_key: TextId
    posting_authority_evidence_refs: list[ref_type('Evidence')]
    lines: list[ArchitectBillingCostAccountingLine]
    totals: list[Money]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    status: Literal['posted', 'pending', 'unknown', 'failed']


class ArchitectBillingProfileView(CostSource):
    ref: ref_type('BillingProfile')
    engagement_ref: ref_type('Engagement')
    authority_ref: ref_type('Authorization')
    choice: Literal['claim', 'correct', 'dispute', 'reconcile', 'remind']
    billing_key: TextId
    work_fact_refs: list[ref_type('WorkFact')]
    dispute_question_ref: ref_type('EvidenceTarget') | None
    reminder_recipient_id: TextId | None
    correction_basis_refs: list[ref_type('Evidence')]
    note: TextId


class ArchitectBillingClauseView(CostSource):
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


class ArchitectBillingWorkFactView(ArchitectPlanningWorkFactView):
    engagement_ref: ref_type('Engagement')


class ArchitectBillingCalculationView(CostSource):
    ref: ref_type('FeeCalculation')
    engagement_ref: ref_type('Engagement')
    billing_clause_ref: ref_type('BillingClause')
    billing_key: TextId
    work_fact_refs: list[ref_type('WorkFact')]
    prior_claim_ref: ref_type('FeeClaim') | None
    amount: Money
    executed_at: TimePoint
    status: Literal['succeeded', 'failed', 'unknown', 'unsupported']
    method: Literal['declared_fixed_or_effort_half_even_v1']


class ArchitectBillingClaimView(CostSource):
    ref: ref_type('FeeClaim')
    engagement_ref: ref_type('Engagement')
    billing_clause_ref: ref_type('BillingClause')
    payer_id: TextId
    payee_organization_id: TextId
    billing_key: TextId
    work_fact_refs: list[ref_type('WorkFact')]
    amount: Money
    actual_received: Money
    due_at: TimePoint | None
    receipt_refs: list[ref_type('PaymentReceipt')]
    recognized_event_ids: list[TextId]
    receipt_coverage: Literal['complete', 'partial', 'unknown']
    prior_claim_ref: ref_type('FeeClaim') | None
    status: Literal['submitted', 'confirmed', 'disputed', 'superseded', 'unknown', 'rejected']


class ArchitectBillingReceiptView(CostSource):
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


class ArchitectBillingExecutionView(CostSource):
    ref: ref_type('PaymentExecution')
    engagement_ref: ref_type('Engagement')
    claim_ref: ref_type('FeeClaim')
    payer_id: TextId
    beneficiary_organization_id: TextId
    command_id: TextId
    business_key: TextId
    receipt_refs: list[ref_type('PaymentReceipt')]


class ArchitectBillingQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    engagement_ref: ref_type('Engagement')
    claim_ref: ref_type('FeeClaim')
    question: ArchitectOpportunityQuestion


def architect_billing_schemas():
    return service_intake_schemas(overrides={
        'Engagement': ArchitectBillingEngagementView, 'BillingProfile': ArchitectBillingProfileView,
        'WorkCostAccounting': ArchitectBillingCostAccountingView,
        'BillingClause': ArchitectBillingClauseView, 'WorkFact': ArchitectBillingWorkFactView,
        'FeeCalculation': ArchitectBillingCalculationView, 'FeeClaim': ArchitectBillingClaimView,
        'PaymentReceipt': ArchitectBillingReceiptView, 'PaymentExecution': ArchitectBillingExecutionView,
        'EvidenceTarget': ArchitectBillingQuestionView,
    })
