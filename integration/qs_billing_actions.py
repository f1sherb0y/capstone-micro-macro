"""Freeze original QS A10 billing clauses, work and independent receipts."""
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_billing_objects import (
    QSBillingEngagementView, QSBillingProfileView, QSBillingClauseView,
    QSBillingWorkFactView, QSBillingCalculationView, QSBillingClaimView,
    QSBillingReceiptView, QSBillingExecutionView, QSBillingQuestionView,
    QSBillingAdvanceCreditView, QSBillingPayableView, QSBillingCostAccountingView, qs_billing_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedQSBilling(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A10'


class QSBillingActionAssembler(QSMarketActionAssembler):
    """Keep internal work costs, external fee rights and received cash separate.

    Original processor checks billing history, conditions, calculation arithmetic,
    correction rights, sourced advance credits and receipt deduplication. Nullable calculations/prior claims
    remain explicit. Assembly creates no claim, self-charge, fee or cash receipt.
    """
    ACTION_ID = 'QS-A10'
    SOURCE_SCHEMAS = staticmethod(qs_billing_schemas)

    def build(self, context, *, scope, engagement_ref, billing_clause_ref, work_fact_refs,
            calculation_ref, prior_claim_ref, receipt_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'engagement_ref': engagement_ref, 'billing_clause_ref': billing_clause_ref,
            'work_fact_refs': work_fact_refs, 'calculation_ref': calculation_ref,
            'prior_claim_ref': prior_claim_ref, 'receipt_refs': receipt_refs},
            prepared_type=PreparedQSBilling, validate_sources=validate_qs_billing_sources)


    def prepare_calculation(self, context, *, calculation_ref, author_authority_ref,
            validate_current, **source_refs):
        """Produce fee evidence under the caller's actual source writer guard."""
        from integration.qs_billing_calculations import prepare_qs_billing_calculation

        prepared = self.build(context, calculation_ref=None, **source_refs)
        return prepare_qs_billing_calculation(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=validate_current)


    def save_calculation(self, context, *, publications, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Return the durable fee calculation before explicit fresh-token publication."""
        from integration.qs_billing_calculation_publication import QSBillingCalculationPublicationStore
        from integration.qs_billing_calculations import prepare_qs_billing_calculation

        if (not isinstance(publications, QSBillingCalculationPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or not callable(read_guard)):
            raise TaskConflict('Fee save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, calculation_ref=None, **source_refs)
            calculation = prepare_qs_billing_calculation(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            return {'kind':'prepared', 'calculation':calculation, 'record':record}

    def build_from_submitted_claim(self, context, *, claim_submission, claim_identity,
            claim_execution_versions, basis_ref, read_guard, validate_history,
            validate_current, validate_receipt_relation, **billing_refs):
        """Prepare a later own fee action from an independently registered claim.

        The receipt links registration to the saved claim/correction only.
        Actual receivable status, cash and credit applications remain native
        facts checked by the host; no processor, transport or ledger is run.
        """
        from integration.qs_submission import QSResultSubmission
        from integration.qs_billing_results import QSBillingResultWorker
        from integration.qs_billing_claim_handoff import prepare_qs_billing_claim_handoff

        if (not isinstance(claim_submission, QSResultSubmission) or claim_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(claim_submission.worker, QSBillingResultWorker)
                or claim_submission.worker.registry is not self.registry
                or claim_submission.worker.store.run_id != self.organizations.run_id
                or self.source_mode != 'formal' or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Fee linkage requires original billing binding and actual guarded source/relation checks')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            receipt = claim_submission.read_receipt(claim_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected registration cannot establish an actual fee claim')
            invocation = self.build(context, **billing_refs)
            if invocation.action_input.prior_claim_ref is None:
                raise TaskConflict('Fee linkage requires the explicit actual existing claim as prior_claim_ref')
            saved = claim_submission.worker.read_completed(claim_identity, current_context=invocation.context,
                reading=invocation.reading, execution_versions=claim_execution_versions, validate_current=validate_history)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']
                        or sources['reading']._resolver.source_mode != 'formal'):
                    raise TaskConflict('Fee registration receipt changes original task, record or current formal sources')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

            handoff = prepare_qs_billing_claim_handoff(saved, context=invocation.context, reading=invocation.reading,
                basis_ref=basis_ref, claim_ref=invocation.action_input.prior_claim_ref, validate_current=validate_link)
            if claim_submission.read_receipt(claim_identity) != receipt:
                raise TaskConflict('Original fee registration receipt changed during actual claim linkage')
            invocation.reading.recheck()
            return {**handoff, 'provenance':{**handoff['provenance'], 'submission':deepcopy(receipt)},
                'invocation':replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}


def validate_qs_billing_sources(action_input, *, context, organization_id, sources):
    """Check original engagement/payer/payment identities without calculating fees."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS billing lacks its exact original concrete source')
        if row.scope != context.scope:
            raise TaskConflict('QS billing source changes its original invocation scope')
        return row

    def same_engagement(row):
        if row.engagement_ref.key() != engagement.ref.key():
            raise TaskConflict('QS billing source changes its original engagement')
        return row

    def claim_identity(claim):
        same_engagement(claim)
        if claim.payer_id != engagement.payer_id or claim.payee_organization_id != organization_id:
            raise TaskConflict('QS fee claim changes its original payer or provider')
        unique_refs(claim.work_fact_refs)
        unique_refs(claim.receipt_refs)
        return claim

    if action_input.scope != context.scope:
        raise TaskConflict('QS billing changes its original invocation scope')
    engagement = read(action_input.engagement_ref, QSBillingEngagementView)
    if engagement.organization_id != organization_id:
        raise TaskConflict('QS billing changes its original service provider')
    if engagement.cost_accounting_ref is not None and engagement.cost_accounting_ref.key() in sources:
        accounting = same_engagement(read(engagement.cost_accounting_ref, QSBillingCostAccountingView))
        if accounting.run_id != context.run_id or accounting.organization_id != organization_id:
            raise TaskConflict('QS internal accounting changes its original run or service provider')
        unique_refs([line.work_fact_ref for line in accounting.lines])
        unique_refs(accounting.posting_authority_evidence_refs)
    clause = same_engagement(read(action_input.billing_clause_ref, QSBillingClauseView))
    if clause.contract_ref.key() != engagement.contract_ref.key() or clause.payer_id != engagement.payer_id:
        raise TaskConflict('QS billing clause changes its original contract or payer')
    for refs in (action_input.work_fact_refs, action_input.receipt_refs, engagement.billing_clause_refs,
            engagement.work_fact_refs, engagement.claim_refs, clause.eligible_work_fact_refs):
        unique_refs(refs)
    for ref in action_input.work_fact_refs:
        fact = same_engagement(read(ref, QSBillingWorkFactView))
        if fact.organization_id != organization_id:
            raise TaskConflict('QS billing work changes its original provider')
    prior = None
    if action_input.prior_claim_ref is not None:
        prior = claim_identity(read(action_input.prior_claim_ref, QSBillingClaimView))
        if prior.billing_clause_ref.key() != clause.ref.key():
            raise TaskConflict('QS prior fee claim changes its original billing clause')
    if action_input.calculation_ref is not None:
        calculation = same_engagement(read(action_input.calculation_ref, QSBillingCalculationView))
        if (calculation.billing_clause_ref.key() != clause.ref.key()
                or calculation.prior_claim_ref != action_input.prior_claim_ref):
            raise TaskConflict('QS fee calculation changes its original clause or prior claim')
        unique_refs(calculation.work_fact_refs)
    for ref in action_input.receipt_refs:
        receipt = same_engagement(read(ref, QSBillingReceiptView))
        if (receipt.payer_id != engagement.payer_id or receipt.beneficiary_organization_id != organization_id
                or prior is not None and receipt.claim_ref.key() != prior.ref.key()):
            raise TaskConflict('QS fee receipt changes its original claim, payer or beneficiary')
        if receipt.execution_ref.key() in sources:
            execution = same_engagement(read(receipt.execution_ref, QSBillingExecutionView))
            if (execution.claim_ref.key() != receipt.claim_ref.key() or execution.payer_id != receipt.payer_id
                    or execution.beneficiary_organization_id != receipt.beneficiary_organization_id
                    or execution.command_id != receipt.command_id or execution.business_key != receipt.business_key):
                raise TaskConflict('QS fee receipt changes its original payment execution identity')
            unique_refs(execution.receipt_refs)
    for ref in engagement.claim_refs:
        if ref.key() in sources:
            claim_identity(read(ref, QSBillingClaimView))
    unique_refs(engagement.advance_credit_refs)
    unique_refs(engagement.payable_obligation_refs)
    for ref in engagement.advance_credit_refs:
        if ref.key() in sources:
            same_engagement(read(ref, QSBillingAdvanceCreditView))
    for ref in engagement.payable_obligation_refs:
        if ref.key() in sources:
            same_engagement(read(ref, QSBillingPayableView))
    # Verified advance receipts, applied credit identity and independent payment
    # obligations remain original processor decisions; no new cash is inferred.
    if engagement.billing_profile_ref.key() not in sources:
        return
    profile = same_engagement(read(engagement.billing_profile_ref, QSBillingProfileView))
    unique_refs(profile.advance_credit_refs)
    unique_refs(profile.work_fact_refs)
    unique_refs(profile.correction_basis_refs)
    if action_input.calculation_ref is not None and calculation.billing_key != profile.billing_key:
        raise TaskConflict('QS fee calculation changes its original billing item')
    if profile.dispute_question_ref is not None and profile.dispute_question_ref.key() in sources:
        question = same_engagement(read(profile.dispute_question_ref, QSBillingQuestionView))
        if (question.question.scope != action_input.scope
                or prior is not None and question.claim_ref.key() != prior.ref.key()):
            raise TaskConflict('QS fee dispute changes its original claim or scope')
