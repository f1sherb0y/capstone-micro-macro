"""BANK-A04 sourced quotation; no offer registration or capacity reservation."""
from fractions import Fraction

from src.actions.contracts.bank_credit_objects import (
    CreditAccountView, CreditAssumptionView, CreditLoanFactor, CreditRuleView, unique_identities,
)
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.bank_quote_objects import (
    QuoteAuthorityPolicyView, QuoteCreditAssessmentView, QuoteFeeView,
    QuoteFundingPathView, QuotePricingView, QuoteProductPolicyView, QuoteProductView,
    QuoteRecordedReviewView, QuoteRepaymentView, QuoteReservationView, projection_digest,
)
from src.actions.contracts.common import EvidenceRecord, Money, TimeWindow, walk_references
from src.actions.roles.bank_credit import review_credit
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.bank_credit import CREDIT_CASH_METHOD, CreditCashInput, CreditCashMovement
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def quote_finance(context, action_input, reading):
    now, lender = context.business_time, reading.organization_id
    sources, basis = {}, {}

    def evidence(refs, point=None):
        for ref in refs:
            value = reading.resolve(ref)
            if not isinstance(value, EvidenceRecord):
                _unsupported('bank-quote-evidence-schema')
            if value.effective_window is not None:
                current(value.effective_window, 'current_quote_evidence', point)
            basis[ref.key()] = ref

    def read(ref, schema, point=None, *, at_field=None):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f'bank-quote-projection:{ref.kind}')
        sources[ref.key()] = ref
        if at_field is not None:
            point = getattr(value, at_field)
        if point is not None:
            if point.clock_ref != now.clock_ref:
                _unsupported('bank-quote-clock-alignment')
            if point.offset > now.offset:
                _needs('available_original_quote_source')
        evidence(getattr(value, 'evidence_refs', []), point)
        return value

    def current(window, field, point=None):
        if window.start.clock_ref != now.clock_ref:
            _unsupported('bank-quote-clock-alignment')
        if not window.contains(point or now):
            _needs(field)

    def amount(value):
        evidence([value.basis_ref])
        if value.currency != application.requested.currency:
            _unsupported('bank-quote-currency-conversion')
        return decimal_fraction(value.value)

    def money(value, ref):
        return Money(value=exact_decimal(value), currency=application.requested.currency, basis_ref=ref)

    def completed(choice, note, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'note': note, **fields}}

    def authorized(grant, actor, organization, function, action, point):
        assignment = read(function, RoleAssignment, point)
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], point)
            else:
                reading.resolve(basis_ref)
                sources[basis_ref.key()] = basis_ref
        return (assignment.role == 'Bank' and grant.actor_id == actor
                and grant.organization_id == organization and grant.function_ref == function
                and assignment.function_ref == function
                and action in grant.action_ids and point.clock_ref == now.clock_ref
                and grant.validity.contains(point)
                and any(scope_covers(scope, application.scope_ref) for scope in grant.scopes))

    def terms_source(row, *, check_current=True):
        if (row.application_ref != application.ref or row.product_ref != product.ref
                or row.borrower_id != application.borrower_id or row.lender_id != lender):
            raise ValueError('Quote term source changes application, product, borrower or lender')
        if check_current:
            current(row.effective_window, 'current_quote_terms')

    def at(point, tenor, field):
        if point.clock_ref != now.clock_ref:
            _unsupported('bank-quote-clock-alignment')
        if not tenor.contains(point) or point.offset < now.offset:
            _needs(field)

    try:
        application = read(action_input.application_ref, FinanceApplicationView)
        product = read(action_input.product_ref, QuoteProductView)
        assessment = read(action_input.assessment_ref, QuoteCreditAssessmentView, at_field='reviewed_at')
        if (application.lender_id != lender or product.lender_id != lender
                or assessment.source_run_id != context.run_id
                or assessment.lender_id != lender or assessment.borrower_id != application.borrower_id
                or assessment.scope_ref != application.scope_ref
                or assessment.application_ref != application.ref or assessment.product_ref != product.ref):
            raise ValueError('Quote review changes the original run, application, borrower, product or bank')
        current(assessment.effective_window, 'current_quote_assessment')
        if assessment.status != 'recorded':
            _needs('active_recorded_credit_assessment')
        if assessment.available_at.clock_ref != now.clock_ref or assessment.available_at.offset > now.offset:
            _needs('available_credit_assessment')
        if assessment.dependency_coverage != 'complete':
            _needs('complete_credit_assessment_dependencies')
        for dependency in assessment.source_dependencies:
            value = reading.resolve(dependency.ref)
            sources[dependency.ref.key()] = dependency.ref
            if projection_digest(value) != dependency.projection_sha256:
                _needs('unchanged_credit_assessment_dependencies', [dependency.ref])
        recorded = read(assessment.recorded_decision_ref, QuoteRecordedReviewView, at_field='business_time')
        if (recorded.source_run_id != assessment.source_run_id or recorded.actor_id != assessment.author_actor_id
                or recorded.organization_id != lender or recorded.function_ref != assessment.author_function_ref
                or recorded.authority_refs != assessment.authority_refs or recorded.scope_ref != assessment.scope_ref
                or recorded.business_time != assessment.reviewed_at or recorded.input != assessment.review_input
                or recorded.payload != assessment.review_payload):
            raise ValueError('Received assessment does not match its original recorded decision')
        author_grants = [read(ref, Authorization, assessment.reviewed_at) for ref in assessment.authority_refs]
        required_reads = {ref.key() for value in (assessment.review_input, assessment.review_payload)
                          for ref in walk_references(value)}
        valid_grants = [grant for grant in author_grants if authorized(grant, assessment.author_actor_id,
            lender, assessment.author_function_ref, 'BANK-A03', assessment.reviewed_at)]
        if not valid_grants or not required_reads <= {ref.key() for grant in valid_grants for ref in grant.readable_refs}:
            _needs('authorized_original_credit_assessment')
        evidence(assessment.method_audit_refs, assessment.reviewed_at)

        grant = read(action_input.authority_ref, Authorization)
        if (grant.ref not in context.authorization_refs or not authorized(grant, context.actor_id, lender,
                context.function_ref, 'BANK-A04', now)):
            _needs('independent_current_quote_authority', [grant.ref])
        policy_refs = [ref for ref in grant.basis_refs if ref.kind == 'QuoteAuthorityPolicy']
        if len(policy_refs) != 1:
            _needs('explicit_quote_authority_limits')
        authority = read(policy_refs[0], QuoteAuthorityPolicyView)
        if (authority.authority_ref != grant.ref or authority.application_ref != application.ref
                or authority.product_ref != product.ref or authority.lender_id != lender
                or not scope_covers(authority.scope_ref, application.scope_ref)):
            raise ValueError('Quote amount authority belongs to another grant or application')
        current(authority.effective_window, 'current_quote_authority_limits')
        authorized_max = amount(_known(authority.maximum_principal, 'quote_authority_maximum'))
        policy = read(product.quote_policy_ref, QuoteProductPolicyView)
        if policy.product_ref != product.ref or policy.lender_id != lender:
            raise ValueError('Quote product policy changes its original product or lender')
        current(policy.effective_window, 'current_quote_product_policy')
        unique_identities(action_input.pricing_candidates)
        unique_identities(action_input.funding_path_refs)
        if set(action_input.pricing_candidates) != set(policy.pricing_refs):
            _needs('complete_product_pricing_candidates', policy.pricing_refs)
        if not policy.pricing_refs:
            return completed('decline', 'The sourced product policy supplies no quotation candidates')
        if authorized_max <= 0 or assessment.review_payload.choice == 'decline':
            return completed('decline', 'The received review or independent amount authority rules out a quotation')

        choices, unknowns = [], []
        for ref in policy.pricing_refs:
            try:
                price = read(ref, QuotePricingView)
                terms_source(price, check_current=False)
                if price.status == 'withdrawn' or ref not in authority.allowed_pricing_refs:
                    continue
                if price.effective_window.start.clock_ref != now.clock_ref:
                    _unsupported('bank-quote-clock-alignment')
                if not price.effective_window.contains(now):
                    continue
                priority = _known(price.priority, 'declared_quote_priority')
                if price.currency != application.requested.currency:
                    _unsupported('bank-quote-currency-conversion')
                tenor = read(price.tenor_ref, TimeWindow)
                validity = read(price.validity_ref, TimeWindow)
                if validity.start.clock_ref != now.clock_ref:
                    _unsupported('bank-quote-clock-alignment')
                if not validity.contains(now):
                    continue
                if tenor.start.clock_ref != now.clock_ref or tenor.end.clock_ref != now.clock_ref:
                    _unsupported('bank-quote-clock-alignment')
                if tenor.start.offset < now.offset or tenor.start.offset >= tenor.end.offset:
                    _needs('future_positive_quote_tenor')
                reservation = read(price.reservation_policy_ref, QuoteReservationView)
                terms_source(reservation)
                if (reservation.ref not in authority.allowed_reservation_refs
                        or reservation.expiry_ref != price.validity_ref):
                    raise ValueError('Quote reservation is outside authorized rules or its exact expiry')
                if reservation.acceptance_action_id != application.originating_action_id:
                    raise ValueError('Quote acceptance route differs from the actual borrower role')
                for rule_ref in (reservation.release_rule_ref, reservation.conversion_rule_ref):
                    if rule_ref is not None:
                        rule = read(rule_ref, CreditRuleView)
                        if rule.lender_id != lender or rule.product_ref != product.ref:
                            raise ValueError('Reservation lifecycle rule changes lender or product')
                        current(rule.effective_window, 'current_reservation_lifecycle_rule')
                if price.funding_path_ref not in action_input.funding_path_refs:
                    _needs('complete_quote_funding_paths', [price.funding_path_ref])
                path = read(price.funding_path_ref, QuoteFundingPathView)
                terms_source(path)
                if path.kind != 'borrower_account':
                    _unsupported('bank-quote-direct-payment-cash-calendar')
                destination = read(path.destination_ref, CreditAccountView)
                funding = read(path.funding_account_ref, CreditAccountView)
                if (path.beneficiary_id != application.borrower_id or destination.borrower_id != application.borrower_id
                        or funding.borrower_id != lender or path.currency != application.requested.currency
                        or destination.currency != path.currency or funding.currency != path.currency):
                    raise ValueError('Quote funding path changes actual account owner, beneficiary or currency')
                purpose = reading.resolve(application.purpose_ref)
                region = _known(purpose.project_region_id, 'quote_project_region')
                if region not in _known(path.permitted_region_ids, 'quote_path_regions'):
                    _unsupported('bank-quote-inter-region-funding-path')
                if region not in _known(funding.permitted_project_region_ids, 'quote_funding_account_regions'):
                    _unsupported('bank-quote-inter-region-funding-account')

                start_methods = len(reading.method_evidence())
                review = review_credit(context, assessment.review_input, reading,
                    capacity_ref=action_input.capacity_snapshot_ref, extra_condition_refs=price.condition_refs)
                if review['kind'] != 'completed':
                    raise ObservationGap(review)
                method_rows = reading.method_evidence()[start_methods:]
                cash_rows = [row for row in method_rows if row['method_ref'] == CREDIT_CASH_METHOD.model_dump()]
                if not cash_rows:
                    # Hard risk or exhausted current capacity has a real negative
                    # exit before a full cash input exists. Do not invent one.
                    continue
                if cash_rows[-1]['result']['kind'] != 'ok':
                    raise ObservationGap(cash_rows[-1]['result'])
                cash = CreditCashInput.model_validate(cash_rows[-1]['input'])
                original_dependencies = {row.ref.key() for row in assessment.source_dependencies}
                core_kinds = {'FinanceApplication', 'FinanceProductProfile', 'FundingPurpose', 'Organization',
                    'OwnerCase', 'Project', 'WorkScope', 'RiskMethod', 'RiskDimension', 'RiskObservation',
                    'FinancialForecast', 'BorrowerPortfolio', 'Account', 'Debt', 'DebtComponent', 'Obligation',
                    'FinanceFeasibilityMethod', 'Assumption'}
                missing_sources = [ref for ref in cash.source_refs if ref.kind in core_kinds
                                   and ref.key() not in original_dependencies]
                if missing_sources:
                    _needs('complete_indirect_credit_assessment_dependencies', missing_sources)
                if path.destination_ref != cash.loan_account_ref:
                    raise ValueError('Quote path is not the account assessed for hypothetical financing')
                if (not cash.horizon.contains(tenor.start) or not cash.horizon.contains(tenor.end)):
                    _needs('quote_calendar_within_disclosed_forecast')
                repayment = read(price.repayment_rule_ref, QuoteRepaymentView)
                terms_source(repayment)
                assumption = read(price.assumption_ref, CreditAssumptionView)
                current(assumption.effective_window, 'current_quote_schedule_basis')
                if assumption.method_ref != reading.resolve(assessment.review_input.risk_method_ref).feasibility_method_ref:
                    raise ValueError('Quote terms assumption changes the declared feasibility method')
                payments = _known(repayment.payments, 'complete_quote_repayment_schedule')
                if sum((decimal_fraction(p.principal_factor) for p in payments), Fraction()) != 1:
                    raise ValueError('Quote repayment schedule must repay exactly one principal')
                loan = [CreditLoanFactor(local_key='quote:draw', time=tenor.start, kind='draw',
                                        factor='1', assumption_ref=assumption.ref)]

                def factor(key, point, kind, value):
                    at(point, tenor, 'complete_quote_payment_calendar')
                    if decimal_fraction(value):
                        loan.append(CreditLoanFactor(local_key=key, time=point, kind=kind, factor=value,
                                                     assumption_ref=assumption.ref))

                for payment in payments:
                    factor('quote:principal:'+payment.local_key, payment.time, 'principal', payment.principal_factor)
                for payment in _known(price.interest_payments, 'complete_quote_interest_schedule'):
                    factor('quote:interest:'+payment.local_key, payment.time, 'cost', payment.principal_factor)
                movements = list(cash.movements)
                for fee_ref in price.fee_rule_refs:
                    fee = read(fee_ref, QuoteFeeView)
                    terms_source(fee)
                    factor('quote:fee:'+fee.ref.id, fee.time, 'cost',
                           _known(fee.principal_factor, 'complete_quote_fee_factor'))
                    fixed = _known(fee.fixed_amount, 'complete_quote_fixed_fee')
                    if amount(fixed):
                        movements.append(CreditCashMovement(local_key='quote:fixed-fee:'+fee.ref.id,
                            account_ref=cash.loan_account_ref, time=fee.time, direction='outflow',
                            amount={'lower': fixed, 'upper': fixed}))
                max_amount = min(amount(cash.maximum), authorized_max)
                if max_amount < amount(cash.minimum) or max_amount <= 0:
                    continue
                current_reads = reading.evidence()
                source_refs = {ref.key(): ref for ref in cash.source_refs}
                for row in current_reads:
                    ref = row['ref']
                    if ref['kind'] not in {'Evidence', 'LendingCapacity', 'FinancePortfolio', 'FinanceCommitment'}:
                        source_refs[(ref['kind'], ref['id'], ref['version'])] = ref
                calculation = CreditCashInput.model_validate({**cash.model_dump(mode='python'),
                    'maximum': money(max_amount, authority.maximum_principal.value.basis_ref),
                    'loan_schedule': loan, 'movements': movements,
                    'source_refs': list(source_refs.values()),
                    'basis_refs': list({ref.key(): ref for ref in [*cash.basis_refs, *basis.values()]}.values())})
                report = reading.calculate(CREDIT_CASH_METHOD, calculation)
                if report.kind == 'invalid_input':
                    raise ValueError('Invalid sourced quote cash calendar')
                if report.kind != 'ok':
                    raise ObservationGap(report.model_dump(mode='python'))
                if not report.value.feasible:
                    continue
                conditions = review['payload']['conditions']
                if any(row['conclusion'] != 'acceptable' for row in review['payload']['findings']):
                    risk = reading.resolve(assessment.review_input.risk_method_ref)
                    by_dimension = {reading.resolve(ref).ref.key(): reading.resolve(ref) for ref in risk.dimension_refs}
                    for finding in review['payload']['findings']:
                        if finding['conclusion'] != 'acceptable':
                            remedy = by_dimension[finding['dimension_ref'].key()].remedial_condition_ref
                            if remedy is None or not any(row['requirement_ref'] == remedy
                                    and row['outcome'] != 'satisfied' for row in conditions):
                                _needs('explicit_quote_conditions_for_unresolved_risk')
                conditional = (any(row['outcome'] != 'satisfied' for row in conditions)
                    or any(row['conclusion'] != 'acceptable' for row in review['payload']['findings']))
                terms = {'borrower_id': application.borrower_id, 'product_ref': product.ref,
                    'principal_limit': report.value.rounded_upper, 'purpose_ref': application.purpose_ref,
                    'tenor_ref': price.tenor_ref, 'pricing_ref': price.ref, 'fee_rule_refs': price.fee_rule_refs,
                    'repayment_rule_ref': repayment.ref, 'validity_ref': price.validity_ref,
                    'condition_refs': [row['requirement_ref'] for row in conditions]}
                choices.append((priority, 'conditional_offer' if conditional else 'offer', terms, reservation.ref))
            except ObservationGap as gap:
                unknowns.append(gap.result)
        # Missing or unsupported candidates cannot silently disappear from the
        # policy's complete ranking, even if another candidate looks feasible.
        if unknowns:
            raise ObservationGap(unknowns[0])
        if not choices:
            return completed('decline', 'No authorized candidate satisfies current risk, capacity and actual-term cash constraints')
        best = min(row[0] for row in choices)
        selected = [row for row in choices if row[0] == best]
        if len(selected) != 1:
            _needs('unambiguous_quote_selection_priority')
        _, choice, terms, reservation_ref = selected[0]
        return completed(choice, 'Versioned quotation decision only; capacity and reservation require formal submission',
                         terms=terms, reservation_policy_ref=reservation_ref)
    except ObservationGap as gap:
        return gap.result
