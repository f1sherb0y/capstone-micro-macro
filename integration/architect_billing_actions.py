"""Freeze original Architect A10 billing clauses, work and independent receipts."""
from dataclasses import dataclass
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_billing_objects import (
    ArchitectBillingEngagementView, ArchitectBillingProfileView, ArchitectBillingClauseView,
    ArchitectBillingWorkFactView, ArchitectBillingCalculationView, ArchitectBillingClaimView,
    ArchitectBillingReceiptView, ArchitectBillingExecutionView, ArchitectBillingQuestionView,
    architect_billing_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedArchitectBilling(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A10'


class ArchitectBillingActionAssembler(ArchitectOpportunityActionAssembler):
    """Keep internal work costs, external fee rights and received cash separate.

    Original processor checks billing history, conditions, calculation arithmetic,
    correction rights and receipt deduplication. Nullable calculations/prior claims
    remain explicit. Assembly creates no claim, self-charge, fee or cash receipt.
    """
    ACTION_ID = 'ARCHITECT-A10'
    SOURCE_SCHEMAS = staticmethod(architect_billing_schemas)

    def build(self, context, *, scope, engagement_ref, billing_clause_ref, work_fact_refs,
            calculation_ref, prior_claim_ref, receipt_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'engagement_ref': engagement_ref, 'billing_clause_ref': billing_clause_ref,
            'work_fact_refs': work_fact_refs, 'calculation_ref': calculation_ref,
            'prior_claim_ref': prior_claim_ref, 'receipt_refs': receipt_refs},
            prepared_type=PreparedArchitectBilling, validate_sources=validate_architect_billing_sources)


def validate_architect_billing_sources(action_input, *, context, organization_id, sources):
    """Check original engagement/payer/payment identities without calculating fees."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect billing lacks its exact original concrete source')
        if row.scope != context.scope:
            raise TaskConflict('Architect billing source changes its original invocation scope')
        return row

    def same_engagement(row):
        if row.engagement_ref.key() != engagement.ref.key():
            raise TaskConflict('Architect billing source changes its original engagement')
        return row

    def claim_identity(claim):
        same_engagement(claim)
        if claim.payer_id != engagement.payer_id or claim.payee_organization_id != organization_id:
            raise TaskConflict('Architect fee claim changes its original payer or provider')
        unique_refs(claim.work_fact_refs)
        unique_refs(claim.receipt_refs)
        return claim

    if action_input.scope != context.scope:
        raise TaskConflict('Architect billing changes its original invocation scope')
    engagement = read(action_input.engagement_ref, ArchitectBillingEngagementView)
    if engagement.organization_id != organization_id:
        raise TaskConflict('Architect billing changes its original service provider')
    clause = same_engagement(read(action_input.billing_clause_ref, ArchitectBillingClauseView))
    if clause.contract_ref.key() != engagement.contract_ref.key() or clause.payer_id != engagement.payer_id:
        raise TaskConflict('Architect billing clause changes its original contract or payer')
    for refs in (action_input.work_fact_refs, action_input.receipt_refs, engagement.billing_clause_refs,
            engagement.work_fact_refs, engagement.claim_refs, clause.eligible_work_fact_refs):
        unique_refs(refs)
    for ref in action_input.work_fact_refs:
        fact = same_engagement(read(ref, ArchitectBillingWorkFactView))
        if fact.organization_id != organization_id:
            raise TaskConflict('Architect billing work changes its original provider')
    prior = None
    if action_input.prior_claim_ref is not None:
        prior = claim_identity(read(action_input.prior_claim_ref, ArchitectBillingClaimView))
        if prior.billing_clause_ref.key() != clause.ref.key():
            raise TaskConflict('Architect prior fee claim changes its original billing clause')
    if action_input.calculation_ref is not None:
        calculation = same_engagement(read(action_input.calculation_ref, ArchitectBillingCalculationView))
        if (calculation.billing_clause_ref.key() != clause.ref.key()
                or calculation.prior_claim_ref != action_input.prior_claim_ref):
            raise TaskConflict('Architect fee calculation changes its original clause or prior claim')
        unique_refs(calculation.work_fact_refs)
    for ref in action_input.receipt_refs:
        receipt = same_engagement(read(ref, ArchitectBillingReceiptView))
        if (receipt.payer_id != engagement.payer_id or receipt.beneficiary_organization_id != organization_id
                or prior is not None and receipt.claim_ref.key() != prior.ref.key()):
            raise TaskConflict('Architect fee receipt changes its original claim, payer or beneficiary')
        if receipt.execution_ref.key() in sources:
            execution = same_engagement(read(receipt.execution_ref, ArchitectBillingExecutionView))
            if (execution.claim_ref.key() != receipt.claim_ref.key() or execution.payer_id != receipt.payer_id
                    or execution.beneficiary_organization_id != receipt.beneficiary_organization_id
                    or execution.command_id != receipt.command_id or execution.business_key != receipt.business_key):
                raise TaskConflict('Architect fee receipt changes its original payment execution identity')
            unique_refs(execution.receipt_refs)
    for ref in engagement.claim_refs:
        if ref.key() in sources:
            claim_identity(read(ref, ArchitectBillingClaimView))
    if engagement.billing_profile_ref.key() not in sources:
        return
    profile = same_engagement(read(engagement.billing_profile_ref, ArchitectBillingProfileView))
    unique_refs(profile.work_fact_refs)
    unique_refs(profile.correction_basis_refs)
    if action_input.calculation_ref is not None and calculation.billing_key != profile.billing_key:
        raise TaskConflict('Architect fee calculation changes its original billing item')
    if profile.dispute_question_ref is not None and profile.dispute_question_ref.key() in sources:
        question = same_engagement(read(profile.dispute_question_ref, ArchitectBillingQuestionView))
        if (question.question.scope != action_input.scope
                or prior is not None and question.claim_ref.key() != prior.ref.key()):
            raise TaskConflict('Architect fee dispute changes its original claim or scope')
