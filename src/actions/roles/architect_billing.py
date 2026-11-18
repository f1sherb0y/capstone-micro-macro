"""ARCHITECT-A10 billing and receipt proposals never add cash or self-charges."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.architect_billing_objects import (
    ArchitectBillingEngagementView, ArchitectBillingProfileView, ArchitectBillingClauseView,
    ArchitectBillingWorkFactView, ArchitectBillingCalculationView, ArchitectBillingClaimView,
    ArchitectBillingReceiptView, ArchitectBillingExecutionView, ArchitectBillingQuestionView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def handle_service_fees(context, action_input, reading):
    now, organization = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('architect-billing-clock-alignment')

    def evidence(refs, historical=False):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('architect-billing-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_billing_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-billing-projection:{ref.kind}')
        if hasattr(row, 'scope') and row.scope != action_input.scope: raise ValueError('Billing input changes original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_billing_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('current_original_billing_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def amount(value):
        if value.currency != clause.currency: _unsupported('architect-billing-currency-conversion')
        evidence([value.basis_ref], True); number = decimal_fraction(value.value)
        if number < 0: raise ValueError('Fee claim, receipt or actual cost cannot be negative')
        return number

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope, 'note': profile.note, **fields}}

    def deferred(code, refs):
        reading.recheck(); return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    try:
        if action_input.scope != context.scope: raise ValueError('Billing action changes original authorized scope')
        engagement = read(action_input.engagement_ref, ArchitectBillingEngagementView)
        if engagement.organization_id != organization: raise ValueError('Billing borrows another service provider engagement')
        profile = read(engagement.billing_profile_ref, ArchitectBillingProfileView)
        if not same(profile.engagement_ref, engagement.ref): raise ValueError('Billing profile changes original engagement')
        grant = read(profile.authority_ref, Authorization); function = read(context.function_ref, RoleAssignment)
        if (grant.organization_id != organization or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                or function.role != 'Architect' or 'ARCHITECT-A10' not in grant.action_ids
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Billing lacks original independent actor/action/function/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_service_billing_authority')
        evidence([*grant.basis_refs, *function.basis_refs])
        if engagement.relation == 'internal' or engagement.payer_organization_id == organization:
            return deferred('internal_design_costs_require_actual_work_accounting_without_self_fee_claim', [engagement.ref])
        clause = read(action_input.billing_clause_ref, ArchitectBillingClauseView, profile.choice in {'dispute', 'reconcile', 'remind'})
        if (not same(clause.engagement_ref, engagement.ref) or not same(clause.contract_ref, engagement.contract_ref)
                or clause.payer_id != engagement.payer_id or clause.ref.key() not in keys(engagement.billing_clause_refs)):
            raise ValueError('Billing clause changes original engagement, contract or actual payer')
        if engagement.coverage != 'complete' or engagement.as_of != now: _needs('complete_current_original_fee_claim_and_work_history')
        if keys(action_input.work_fact_refs) != keys(profile.work_fact_refs) or not keys(profile.work_fact_refs) <= keys(engagement.work_fact_refs):
            _needs('all_original_work_for_current_billing_item')
        prior = None
        claims = {}
        for ref in engagement.claim_refs:
            claim = read(ref, ArchitectBillingClaimView, True)
            if (not same(claim.engagement_ref, engagement.ref) or claim.payer_id != engagement.payer_id
                    or claim.payee_organization_id != organization): raise ValueError('Claim history changes original payer/provider/engagement')
            if claim.actual_received.currency != claim.amount.currency: raise ValueError('Claim received cash changes original billing currency')
            if same(claim.billing_clause_ref, clause.ref):
                amount(claim.amount); amount(claim.actual_received)
            claims[ref.key()] = claim
        if action_input.prior_claim_ref is not None:
            prior = claims.get(action_input.prior_claim_ref.key())
            if prior is None or not same(prior.billing_clause_ref, clause.ref): raise ValueError('Existing fee branch borrows another original claim/clause')
            if prior.status == 'superseded': _needs('current_original_fee_claim_successor')
        if profile.choice != 'claim' and prior is None: _needs('input.prior_claim_ref')
        if profile.choice == 'claim' and prior is not None: raise ValueError('Existing claim requires correction or reconciliation')
        if profile.choice == 'dispute':
            if profile.dispute_question_ref is None: _needs('specific_original_fee_dispute_question')
            row = read(profile.dispute_question_ref, ArchitectBillingQuestionView); question = row.question
            if (not same(row.engagement_ref, engagement.ref) or not same(row.claim_ref, prior.ref)
                    or question.scope != action_input.scope or not question.recipient_ids
                    or row.ref.key() not in keys(question.target_refs)):
                raise ValueError('Fee dispute question changes original claim/engagement/scope')
            response = read(question.response_requirement_ref, ServiceResponseRequirementView)
            if not set(question.recipient_ids) <= set(response.recipient_ids): raise ValueError('Fee dispute exceeds original response recipients')
            for ref in question.target_refs:
                target = read(ref, ArchitectBillingQuestionView)
                if not same(target.claim_ref, prior.ref) or not same(target.engagement_ref, engagement.ref) or target.question != question:
                    raise ValueError('Fee dispute mixes original claim targets')
            evidence(question.evidence_refs)
            return completed('dispute', claim_ref=prior.ref, issue=question.model_dump(mode='python'))
        if profile.choice == 'remind':
            if (profile.reminder_recipient_id is None or profile.reminder_recipient_id not in clause.reminder_recipient_ids):
                _needs('original_authorized_fee_reminder_recipient')
            if prior.status != 'confirmed' or prior.due_at is None: _needs('original_confirmed_due_receivable_for_reminder')
            clock(prior.due_at)
            if prior.due_at.offset >= now.offset or amount(prior.actual_received) >= amount(prior.amount):
                return deferred('original_fee_not_overdue_or_already_received', [prior.ref])
            return completed('remind', claim_ref=prior.ref, recipient_id=profile.reminder_recipient_id)
        if profile.choice == 'reconcile':
            if not action_input.receipt_refs: _needs('actual_original_payment_receipts_for_fee_reconciliation')
            if prior.receipt_coverage != 'complete' or keys(action_input.receipt_refs) != keys(prior.receipt_refs):
                _needs('all_original_received_fee_payment_receipts')
            events, execution_totals, recognized_totals, sequences, command_executions = {}, {}, {}, set(), {}
            for ref in action_input.receipt_refs:
                row = read(ref, ArchitectBillingReceiptView, True)
                if (not same(row.claim_ref, prior.ref) or not same(row.engagement_ref, engagement.ref)
                        or row.payer_id != engagement.payer_id or row.beneficiary_organization_id != organization):
                    raise ValueError('Fee receipt changes original claim, payer, beneficiary or engagement')
                clock(row.effective_at)
                if row.effective_at.offset > min(now.offset, row.available_at.offset): _needs('actual_fee_payment_before_received_receipt')
                execution = read(row.execution_ref, ArchitectBillingExecutionView, True)
                if (not same(execution.engagement_ref, engagement.ref) or not same(execution.claim_ref, prior.ref)
                        or execution.payer_id != engagement.payer_id or execution.beneficiary_organization_id != organization
                        or execution.command_id != row.command_id or execution.business_key != row.business_key
                        or row.ref.key() not in keys(execution.receipt_refs)):
                    raise ValueError('Fee receipt changes original payment execution identity')
                command = (row.command_id, row.business_key)
                if command in command_executions and command_executions[command] != row.execution_ref.key():
                    raise ValueError('Fee history repeats one payment command under multiple execution identities')
                command_executions[command] = row.execution_ref.key()
                payload = row.model_dump(mode='json', exclude={'ref', 'available_at', 'effective_window', 'evidence_refs'})
                if row.event_id in events:
                    if events[row.event_id].model_dump(mode='json', exclude={'ref', 'available_at', 'effective_window', 'evidence_refs'}) != payload:
                        raise ValueError('Duplicate fee receipt event changes original content')
                    continue
                events[row.event_id] = row
                sequence = (row.execution_ref.key(), row.sequence)
                if sequence in sequences: raise ValueError('Fee execution receipt sequence is ambiguous')
                sequences.add(sequence)
            ordered = sorted(events.values(), key=lambda row: (row.execution_ref.key(), row.sequence))
            for row in ordered:
                value = amount(row.amount.value) if isinstance(row.amount, Known) else None
                if row.status in {'unknown', 'failed', 'rejected'}:
                    if value: raise ValueError('Unverified/failed fee receipt cannot claim actual received cash')
                    continue
                if value is None: _needs('verified_actual_fee_receipt_amount')
                key = (row.command_id, row.business_key)
                old = execution_totals.get(key, Fraction())
                if row.semantics == 'cumulative' and value < old: raise ValueError('Cumulative fee receipt regresses known received cash')
                execution_totals[key] = value if row.semantics == 'cumulative' else old + value
                if row.event_id in prior.recognized_event_ids:
                    recorded = recognized_totals.get(key, Fraction())
                    if row.semantics == 'cumulative' and value < recorded: raise ValueError('Recorded fee receipt history regresses actual cash')
                    recognized_totals[key] = value if row.semantics == 'cumulative' else recorded + value
            if len(set(prior.recognized_event_ids)) != len(prior.recognized_event_ids) or not set(prior.recognized_event_ids) <= set(events):
                _needs('original_recognized_fee_receipt_event_history')
            if any(events[key].status not in {'verified_partial', 'verified_final'} for key in prior.recognized_event_ids):
                raise ValueError('Recorded fee cash includes an unverified receipt event')
            if amount(prior.actual_received) != sum(recognized_totals.values(), Fraction()):
                _needs('original_recorded_fee_cash_matching_recognized_receipt_events')
            return completed('reconcile', claim_ref=prior.ref, receipt_refs=action_input.receipt_refs)
        if action_input.calculation_ref is None: _needs('input.calculation_ref')
        calculation = read(action_input.calculation_ref, ArchitectBillingCalculationView)
        clock(calculation.executed_at)
        if (not same(calculation.engagement_ref, engagement.ref) or not same(calculation.billing_clause_ref, clause.ref)
                or calculation.billing_key != profile.billing_key or keys(calculation.work_fact_refs) != keys(action_input.work_fact_refs)
                or calculation.prior_claim_ref != action_input.prior_claim_ref
                or calculation.executed_at.offset > min(now.offset, calculation.available_at.offset)):
            raise ValueError('Fee calculation changes original clause, billing identity, work or prior claim')
        if calculation.status == 'unsupported': _unsupported('architect-fee-calculation-method')
        if calculation.status != 'succeeded': _needs('successful_original_fee_calculation')
        if not isinstance(clause.conditions_satisfied, Known): _needs('verified_original_billing_conditions')
        if not clause.conditions_satisfied.value: return deferred('original_billing_conditions_not_satisfied', [clause.ref])
        if not clause.condition_evidence_refs: _needs('original_billing_condition_evidence')
        evidence(clause.condition_evidence_refs)
        if not keys(action_input.work_fact_refs) <= keys(clause.eligible_work_fact_refs): raise ValueError('Fee claim uses work outside original billing clause')
        effort, slices = Fraction(), set()
        for ref in action_input.work_fact_refs:
            fact = read(ref, ArchitectBillingWorkFactView, True)
            clock(fact.window.start)
            if (fact.organization_id != organization or not same(fact.engagement_ref, engagement.ref) or fact.investment_key in slices):
                raise ValueError('Fee calculation duplicates original investment or borrows another engagement')
            if fact.status != 'committed' or fact.window.end.offset > calculation.executed_at.offset: _needs('actual_original_work_before_fee_calculation')
            if clause.effort_unit is not None and fact.effort.unit != clause.effort_unit: _unsupported('architect-fee-effort-unit-conversion')
            value = decimal_fraction(fact.effort.value)
            if value < 0 or decimal_fraction(fact.internal_cost.value) < 0: raise ValueError('Actual work/cost cannot be negative')
            evidence([fact.effort.basis_ref, fact.internal_cost.basis_ref], True); effort += value; slices.add(fact.investment_key)
        if effort < decimal_fraction(clause.minimum_effort): _needs('original_billing_work_threshold')
        if decimal_fraction(clause.minimum_effort) < 0: raise ValueError('Billing effort threshold cannot be negative')
        if clause.mode == 'effort':
            if clause.unit_rate is None or clause.effort_unit is None: _unsupported('architect-fee-original-effort-rate')
            calculated = effort * amount(clause.unit_rate)
        else:
            if clause.fixed_amount is None: _needs('original_fixed_stage_or_advance_fee')
            calculated = amount(clause.fixed_amount)
        scaled = calculated * 10 ** clause.minor_places
        integer, remainder = divmod(scaled.numerator, scaled.denominator)
        if 2 * remainder > scaled.denominator or (2 * remainder == scaled.denominator and integer % 2): integer += 1
        if amount(calculation.amount) != Fraction(integer, 10 ** clause.minor_places): raise ValueError('Fee amount differs from original clause arithmetic and rounding')
        if amount(calculation.amount) <= 0: _needs('positive_original_fee_claim_amount')
        if profile.choice == 'correct':
            if not clause.allowed_correction or not profile.correction_basis_refs: _needs('original_allowed_fee_correction_with_evidence')
            if prior.billing_key != profile.billing_key: raise ValueError('Fee correction changes original business billing item')
            evidence(profile.correction_basis_refs)
        active = [claim for claim in claims.values() if claim.status not in {'superseded', 'rejected'} and same(claim.billing_clause_ref, clause.ref)]
        for claim in active:
            if prior is not None and same(claim.ref, prior.ref): continue
            if claim.billing_key == profile.billing_key: return deferred('query_original_fee_claim_before_duplicate', [claim.ref])
            if keys(claim.work_fact_refs).intersection(keys(action_input.work_fact_refs)):
                raise ValueError('Fee billing items charge the same original work twice')
        total = amount(calculation.amount) + sum((amount(claim.amount) for claim in active if prior is None or not same(claim.ref, prior.ref)), Fraction())
        if total > amount(clause.cumulative_limit): _needs('original_cumulative_service_fee_limit')
        claim = {'engagement_ref': engagement.ref, 'billing_clause_ref': clause.ref, 'work_fact_refs': action_input.work_fact_refs,
            'calculation_ref': calculation.ref, 'amount': calculation.amount, 'payer_id': engagement.payer_id, 'prior_claim_ref': action_input.prior_claim_ref}
        fields = {'claim': claim}
        if profile.choice == 'correct': fields['prior_claim_ref'] = prior.ref
        return completed(profile.choice, **fields)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
