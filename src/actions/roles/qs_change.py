"""QS-A07 preserves original arithmetic, unresolved rights and determination powers."""
import hashlib
import json

from src.actions.contracts.common import EvidenceRecord, ref_type
from src.actions.contracts.qs_change_objects import (
    QSChangeContractView, QSChangeClaimView, QSChangeInstructionView, QSChangeLineView,
    QSChangeStatementView, QSChangeResultView, QSChangeAuthorityView, QSChangeEntitlementView,
    QSChangeDeterminationView, QSChangeQuestionView, QSChangeResponseView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.qs_change import CHANGE_METHOD, ChangeArithmeticInput
from src.methods.qs_cost import unknown
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def content_digest(record):
    return hashlib.sha256(json.dumps(record.model_dump(mode='json'), sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def value_change(context, action_input, reading, action_contract=None):
    return _value_change(context, action_input, reading, action_contract=action_contract)


def prepare_change_arithmetic(context, action_input, reading, *, calculation_ref):
    """Reuse original claim/history checks without requiring a saved calculation."""
    reading.check_method_context(context, 'QS-A07')
    if action_input.valuation_result_ref is not None:
        raise ValueError('Change production requires source input without an existing valuation result')
    calculation_ref = ref_type('MethodResult').model_validate(calculation_ref)
    return _value_change(context, action_input, reading, calculation_ref=calculation_ref)


def _value_change(context, action_input, reading, action_contract=None, *, calculation_ref=None):
    arithmetic_only = calculation_ref is not None
    scope, now = action_input.scope, context.business_time
    inputs = {}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('qs-change-clock-alignment')

    def current(window, at):
        clock(window.start); clock(at)
        return window.contains(at)

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('qs-change-evidence-schema')
            # Historic contract/change evidence may legitimately describe an earlier period.
            if row.effective_window is not None:
                clock(row.effective_window.start)

    def read(ref, schema, at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('qs-change-projection:' + ref.kind)
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'scope') and row.scope != scope:
            raise ValueError('Change valuation substitutes a different original scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_change_input', [ref])
            if at is not None and not current(row.effective_window, at):
                _needs('applicable_original_change_input', [ref])
            inputs[ref.key()] = row
        return row

    def grant(ref, actor, function, action, at, role=None, organization=None):
        row = read(ref, Authorization)
        assignment = read(function, RoleAssignment)
        evidence(row.basis_refs + assignment.basis_refs)
        if (row.actor_id != actor or row.function_ref != function
                or (role is not None and assignment.role != role)
                or (organization is not None and row.organization_id != organization)):
            raise ValueError('Change author substitutes original actor, function or organization')
        if action not in row.action_ids or not current(row.validity, at) or not any(scope_covers(s, scope) for s in row.scopes):
            _needs('original_change_authorization', [ref])
        return assignment

    def author(row, qs=False):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset:
            raise ValueError('Original change record cannot be available before its creation')
        if not current(row.effective_window, row.authored_at):
            _needs('change_record_at_original_creation', [row.ref])
        if qs and row.author_action_id != 'QS-A07':
            raise ValueError('Saved valuation must be an original QS-A07 execution')
        assignment = grant(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_action_id, row.authored_at, 'QS' if qs else None,
            reading.organization_id if qs else None)
        prefixes = {'Owner': 'OWN-', 'Contractor': 'CONTRACTOR-', 'Supplier': 'SUPPLIER-',
            'Architect': 'ARCHITECT-', 'Engineer': 'ENGINEER-', 'QS': 'QS-', 'Government': 'GOV-', 'Bank': 'BANK-'}
        if not row.author_action_id.startswith(prefixes[assignment.role]):
            raise ValueError('Original change action does not belong to its author function')
        return assignment

    def related(row):
        if row.contract_ref != contract.ref or row.claim_ref != claim.ref:
            raise ValueError('Change source substitutes an original contract or claim version')

    def independent(ref, row, purpose, actor=None, function=None, at=None):
        power = read(ref, QSChangeAuthorityView, at or now)
        related(power)
        if (purpose not in power.purposes or power.actor_id != (actor or row.author_actor_id)
                or power.function_ref != (function or row.author_function_ref)):
            raise ValueError('Independent change power does not cover original purpose or actor')
        return power

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'scope': scope, 'choice': choice,
            'note': 'Scoped valuation only; unresolved entitlement remains unresolved. Contract, debt, cash and valid work obligations require their own formal effects.', **fields}}

    def question_refs(refs):
        questions = []
        unique_refs(refs)
        for ref in refs:
            row = read(ref, QSChangeQuestionView, now); related(row)
            response = read(row.response_requirement_ref, QSChangeResponseView, now); related(response)
            if not set(row.recipient_ids) <= set(response.recipient_ids) or not set(row.recipient_ids) <= set(contract.party_ids):
                raise ValueError('Change question substitutes original contract recipients')
            questions.append({'scope': scope, 'target_refs': [row.ref], 'question': row.question,
                'recipient_ids': row.recipient_ids, 'evidence_refs': row.evidence_refs,
                'blocking_uses': row.blocking_uses, 'response_requirement_ref': response.ref})
        return questions

    def money_equal(left, right):
        return left.currency == right.currency and decimal_fraction(left.value) == decimal_fraction(right.value)

    try:
        contract = read(action_input.contract_ref, QSChangeContractView, now)
        claim = read(action_input.claim_or_change_ref, QSChangeClaimView, now)
        author(claim)
        if (claim.contract_ref != contract.ref or claim.instruction_ref != action_input.instruction_ref
                or claim.claimant_id != claim.author_actor_id or claim.claimant_id not in contract.party_ids):
            raise ValueError('Claim substitutes contract, original instruction or claimant')
        if (contract.valuation_actor_id != context.actor_id or contract.valuation_function_ref != context.function_ref
                or contract.valuation_organization_id != reading.organization_id):
            raise ValueError('Contract does not appoint this QS valuation function')
        grant(contract.valuation_authority_ref, context.actor_id, context.function_ref, 'QS-A07', now, 'QS', reading.organization_id)
        clock(claim.period.start); clock(claim.period.end)
        unique_refs(action_input.evidence_refs); evidence(action_input.evidence_refs)
        if claim.status == 'withdrawn':
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'qs_change_claim_withdrawn', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [claim.ref], 'earliest_time': None,
                'condition_code': 'qs.change.original_claim_submitted'}}
        if action_input.instruction_ref is not None:
            instruction = read(action_input.instruction_ref, QSChangeInstructionView)
            related(instruction); author(instruction)
            independent(instruction.instruction_authority_ref, instruction, 'instruct', at=instruction.authored_at)
        if not arithmetic_only and action_input.valuation_result_ref is None:
            questions = question_refs(claim.question_refs)
            if not questions:
                _needs('original_change_valuation_question')
            return completed('request_evidence', questions=questions)
        saved = None
        calculation_at = now
        if not arithmetic_only:
            saved = read(action_input.valuation_result_ref, QSChangeResultView)
            related(saved); author(saved, qs=True)
            calculation_ref, calculation_at = saved.ref, saved.authored_at
            if saved.method_ref != CHANGE_METHOD:
                _unsupported('qs-change-original-valuation-method')
            if saved.status == 'unsupported':
                _unsupported('qs-change-saved-calculation-domain')
            if saved.status == 'failed':
                raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                    'correlation_id': context.operation_id, 'code': 'original_change_method_failed'}, 'retryability': 'unknown'})
        lines = [read(ref, QSChangeLineView) for ref in claim.line_refs]
        for line in lines:
            related(line); author(line)
            evidence([line.calculation_line.quantity_delta.basis_ref, line.calculation_line.unit_rate.basis_ref])
        if not lines:
            questions = question_refs(claim.question_refs)
            if not questions:
                _needs('original_change_quantity_price_evidence')
            return completed('request_evidence', questions=questions)
        statements = [read(ref, QSChangeStatementView) for ref in claim.prior_statement_refs]
        if sorted(r.sequence for r in statements) != list(range(1, len(statements) + 1)):
            raise ValueError('Cumulative change history must preserve complete consecutive original statements')
        original_calculations = []
        for statement in statements:
            if (statement.contract_ref != contract.ref or statement.claim_ref.id != claim.ref.id):
                raise ValueError('Prior statement changes original contract or physical claim')
            author(statement, qs=True)
            original = read(statement.calculation_ref, QSChangeResultView)
            if original.contract_ref != contract.ref or original.claim_ref != statement.claim_ref:
                raise ValueError('Prior calculation changes its original statement claim version')
            author(original, qs=True)
            if (original.ref == calculation_ref or original.status != 'ok' or original.method_ref != CHANGE_METHOD
                    or original.period_delta is None or not money_equal(statement.period_delta, original.period_delta)
                    or original.authored_at.offset > statement.authored_at.offset
                    or statement.available_at.offset > calculation_at.offset):
                raise ValueError('Prior statement lacks its original successful earlier valuation delta')
            evidence([statement.period_delta.basis_ref])
            original_calculations.append(original.ref)
        unique_refs(original_calculations)
        source_refs = [contract.ref, claim.ref, *claim.line_refs, *claim.prior_statement_refs, *action_input.evidence_refs]
        if action_input.instruction_ref is not None:
            source_refs.append(action_input.instruction_ref)
        data = ChangeArithmeticInput(currency=contract.currency, decimal_places=contract.decimal_places,
            basis=claim.basis, lines=[r.calculation_line for r in lines],
            prior_amounts=[r.period_delta for r in sorted(statements, key=lambda r: r.sequence)], source_refs=source_refs)
        if arithmetic_only:
            for ref in source_refs:
                row = inputs.get(ref.key())
                if row is not None and (row.available_at.offset > calculation_at.offset
                        or (not isinstance(row, QSChangeStatementView) and not current(row.effective_window, calculation_at))):
                    _needs('change_calculation_from_available_applicable_original_versions', [ref])
            reading.recheck()
            return {'kind': 'prepared', 'input': data, 'contract_ref': contract.ref, 'claim_ref': claim.ref}
        if saved.input_sha256 != content_digest(data):
            raise ValueError('Saved valuation does not bind original contract, claim, quantities, rates and complete history')
        calculation_grant = read(saved.author_authority_ref, Authorization)
        readable = {ref.key() for ref in calculation_grant.readable_refs}
        if not {ref.key() for ref in source_refs} <= readable:
            _needs('original_change_calculation_source_read_authority', [saved.ref])
        for ref in source_refs:
            row = inputs.get(ref.key())
            if row is not None and (row.available_at.offset > saved.authored_at.offset
                    or (not isinstance(row, QSChangeStatementView) and not current(row.effective_window, saved.authored_at))):
                _needs('change_calculation_from_available_applicable_original_versions', [ref])
        result = reading.calculate(CHANGE_METHOD, data)
        if result.kind != 'ok':
            if result.kind == 'invalid_input':
                raise ValueError('Original change arithmetic violates the registered domain')
            raw = result.model_dump(mode='python')
            if result.kind == 'needs_information':
                raw['requested_refs'] = []
            raise ObservationGap(raw)
        report = result.value
        if (saved.assessed_amount != report.assessed_amount or saved.period_delta != report.period_delta):
            raise ValueError('Saved valuation differs from original signed quantities, rates, precision or period delta')
        recognized, disputed = unknown('entitlement_not_decided'), unknown('entitlement_not_decided')
        entitlements = []
        if action_input.entitlement_ref is not None:
            decision = read(action_input.entitlement_ref, QSChangeEntitlementView, now)
            related(decision); author(decision)
            independent(decision.decision_authority_ref, decision, 'entitlement', at=decision.authored_at)
            entitlements = [decision.ref]
            if decision.status == 'pending':
                if any(s.state == 'known' for s in (decision.payer_id, decision.recognized_amount, decision.disputed_amount)):
                    raise ValueError('Pending entitlement cannot claim a determined payer or recognized monetary split')
            else:
                if decision.calculation_ref != saved.ref:
                    raise ValueError('Entitlement amounts refer to another valuation version')
                recognized, disputed = decision.recognized_amount, decision.disputed_amount
                if recognized.state != 'known' or disputed.state != 'known':
                    _needs('original_decided_entitlement_amounts', [decision.ref])
                evidence([recognized.value.basis_ref, disputed.value.basis_ref])
                if (recognized.value.currency != contract.currency or disputed.value.currency != contract.currency
                        or decimal_fraction(recognized.value.value) + decimal_fraction(disputed.value.value)
                            != decimal_fraction(saved.assessed_amount.value)):
                    raise ValueError('Original entitlement split does not equal the assessed valuation')
                if decision.payer_id.state == 'known' and decision.payer_id.value not in contract.party_ids:
                    raise ValueError('Entitlement names a payer outside original contract parties')
        valuation = {'contract_ref': contract.ref, 'source_application_ref': claim.ref, 'covered_scope': scope,
            'period': claim.period, 'basis': claim.basis, 'calculation_ref': saved.ref,
            'assessed_amount': saved.assessed_amount, 'recognized_amount': recognized, 'disputed_amount': disputed,
            'retention_result_ref': None, 'deduction_result_ref': None, 'prior_statement_refs': claim.prior_statement_refs,
            'entitlement_refs': entitlements, 'unresolved_questions': question_refs(claim.unresolved_question_refs)}
        if claim.determination_basis_ref is None:
            return completed('value', valuation=valuation)
        basis = read(claim.determination_basis_ref, QSChangeDeterminationView, now)
        related(basis); author(basis)
        if basis.actor_id != context.actor_id or basis.function_ref != context.function_ref or basis.calculation_ref != saved.ref:
            raise ValueError('Determination basis substitutes acting QS or original valuation version')
        independent(basis.determination_authority_ref, basis, 'determine', context.actor_id, context.function_ref)
        if action_contract is None:
            from src.actions.contracts.catalog import ContractCatalog
            action_contract = ContractCatalog().contracts['QS-A07']
        checked = action_contract.validate_payload({'scope': scope, 'choice': 'value',
            'valuation': valuation, 'note': 'Original valuation digest'}).valuation
        if basis.valuation_sha256 != content_digest(checked):
            raise ValueError('Independent determination basis does not bind the entire original valuation')
        return completed('determine_authorized', valuation=valuation, determination_basis_ref=basis.ref)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
