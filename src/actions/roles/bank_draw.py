"""BANK-A06 original batch approval; no transfer, principal or release effects."""
from fractions import Fraction
from src.actions.roles.bank_draw_accounting import read_draw_usage

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.bank_objects import FundingPurposeView
from src.actions.contracts.bank_draw_objects import (
    BankDrawRequestView, BankDrawDecisionView, BankDrawArrangementView, BankDrawTermsView,
    BankDrawCapacityView, BankDrawBatchView, BankDrawReinstatementView, BankDrawExecutionView,
    BankDrawReceiptView, BankDrawConditionView, BankDrawDestinationView, BankDrawObligationView, BankDrawFeeRuleView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_draw(context, action_input, reading):
    now, lender = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('bank-draw-clock-alignment')

    def evidence(refs, historical=False, at=None):
        point = now if at is None else at
        clock(point)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('bank-draw-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if (at is not None or not historical) and not row.effective_window.contains(point):
                    _needs('current_original_draw_evidence' if at is None else 'original_draw_evidence_valid_when_verified', [ref])

    def read(ref, schema, historical=False, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'bank-draw-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Draw input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_draw_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('current_original_draw_input', [ref])
        point = None if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > min(now.offset, row.available_at.offset):
                _needs('received_original_draw_verification', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical, at=point); return row

    def authorize(ref, actor, function_ref, organization, action, roles, at=None, *, target_scope=None, required_reads=()):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        expected_role = {'OWN': 'Owner', 'BANK': 'Bank', 'GOV': 'Government', 'ENGINEER': 'Engineer',
            'ARCHITECT': 'Architect', 'QS': 'QS', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier'}.get(action.split('-')[0])
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or function.function_ref != function_ref or function.role != expected_role
                or function.role not in roles or action not in grant.action_ids
                or not any(scope_covers(scope, target_scope or context.scope) for scope in grant.scopes)
                or not {ref.key() for ref in required_reads} <= {ref.key() for ref in grant.readable_refs}):
            raise ValueError('Draw request/decision/verification lacks independent original action and scope authority')
        point = now if at is None else at
        clock(grant.validity.start); clock(point)
        if not grant.validity.contains(point):
            _needs('current_original_draw_authority' if at is None else 'original_draw_verifier_authority_at_verification', [ref])
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                reading.resolve(basis_ref)

    def amount(value, currency, positive=False):
        evidence([value.basis_ref]); number = decimal_fraction(value.value)
        if value.currency != currency: _unsupported('bank-draw-currency-conversion')
        if number < 0 or (positive and number == 0): raise ValueError('Original draw/usage amount must be nonnegative, approved amounts positive')
        return number

    def deferred(refs, code):
        reading.recheck(); return {'kind': 'deferred', 'reason_code': 'original_draw_batch_reconciliation_required',
            'resume_condition': {'trigger': 'event', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def receipt(ref, currency):
        row = read(ref, BankDrawReceiptView, historical=True)
        if row.lender_id != lender or not same(row.arrangement_ref, arrangement.ref):
            raise ValueError('Draw receipt changes original lender/arrangement identity')
        value = amount(row.amount, currency, True); return row, value

    def conditions(roots):
        graph, identities = {}, {}
        pending = list(reversed(roots))
        while pending:
            ref = pending.pop()
            if ref.key() in graph: continue
            identity = (ref.kind, ref.id)
            previous = identities.get(identity)
            if previous is not None and previous != ref.key():
                raise ValueError('Draw condition graph mixes versions of one original requirement')
            identities[identity] = ref.key()
            row = read(ref, BankDrawConditionView, evidence_at_field='verified_at')
            if not same(row.arrangement_ref, arrangement.ref): raise ValueError('Condition belongs to another arrangement')
            if row.stage in {'each_draw', 'batch'} and (row.draw_request_ref is None or not same(row.draw_request_ref, request.ref)):
                raise ValueError('Condition applies to another original draw batch')
            graph[ref.key()] = row
            keys(row.dependency_refs)
            pending.extend(reversed(row.dependency_refs))

        resolved, output, visiting = {}, [], set()
        for ref in roots:
            # Explicit entry/exit frames preserve dependency-first evaluation
            # without imposing Python's recursion limit on the source graph.
            stack = [(ref.key(), False)]
            while stack:
                key, ready = stack.pop()
                if key in resolved: continue
                row = graph[key]
                if not ready:
                    if key in visiting: _needs('draw_condition_dependency_cycle_requires_responsible_party_resolution', [row.ref])
                    visiting.add(key)
                    stack.append((key, True))
                    stack.extend((dependency.key(), False) for dependency in reversed(row.dependency_refs))
                    continue
                dependencies = [resolved[dependency.key()] for dependency in row.dependency_refs]
                outcome = 'unknown'
                if row.outcome.state == 'not_supported':
                    _known(row.outcome, 'supported_original_draw_condition')
                if row.outcome.state == 'known':
                    clock(row.verified_at)
                    if row.verified_at.offset > min(now.offset, row.available_at.offset): _needs('received_original_draw_condition_verification')
                    if (row.verifier_organization_id not in row.permitted_verifier_ids
                            or row.verifier_action_id not in row.permitted_verifier_action_ids):
                        raise ValueError('Draw condition verifier leaves original independent verifier permission')
                    authorize(row.verifier_authority_ref, row.verifier_actor_id, row.verifier_function_ref,
                              row.verifier_organization_id, row.verifier_action_id, {'Owner', 'Bank', 'Engineer', 'Architect', 'QS', 'Government'},
                              at=row.verified_at, target_scope=row.scope,
                              required_reads=[*row.evidence_refs, *row.verification_evidence_refs])
                    if not row.verification_evidence_refs or not keys(row.verification_evidence_refs) <= keys(action_input.condition_evidence_refs):
                        _needs('received_original_batch_condition_evidence', row.verification_evidence_refs)
                    evidence(row.verification_evidence_refs, at=row.verified_at)
                    outcome = 'satisfied' if row.outcome.value else 'unsatisfied'
                if 'unsatisfied' in dependencies: outcome = 'unsatisfied'
                elif 'unknown' in dependencies and outcome == 'satisfied': outcome = 'unknown'
                resolved[key] = outcome; visiting.remove(key)
                output.append({'requirement_ref': row.ref, 'scope_ref': row.scope, 'responsible_id': row.responsible_id,
                    'evidence_refs': row.verification_evidence_refs, 'outcome': outcome})
        return output, resolved

    def transfers(lines, currency, requested_by_destination=None):
        if not lines: _needs('nonempty_original_draw_transfer_lines')
        keys([line.destination_ref for line in lines]); total, fees, obligations = Fraction(), Fraction(), set()
        for line in lines:
            if line.beneficiary_id not in terms.allowed_beneficiary_ids: raise ValueError('Draw transfer beneficiary leaves original facility permission')
            destination = read(line.destination_ref, BankDrawDestinationView)
            if (destination.organization_id != line.beneficiary_id or destination.currency != currency
                    or arrangement.ref.key() not in keys(destination.permitted_arrangement_refs)):
                raise ValueError('Transfer mixes original recipient/account/currency/facility permission')
            if not _known(destination.available, 'original_draw_destination_available'): _needs('original_draw_destination_available')
            value = amount(line.requested, currency, True); total += value
            if requested_by_destination is not None:
                original = requested_by_destination.get(line.destination_ref.key())
                if (original is None or original.beneficiary_id != line.beneficiary_id
                        or keys(original.obligation_refs) != keys(line.obligation_refs)
                        or keys(original.fee_rule_refs) != keys(line.fee_rule_refs)
                        or value > decimal_fraction(original.requested.value)):
                    raise ValueError('Approved draw transfer changes original requested destination/obligation/fees or exceeds amount')
            keys(line.obligation_refs)
            unpaid = Fraction()
            for ref in line.obligation_refs:
                obligation_identity = (ref.kind, ref.id)
                if obligation_identity in obligations: raise ValueError('Direct draw pays the same obligation twice across versions')
                obligations.add(obligation_identity); row = read(ref, BankDrawObligationView)
                if row.borrower_id != arrangement.borrower_id or row.payee_id != line.beneficiary_id or not same(row.purpose_ref, action_input.purpose_ref):
                    raise ValueError('Direct draw changes original borrower/payee/purpose obligation')
                if not _known(row.payable, 'original_direct_draw_obligation_payable'): _needs('original_direct_draw_obligation_payable')
                unpaid += amount(_known(row.unpaid_amount, 'original_direct_draw_unpaid'), currency)
            if line.beneficiary_id != arrangement.borrower_id and (not line.obligation_refs or value > unpaid):
                _needs('original_direct_transfer_within_verified_unpaid_obligations')
            keys(line.fee_rule_refs)
            if not keys(line.fee_rule_refs) <= keys(terms.allowed_fee_rule_refs): raise ValueError('Draw adds a fee outside original product terms')
            for ref in line.fee_rule_refs:
                fee = read(ref, BankDrawFeeRuleView)
                if not same(fee.arrangement_ref, arrangement.ref) or not same(fee.destination_ref, line.destination_ref):
                    raise ValueError('Draw fee belongs to another arrangement or transfer destination')
                charge = amount(fee.fixed_amount, currency)
                if fee.basis == 'capitalized': fees += charge
        if terms.principal_basis == 'net_transfers' and fees: _unsupported('bank-draw-fee-principal-basis-domain')
        return total + (fees if terms.principal_basis == 'transfers_plus_capitalized_fees' else Fraction())

    try:
        request = read(action_input.draw_request_ref, BankDrawRequestView)
        arrangement = read(action_input.arrangement_ref, BankDrawArrangementView)
        if request.lender_id != lender or arrangement.lender_id != lender or request.borrower_id != arrangement.borrower_id or not same(request.arrangement_ref, arrangement.ref):
            raise ValueError('Draw request changes original borrower/lender/arrangement')
        request_role = {'OWN-A06': 'Owner', 'CONTRACTOR-A10': 'Contractor', 'SUPPLIER-A10': 'Supplier'}[request.author_action_id]
        authorize(request.author_authority_ref, request.author_actor_id, request.author_function_ref,
                  request.borrower_id, request.author_action_id, {request_role})
        profile = read(request.decision_profile_ref, BankDrawDecisionView)
        if profile.organization_id != lender or not same(profile.draw_request_ref, request.ref): raise ValueError('Draw choice belongs to another lender/batch')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, lender, 'BANK-A06', {'Bank'})
        terms = read(arrangement.terms_ref, BankDrawTermsView)
        if (not same(request.terms_ref, terms.ref) or not same(terms.arrangement_ref, arrangement.ref)
                or terms.borrower_id != arrangement.borrower_id or terms.lender_id != lender):
            raise ValueError('Draw request applies another original facility terms version')
        currency = terms.facility_limit.currency
        capacity = read(action_input.capacity_snapshot_ref, BankDrawCapacityView); clock(capacity.as_of)
        if capacity.lender_id != lender or not same(capacity.arrangement_ref, arrangement.ref): raise ValueError('Draw snapshot belongs to another actual facility')
        if capacity.as_of != now or capacity.coverage != 'complete': _needs('complete_current_facility_usage_and_pending_execution_snapshot')
        keys(capacity.approved_batch_refs); keys(capacity.execution_refs)
        if keys(action_input.pending_execution_refs) != keys(capacity.execution_refs): _needs('all_current_original_draw_execution_identities', capacity.execution_refs)
        usage, executed, batches, execution_rows, receipt_ids = read_draw_usage(
            capacity=capacity, arrangement=arrangement, lender=lender, currency=currency,
            read=read, amount=amount, receipt=receipt, evidence=evidence, keys=keys)
        previous = [batch for batch in batches.values() if batch.batch_key == request.batch_key or same(batch.draw_request_ref, request.ref)]
        if previous: return deferred([row.ref for row in previous], f'query_original_draw_batch:{request.batch_key}')
        restored = Fraction(); keys(capacity.reinstatement_refs)
        for ref in capacity.reinstatement_refs:
            row = read(ref, BankDrawReinstatementView)
            if row.lender_id != lender or not same(row.arrangement_ref, arrangement.ref): raise ValueError('Credit restoration belongs to another facility')
            if not terms.revolving: raise ValueError('Nonrevolving repayment cannot restore draw capacity')
            if not _known(row.authorized, 'original_revolving_credit_reinstatement'): _needs('original_revolving_credit_reinstatement')
            r, value = receipt(row.receipt_ref, currency)
            receipt_identity = (r.ref.kind, r.ref.id)
            if receipt_identity in receipt_ids or r.kind != 'principal_repayment' or r.status != 'succeeded' or value != amount(row.amount, currency):
                raise ValueError('Reinstatement copies or changes a real principal repayment receipt')
            receipt_ids.add(receipt_identity); restored += value
        if restored > executed: raise ValueError('Reinstated credit exceeds actual executed principal')
        remaining = amount(terms.facility_limit, currency, True) - usage + restored
        if remaining < 0: raise ValueError('Current approved/unknown facility usage already exceeds the original limit')
        groups = [(arrangement.formation_condition_refs, 'formation'), (arrangement.each_draw_condition_refs, 'each_draw'),
                  (arrangement.continuing_condition_refs, 'continuing'), (request.condition_refs, 'batch')]
        if executed == 0: groups.append((arrangement.first_draw_condition_refs, 'first_draw'))
        roots = {}
        for refs, stage in groups:
            keys(refs)
            for ref in refs:
                row = read(ref, BankDrawConditionView, evidence_at_field='verified_at')
                if row.stage != stage: raise ValueError('Draw condition stage differs from its original facility/batch declaration')
                roots[ref.key()] = ref
        outputs, outcomes = conditions(list(roots.values()))
        if profile.choice == 'decline_draw':
            reading.recheck(); return {'kind': 'completed', 'payload': {'choice': 'decline_draw', 'conditions': outputs, 'note': profile.note}}
        if request.status != 'submitted' or arrangement.status != 'active': _needs('active_original_facility_and_current_draw_request')
        clock(terms.draw_window.start)
        if not terms.draw_window.contains(now): _needs('original_facility_draw_window')
        purpose = read(action_input.purpose_ref, FundingPurposeView)
        if (not same(request.purpose_ref, purpose.ref) or purpose.borrower_ref.id != request.borrower_id
                or not scope_covers(purpose.scope_ref, context.scope)):
            raise ValueError('Draw purpose changes original borrower or authorized scope')
        if (_known(purpose.purpose_code, 'original_draw_purpose_code') not in terms.allowed_purpose_codes
                or _known(purpose.project_region_id, 'original_draw_region') not in terms.allowed_region_ids):
            _needs('original_facility_eligible_draw_purpose_and_region')
        if any(value != 'satisfied' for value in outcomes.values()): _needs('all_independent_current_batch_draw_conditions_satisfied', list(roots.values()))
        requested = amount(request.requested_amount, currency, True)
        if transfers(request.transfer_lines, currency) != requested: raise ValueError('Requested principal differs from original product transfer/fee basis')
        if profile.approved_amount is None: _needs('explicit_positive_original_approved_draw_amount')
        approved = amount(profile.approved_amount, currency, True)
        if approved > min(requested, remaining): _needs('approved_draw_within_request_and_all_current_facility_usage')
        if approved < requested and not terms.allow_partial: _needs('original_facility_permission_for_partial_draw')
        if transfers(profile.transfer_lines, currency, {line.destination_ref.key(): line for line in request.transfer_lines}) != approved:
            raise ValueError('Approved principal differs from original product transfer/fee basis')
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': 'approve_draw', 'conditions': outputs,
            'note': profile.note, 'approved_amount': profile.approved_amount,
            'transfer_lines': [line.model_dump(mode='python') for line in profile.transfer_lines]}}
    except ObservationGap as gap:
        reading.recheck(); return gap.result
