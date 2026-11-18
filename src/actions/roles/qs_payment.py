"""QS-A08 verifies original works and prepares independently authorized certificates."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Money
from src.actions.contracts.qs_payment_objects import (
    QSPaymentContractView, QSPaymentApplicationView, QSPaymentWorkView, QSPaymentRateView,
    QSPaymentConditionView, QSPaymentResultView, QSPaymentCertificateView, QSPaymentStatementView,
    QSPaymentAdjustmentView, QSPaymentCreditView, QSPaymentCreditAllocation, QSPaymentReceiptView,
    QSPaymentExecutionView, QSPaymentAuthorityView, QSPaymentCertificationView, QSPaymentCorrectionView,
    QSPaymentQuestionView, QSPaymentResponseView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction, exact_decimal
from src.methods.qs_cost import unknown
from src.methods.qs_payment import PAYMENT_METHOD, PaymentValuationInput
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def verify_payment(context, action_input, reading, action_contract=None):
    return _verify_payment(context, action_input, reading, action_contract=action_contract)


def prepare_payment_arithmetic(context, action_input, reading):
    """Prepare original work/history arithmetic without resolving future results."""
    reading.check_method_context(context, 'QS-A08')
    if action_input.measurement_result_refs:
        raise ValueError('Payment production requires source input without saved measurement results')
    return _verify_payment(context, action_input, reading, arithmetic_only=True)


def _verify_payment(context, action_input, reading, action_contract=None, *, arithmetic_only=False):
    scope, now, sources = action_input.scope, context.business_time, {}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('qs-payment-clock-alignment')

    def current(window, at):
        clock(window.start); clock(at)
        return window.contains(at)

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('qs-payment-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)

    def read(ref, schema, at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('qs-payment-projection:' + ref.kind)
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'scope') and row.scope != scope:
            raise ValueError('Payment record changes original requested scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_payment_record', [ref])
            if at is not None and not current(row.effective_window, at):
                _needs('applicable_original_payment_record', [ref])
        sources[ref.key()] = row
        return row

    def grant(ref, actor, function, action, at, qs=False, own=False):
        row = read(ref, Authorization); assignment = read(function, RoleAssignment)
        evidence(row.basis_refs + assignment.basis_refs)
        if row.actor_id != actor or row.function_ref != function:
            raise ValueError('Payment author changes original actor or function')
        if (qs and assignment.role != 'QS') or (own and row.organization_id != reading.organization_id):
            raise ValueError('Payment valuation substitutes original QS organization')
        prefixes = {'Owner': 'OWN-', 'Contractor': 'CONTRACTOR-', 'Supplier': 'SUPPLIER-', 'Architect': 'ARCHITECT-',
            'Engineer': 'ENGINEER-', 'QS': 'QS-', 'Government': 'GOV-', 'Bank': 'BANK-'}
        if (not action.startswith(prefixes[assignment.role]) or action not in row.action_ids
                or not current(row.validity, at) or not any(scope_covers(s, scope) for s in row.scopes)):
            _needs('original_payment_authorization', [ref])
        return row

    def author(row, qs=False, own=False):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not current(row.effective_window, row.authored_at):
            raise ValueError('Payment original author time is not applicable to its original version')
        if qs and row.author_action_id != 'QS-A08':
            raise ValueError('Saved payment valuation requires an original QS-A08 execution')
        return grant(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_action_id, row.authored_at, qs, own)

    def related(row, original_application=None):
        if row.contract_ref != contract.ref:
            raise ValueError('Payment record changes original contract version')
        if hasattr(row, 'application_ref') and row.application_ref != (original_application or application.ref):
            raise ValueError('Payment record changes original application version')

    def power(ref, actor, function, purpose, at, application_ref=None, key=None):
        row = read(ref, QSPaymentAuthorityView, at)
        if (row.contract_ref != contract.ref or row.actor_id != actor or row.function_ref != function
                or purpose not in row.purposes or row.application_ref not in (None, application_ref or application.ref)
                or (key is not None and row.certificate_key != key)):
            raise ValueError('Payment authority does not cover original purpose, actor, application or certificate identity')
        return row

    def amount(money):
        evidence([money.basis_ref])
        if money.currency != contract.currency:
            _unsupported('qs-payment-original-currency-conversion')
        return decimal_fraction(money.value)

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope,
            'note': 'Original work valuation only. Certification/correction awaits formal atomic acceptance; paid cash, advance allocation, unresolved rights and valid work obligations remain traceable.', **fields}}

    def questions(refs):
        unique_refs(refs); output = []
        for ref in refs:
            row = read(ref, QSPaymentQuestionView, now); related(row)
            response = read(row.response_requirement_ref, QSPaymentResponseView, now); related(response)
            if not set(row.recipient_ids) <= set(contract.party_ids) or not set(row.recipient_ids) <= set(response.recipient_ids):
                raise ValueError('Payment question changes original recipients or response requirements')
            output.append({'scope': scope, 'target_refs': [row.ref], 'question': row.question,
                'recipient_ids': row.recipient_ids, 'evidence_refs': row.evidence_refs,
                'blocking_uses': row.blocking_uses, 'response_requirement_ref': response.ref})
        return output

    def receipts(refs):
        from src.actions.roles.qs_receipts import reconcile_original_receipts
        return reconcile_original_receipts(contract, refs, read, amount)

    try:
        contract = read(action_input.contract_ref, QSPaymentContractView, now)
        application = read(action_input.application_ref, QSPaymentApplicationView, now)
        related(application); author(application)
        if application.applicant_id != application.author_actor_id or application.applicant_id != contract.beneficiary_id:
            raise ValueError('Payment application is not the original beneficiary submission')
        if (contract.valuation_actor_id != context.actor_id or contract.valuation_function_ref != context.function_ref
                or contract.valuation_organization_id != reading.organization_id):
            raise ValueError('Contract does not appoint this scoped QS valuation function')
        grant(contract.valuation_authority_ref, context.actor_id, context.function_ref, 'QS-A08', now, True, True)
        clock(application.period.start); clock(application.period.end)
        if application.status == 'withdrawn':
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'qs_payment_application_withdrawn', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [application.ref], 'earliest_time': None,
                'condition_code': 'qs.payment.original_application_submitted'}}
        for refs in (action_input.performed_work_refs, action_input.prior_certificate_refs,
                     action_input.payment_receipt_refs, action_input.measurement_result_refs):
            unique_refs(refs)
        if set(action_input.performed_work_refs) != set(application.work_refs):
            _needs('complete_original_application_work_set')
        if set(action_input.prior_certificate_refs) != set(contract.active_certificate_refs):
            _needs('complete_original_active_certificate_history')
        if set(action_input.payment_receipt_refs) != set(contract.receipt_refs):
            _needs('complete_original_visible_payment_history')
        expected_results = [ref for ref in (application.valuation_result_ref, application.retention_result_ref,
            application.deduction_result_ref) if ref is not None]
        unique_refs(expected_results)
        if not arithmetic_only and set(action_input.measurement_result_refs) != set(expected_results):
            _needs('exact_original_application_measurement_results')
        if (not arithmetic_only and application.valuation_result_ref is None) or not application.work_refs:
            output = questions(application.question_refs)
            if not output:
                _needs('original_payment_measurement_question')
            return completed('request_evidence', questions=output)
        if arithmetic_only and application.valuation_result_ref is None:
            _needs('original_payment_valuation_target')

        certificates, original_reports = [], {}
        for ref in action_input.prior_certificate_refs:
            row = read(ref, QSPaymentCertificateView); related(row, row.application_ref); author(row, True)
            if row.status != 'active':
                _needs('original_current_effective_certificate', [ref])
            power(row.certification_authority_ref, row.author_actor_id, row.author_function_ref,
                'correct' if row.predecessor_ref is not None else 'certify', row.authored_at, row.application_ref, row.certificate_key)
            statement = read(row.statement_ref, QSPaymentStatementView); author(statement, True)
            if statement.contract_ref != contract.ref or statement.certificate_ref != row.ref or statement.calculation_ref != row.calculation_ref:
                raise ValueError('Certificate substitutes its original valuation statement')
            old = read(row.calculation_ref, QSPaymentResultView); related(old, row.application_ref); author(old, True)
            if arithmetic_only and old.ref in expected_results:
                raise ValueError('Payment production cannot replace an original prior certificate calculation')
            if old.status != 'ok' or old.report is None or old.result_kind != 'valuation' or old.method_ref != PAYMENT_METHOD:
                _needs('original_successful_certificate_calculation', [row.ref])
            if (old.report.net_amount.state != 'known' or old.report.net_period_delta.state != 'known'
                    or old.report.retention_amount.state != 'known'):
                raise ValueError('An original formal certificate cannot carry unknown net entitlement')
            amount(row.assessed_contribution); amount(row.net_contribution)
            amount(row.retention_contribution)
            expected_assessed, expected_net = old.report.assessed_period_delta, old.report.net_period_delta.value
            if old.report.retention_period_delta.state != 'known':
                raise ValueError('Original certificate lacks its retained current-period contribution')
            expected_retention = old.report.retention_period_delta.value
            if row.predecessor_ref != old.correction_of:
                raise ValueError('Corrected certificate must bind the exact original replaced version')
            if row.predecessor_ref is not None:
                predecessor = read(row.predecessor_ref, QSPaymentCertificateView); author(predecessor, True)
                if (predecessor.contract_ref != contract.ref or predecessor.certificate_key != row.certificate_key
                        or predecessor.sequence != row.sequence or predecessor.status != 'superseded'):
                    raise ValueError('Corrected certificate substitutes its original obligation identity or sequence')
                if old.valuation_basis == 'incremental':
                    expected_assessed, expected_net = old.report.assessed_amount, old.report.net_amount.value
                    expected_retention = old.report.retention_amount.value
                else:
                    expected_assessed = Money(value=exact_decimal(amount(predecessor.assessed_contribution) + amount(expected_assessed)),
                        currency=contract.currency, basis_ref=row.assessed_contribution.basis_ref)
                    expected_net = Money(value=exact_decimal(amount(predecessor.net_contribution) + amount(expected_net)),
                        currency=contract.currency, basis_ref=row.net_contribution.basis_ref)
                    expected_retention = Money(value=exact_decimal(amount(predecessor.retention_contribution) + amount(expected_retention)),
                        currency=contract.currency, basis_ref=row.retention_contribution.basis_ref)
            if (amount(row.assessed_contribution) != amount(expected_assessed) or amount(row.net_contribution) != amount(expected_net)
                    or amount(row.retention_contribution) != amount(expected_retention)):
                raise ValueError('Prior certificate changes its original current-period contributions')
            if old.available_at.offset > row.authored_at.offset:
                raise ValueError('Certificate predates its original saved calculation')
            certificates.append(row); original_reports[row.ref] = old.report
        if (len({r.certificate_key for r in certificates}) != len(certificates)
                or len({r.sequence for r in certificates}) != len(certificates)
                or len({r.statement_ref.key() for r in certificates}) != len(certificates)):
            raise ValueError('Certificate history repeats obligation identity, sequence or statement')
        if sorted(r.sequence for r in certificates) != list(range(1, len(certificates) + 1)):
            raise ValueError('Certificate history is incomplete')

        correction = None
        if application.correction_basis_ref is not None:
            correction = read(application.correction_basis_ref, QSPaymentCorrectionView, now); related(correction); author(correction)
            target = next((r for r in certificates if r.ref == correction.prior_certificate_ref), None)
            if target is None or target.certificate_key != correction.certificate_key:
                raise ValueError('Correction must preserve the selected original active certificate identity')

        prior_work = {key for r in certificates for key in r.work_keys}
        lines = []
        for ref in action_input.performed_work_refs:
            row = read(ref, QSPaymentWorkView); related(row); author(row)
            clock(row.period.start); clock(row.period.end)
            if row.period.start.offset < application.period.start.offset or row.period.end.offset > application.period.end.offset:
                raise ValueError('Original performed work falls outside the application period')
            if application.basis == 'incremental' and row.work_key in prior_work:
                if correction is None or row.work_key not in target.work_keys:
                    raise ValueError('Incremental application repeats already valued physical work')
            if row.rate_ref not in contract.rate_refs:
                raise ValueError('Work uses a rate outside the original contract')
            rate = read(row.rate_ref, QSPaymentRateView, row.period.end); related(rate)
            condition = read(row.condition_ref, QSPaymentConditionView); related(condition); author(condition)
            if condition.work_ref != row.ref:
                raise ValueError('Payment condition concerns a different original work version')
            power(condition.condition_authority_ref, condition.author_actor_id, condition.author_function_ref,
                'condition', condition.authored_at)
            amount(rate.amount); evidence([row.quantity.basis_ref])
            lines.append({'work_key': row.work_key, 'quantity': row.quantity, 'rate': rate.amount,
                'rate_unit': rate.quantity_unit, 'eligible': condition.fulfilled})
        if application.basis == 'cumulative':
            reusable = {key for certificate in certificates if correction is None or certificate.ref != target.ref
                        for key in certificate.work_keys}
            if not reusable <= {line['work_key'] for line in lines}:
                _needs('complete_original_cumulative_work_coverage')

        cash = receipts(action_input.payment_receipt_refs)
        paid = Fraction(); cash_unknown = contract.certified_cash_visibility == 'unavailable'
        for (purpose, ref), (value, uncertain) in cash.items():
            if purpose != 'certified_payment':
                continue
            if ref not in {r.ref for r in certificates}:
                # Historic superseded certificates still own their original received cash.
                historic = read(ref, QSPaymentCertificateView)
                if historic.contract_ref != contract.ref or historic.certificate_key not in {r.certificate_key for r in certificates}:
                    raise ValueError('Paid cash belongs to an unrelated certificate obligation')
            paid += value; cash_unknown |= uncertain
        paid_total = unknown('certified_cash_not_visible') if cash_unknown else {'state': 'known', 'value': Money(
            value=exact_decimal(paid), currency=contract.currency, basis_ref=contract.evidence_refs[0])}

        deductions = []
        for ref in contract.deduction_refs:
            row = read(ref, QSPaymentAdjustmentView, now); related(row); author(row)
            power(row.deduction_authority_ref, row.author_actor_id, row.author_function_ref, 'deduct', row.authored_at)
            amount(row.amount); deductions.append(row.amount)
        credits, used_sources = [], set()
        for ref in contract.advance_credit_refs:
            credit = read(ref, QSPaymentCreditView, now); related(credit)
            if not set(credit.source_receipt_refs) <= set(action_input.payment_receipt_refs):
                _needs('original_advance_cash_receipts', credit.source_receipt_refs)
            funded, uncertain = cash.get(('advance', credit.ref), (Fraction(), False))
            if uncertain or funded != amount(credit.received_amount):
                _needs('verified_original_advance_credit_cash', credit.source_receipt_refs)
            for source in credit.source_receipt_refs:
                original_receipt = read(source, QSPaymentReceiptView)
                if original_receipt.credit_ref != credit.ref or original_receipt.purpose != 'advance':
                    raise ValueError('Advance offset reuses a certified-payment receipt')
                if source.key() in used_sources:
                    raise ValueError('One original advance receipt cannot fund multiple credits')
                used_sources.add(source.key())
            if set(credit.source_receipt_refs) != {r.ref for r in sources.values() if isinstance(r, QSPaymentReceiptView) and r.credit_ref == credit.ref}:
                _needs('complete_original_advance_credit_cash_history')
            used = Fraction()
            for allocation_ref in credit.allocation_refs:
                allocation = read(allocation_ref, QSPaymentCreditAllocation)
                if allocation.contract_ref != contract.ref or allocation.credit_ref != credit.ref:
                    raise ValueError('Advance allocation changes its original credit or contract')
                original_certificate = read(allocation.certificate_ref, QSPaymentCertificateView)
                if original_certificate.contract_ref != contract.ref or allocation not in original_certificate.advance_allocations:
                    raise ValueError('Advance allocation lacks its original certificate linkage')
                used += amount(allocation.amount)
            declared_allocations = {a.ref for r in certificates for a in r.advance_allocations if a.credit_ref == credit.ref}
            if not declared_allocations <= set(credit.allocation_refs):
                _needs('complete_original_advance_credit_allocation_history')
            offset = amount(credit.offset_amount)
            included = used if application.basis == 'cumulative' else Fraction()
            if correction is not None and application.basis == 'incremental':
                included = sum((amount(a.amount) for a in target.advance_allocations if a.credit_ref == credit.ref), Fraction())
            if offset < included or used + offset - included > funded:
                raise ValueError('Advance offset duplicates already allocated credit or exceeds received cash')
            credits.append(credit.offset_amount)

        if contract.retention_cap is not None:
            amount(contract.retention_cap)
        required_sources = [row.ref for row in sources.values() if hasattr(row, 'ref') and row.ref.kind not in {'MethodResult', 'Authorization', 'FunctionAssignment', 'Authority', 'CertificationBasis', 'CorrectionBasis'}]
        data = PaymentValuationInput(currency=contract.currency, decimal_places=contract.decimal_places,
            basis=application.basis, lines=lines, retention_fraction=contract.retention_fraction,
            retention_cap=contract.retention_cap, deductions=deductions, advance_offsets=credits,
            prior_assessed=[r.assessed_contribution for r in certificates], prior_net=[r.net_contribution for r in certificates],
            prior_retention=[r.retention_contribution for r in certificates],
            corrected_assessed=original_reports[target.ref].assessed_amount if correction is not None and application.basis == 'incremental' else None,
            corrected_net=original_reports[target.ref].net_amount.value if correction is not None and application.basis == 'incremental' else None,
            corrected_retention=original_reports[target.ref].retention_amount.value if correction is not None and application.basis == 'incremental' else None,
            paid_total=paid_total, source_refs=sorted(required_sources, key=lambda ref: repr(ref.key())))
        if arithmetic_only:
            if application.retention_result_ref is None and decimal_fraction(contract.retention_fraction) != 0:
                _needs('original_retention_calculation_target')
            if application.deduction_result_ref is None and deductions:
                _needs('original_deduction_calculation_target')
            reading.recheck()
            return {'kind': 'prepared', 'input': data, 'contract_ref': contract.ref,
                'application_ref': application.ref, 'valuation_basis': application.basis,
                'correction_of': target.ref if correction is not None else None,
                'result_refs': {kind: ref for kind, ref in [('valuation', application.valuation_result_ref),
                    ('retention', application.retention_result_ref), ('deduction', application.deduction_result_ref)]
                    if ref is not None}}
        result = reading.calculate(PAYMENT_METHOD, data)
        if result.kind != 'ok':
            if result.kind == 'invalid_input':
                raise ValueError('Original payment arithmetic violates registered support domain')
            raw = result.model_dump(mode='python')
            if result.kind == 'needs_information':
                raw['requested_refs'] = []
            raise ObservationGap(raw)
        report = result.value
        for kind, ref in [('valuation', application.valuation_result_ref), ('retention', application.retention_result_ref),
                          ('deduction', application.deduction_result_ref)]:
            if ref is None:
                if kind == 'retention' and decimal_fraction(contract.retention_fraction) != 0:
                    _needs('original_retention_calculation_result')
                if kind == 'deduction' and deductions:
                    _needs('original_deduction_calculation_result')
                continue
            saved = read(ref, QSPaymentResultView); related(saved); original_grant = author(saved, True, True)
            if saved.method_ref != PAYMENT_METHOD or saved.result_kind != kind:
                _unsupported('qs-payment-original-measurement-result-domain')
            if saved.valuation_basis != application.basis or saved.correction_of != (target.ref if correction is not None else None):
                raise ValueError('Saved valuation changes its original cumulative/incremental or correction target')
            if saved.status == 'unsupported':
                _unsupported('qs-payment-saved-calculation-domain')
            if saved.status == 'failed':
                raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                    'correlation_id': context.operation_id, 'code': 'original_payment_method_failed'}, 'retryability': 'unknown'})
            if saved.input_sha256 != content_digest(data) or saved.report != report:
                raise ValueError('Saved payment result changes original inputs, measured amounts, offsets or payment history')
            readable = {ref.key() for ref in original_grant.readable_refs}
            if not {ref.key() for ref in required_sources} <= readable:
                _needs('original_payment_calculation_source_read_authority', [ref])
            if any(sources[source.key()].available_at.offset > saved.authored_at.offset for source in required_sources):
                _needs('payment_calculation_from_received_original_versions', [ref])

        statement = {'contract_ref': contract.ref, 'source_application_ref': application.ref, 'covered_scope': scope,
            'period': application.period, 'basis': application.basis, 'calculation_ref': application.valuation_result_ref,
            'assessed_amount': report.assessed_amount, 'recognized_amount': report.recognized_amount,
            'disputed_amount': report.disputed_amount, 'retention_result_ref': application.retention_result_ref,
            'deduction_result_ref': application.deduction_result_ref, 'prior_statement_refs': [r.statement_ref for r in certificates],
            'entitlement_refs': [], 'unresolved_questions': questions(application.unresolved_question_refs)}
        if action_input.certification_authority_ref is None:
            return completed('verify', statement=statement)
        if report.net_amount.state != 'known':
            _needs('known_original_payment_conditions_before_certification')
        if action_contract is None:
            from src.actions.contracts.catalog import ContractCatalog
            action_contract = ContractCatalog().contracts['QS-A08']
        checked = action_contract.validate_payload({'scope': scope, 'choice': 'verify', 'statement': statement,
            'note': 'Original statement digest'}).statement
        if correction is not None:
            basis, purpose = correction, 'correct'
        elif application.certification_basis_ref is not None:
            basis = read(application.certification_basis_ref, QSPaymentCertificationView, now); related(basis); author(basis)
            purpose = 'certify'
            if basis.certificate_key in {r.certificate_key for r in certificates}:
                _needs('query_existing_original_certificate_before_resubmission')
        else:
            _needs('original_independent_certification_basis')
        if (basis.authority_ref != action_input.certification_authority_ref or basis.actor_id != context.actor_id
                or basis.function_ref != context.function_ref or basis.statement_sha256 != content_digest(checked)):
            raise ValueError('Certificate basis changes acting QS, independent authority or complete statement')
        power(basis.authority_ref, context.actor_id, context.function_ref, purpose, now, key=basis.certificate_key)
        if purpose == 'correct':
            return completed('correct_certificate', prior_certificate_ref=target.ref, statement=statement, correction_basis_ref=basis.ref)
        return completed('certify', statement=statement, certification_basis_ref=basis.ref)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
