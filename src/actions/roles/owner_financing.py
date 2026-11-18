"""OWN-A05 plans lawful funding and forms only the owner's local decision."""
from fractions import Fraction

from src.actions.contracts.bank_objects import (
    BorrowerOrganizationView, FinanceApplicationView, FinanceProductProfileView, FundingPurposeView,
)
from src.actions.contracts.common import EvidenceRecord, Money, TimeWindow
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_financing_objects import (
    FinancingAcceptanceView, FinancingAccountView, FinancingApprovalView, FinancingCaseView,
    FinancingArrangementView, FinancingConditionView, FinancingDebtView,
    FinancingFeeView, FinancingIssueView, FinancingObligationView, FinancingOfferView,
    FinancingPricingView, FinancingProfileView, FinancingProjectView, FinancingRepaymentView,
    FinancingRestrictionView, FinancingRevisionView, FinancingSourceView,
    FinancingSubjectView, FinancingWorkView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.owner_financing import FinancingCandidate, FinancingSelectionInput
from src.methods.owner_investment import CashAccount, CashCalendarInput, CashFlow
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def plan_financing(context, action_input, reading):
    now, owner, borrower = context.business_time, reading.organization_id, action_input.borrower_id
    monthly_cash_reports=[]

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('owner-financing-clock')

    def available(point, field):
        clock(point)
        if point.offset > now.offset:
            _needs(field)

    def active(window, point=None):
        clock(window.start)
        return window.contains(point or now)

    def current(window, field):
        if not active(window):
            _needs(field)

    def evidence(refs, point=None):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('owner-financing-evidence-schema')
            if row.effective_window is not None and not active(row.effective_window, point):
                _needs('applicable_financing_evidence', [ref])

    def read(ref, schema, point=None, *, at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'owner-financing-projection:{ref.kind}')
        if at_field is not None:
            point = getattr(row, at_field)
            available(point, 'available_original_financing_source')
        evidence(getattr(row, 'evidence_refs', []), point)
        return row

    def amount(value):
        evidence([value.basis_ref])
        if value.currency != profile.currency:
            _unsupported('owner-financing-currency-conversion')
        return decimal_fraction(value.value)

    def money(value, basis):
        return Money(value=exact_decimal(value), currency=profile.currency, basis_ref=basis)

    def authority(ref, organization, actor, function_ref, role, action, scope, point=None, *, required_reads=()):
        grant = read(ref, Authorization, point)
        assignment = read(function_ref, RoleAssignment, point)
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], point)
            else:
                reading.resolve(basis_ref)
        expected_role = {'OWN': 'Owner', 'BANK': 'Bank', 'GOV': 'Government', 'ARCHITECT': 'Architect',
            'ENGINEER': 'Engineer', 'QS': 'QS', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier'}.get(action.split('-', 1)[0])
        if (grant.organization_id != organization or grant.actor_id != actor
                or grant.function_ref != function_ref or assignment.function_ref != function_ref
                or assignment.role != role or role != expected_role):
            raise ValueError('Financing authority changes legal organization, actor or assigned function')
        return (active(grant.validity, point) and action in grant.action_ids
                and any(scope_covers(value, scope) for value in grant.scopes)
                and {ref.key() for ref in required_reads} <= {ref.key() for ref in grant.readable_refs})

    def borrower_authority(ref):
        grant = read(ref, Authorization)
        if not authority(ref, borrower, context.actor_id, grant.function_ref, 'Owner', 'OWN-A05', action_input.scope_ref):
            _needs('current_borrower_financing_authority', [ref])

    def method(ref, data):
        result = reading.calculate(ref, data)
        if result.kind == 'ok':
            if profile.monthly_capacity_observation_ref is not None and ref==profile.cash_method_ref:
                monthly_cash_reports.append((data,result.value))
            return result.value
        if result.kind == 'invalid_input':
            raise ValueError('Invalid sourced financing method input')
        raw = result.model_dump(mode='python')
        if result.kind == 'needs_information':
            raw['requested_refs'] = []
        raise ObservationGap(raw)

    def completed(choice, note, **fields):
        if profile.monthly_capacity_observation_ref is not None:
            from src.actions.roles.owner_monthly_capacity import review_monthly_capacity
            if len(monthly_cash_reports)!=1:raise ValueError('Monthly review requires one actual original cash-calendar calculation')
            data,report=monthly_cash_reports[0]
            note=review_monthly_capacity(context,reading,profile=profile,choice=choice,cash_input=data,cash_report=report).model_dump_json()
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'note': note, **fields}}

    def deferred():
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': 'owner_financing_dependencies_pending', 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': [profile.ref], 'earliest_time': None,
            'condition_code': 'owner.financing.inputs_changed'}}

    def conditions(refs, offer=None, arrangement=None, scope=None, at=None):
        unique_refs(refs)
        for ref in refs:
            row = read(ref, FinancingConditionView, at_field='verified_at')
            if (row.borrower_id != borrower or row.lender_id != (offer.lender_id if offer else arrangement.lender_id)
                    or row.offer_ref != (offer.ref if offer else None)
                    or row.arrangement_ref != (arrangement.ref if arrangement else None)
                    or not scope_covers(row.scope_ref, scope or action_input.scope_ref)):
                raise ValueError('Financing condition changes its exact offer/arrangement, parties or scope')
            available(row.verified_at, 'available_financing_condition')
            if not active(row.effective_window, at):
                _needs('current_financing_condition')
            verifier = read(row.verifier_authority_ref, Authorization)
            role = read(row.verifier_function_ref, RoleAssignment).role
            permitted = {'Owner': {'OWN-A05'}, 'Bank': {'BANK-A05', 'BANK-A06'}}
            if row.verifier_action_id not in permitted.get(role, set()):
                _unsupported('owner-financing-condition-verifier-function')
            if not authority(row.verifier_authority_ref, verifier.organization_id, row.verifier_actor_id,
                    row.verifier_function_ref, role, row.verifier_action_id, row.scope_ref, row.verified_at,
                    required_reads=row.evidence_refs):
                _needs('valid_financing_condition_verifier')
            if verifier.organization_id != (borrower if role == 'Owner' else row.lender_id):
                raise ValueError('Financing condition verifier belongs to another legal party')
            if not _known(row.permitted, 'verified_financing_condition'):
                return False
        return True

    def validate_arrangement(ref):
        row = read(ref, FinancingArrangementView)
        if row.borrower_id != borrower:
            raise ValueError('Financing arrangement changes its original borrower')
        available(row.available_at, 'available_financing_arrangement')
        offer = read(row.offer_ref, FinancingOfferView, at_field='issued_at')
        if (offer.terms.borrower_id != row.borrower_id or offer.lender_id != row.lender_id
                or offer.scope_ref != row.scope_ref):
            raise ValueError('Financing arrangement changes the exact accepted offer parties or scope')
        for ref, organization, role, action in (
            (row.borrower_acceptance_ref, row.borrower_id, 'Owner', 'OWN-A05'),
            (row.lender_confirmation_ref, row.lender_id, 'Bank', 'BANK-A05'),
        ):
            acceptance = read(ref, FinancingAcceptanceView, at_field='accepted_at')
            available(acceptance.accepted_at, 'available_independent_financing_acceptance')
            if (acceptance.offer_ref != row.offer_ref or acceptance.scope_ref != row.scope_ref
                    or acceptance.organization_id != organization or acceptance.action_id != action):
                raise ValueError('Financing acceptance changes the exact offer, scope, party or action')
            if acceptance.decision != 'accept':
                _needs('independently_accepted_financing_arrangement')
            if not authority(acceptance.authority_ref, organization, acceptance.actor_id, acceptance.function_ref,
                    role, action, row.scope_ref, acceptance.accepted_at):
                _needs('valid_independent_financing_acceptance_authority')
        return row, offer

    def cash_input(lines, scope):
        """Keep a complete borrower portfolio; a source is never a copied balance."""
        if profile.as_of != now or profile.coverage != 'complete':
            _needs('current_complete_financing_portfolio')
        if not profile.source_refs:
            _needs('declared_actual_funding_sources')
        sources, accounts, inflows, existing, proposed = {}, [], [], [], []
        provenance = [profile.ref]
        account_refs, all_debts, all_obligations = [], [], []
        release_refs, approval_refs, component_refs = [], [], []
        arrangements = {}
        release_totals = {}
        for ref in profile.arrangement_refs:
            arrangements[ref.key()] = validate_arrangement(ref)
            provenance.append(ref)
        for ref in profile.source_refs:
            source = read(ref, FinancingSourceView)
            account = read(source.account_ref, FinancingAccountView)
            if (source.organization_id != borrower or account.organization_id != borrower
                    or account.source_ref != source.ref):
                raise ValueError('Financing source/account belongs to another borrower or source version')
            if source.as_of != now or account.as_of != now or source.coverage != 'complete' or account.coverage != 'complete':
                _needs('current_complete_financing_account')
            if account.currency != profile.currency:
                _unsupported('owner-financing-currency-conversion')
            project_region = _known(purpose.project_region_id, 'funding_project_region')
            if (account.region_id != project_region and (account.permitted_project_region_ids.state != 'known'
                    or project_region not in account.permitted_project_region_ids.value)):
                _unsupported('owner-financing-inter-region-funding-path')
            if source.actual_cash != account.actual_cash or source.restricted_cash != account.restricted_cash:
                raise ValueError('Funding source changes the actual same-version account balance')
            total = _known(account.actual_cash, 'actual_financing_cash')
            restricted = _known(account.restricted_cash, 'actual_restricted_cash')
            free = amount(total) - amount(restricted)
            if free < 0:
                raise ValueError('Restricted cash exceeds actual account cash')
            account_refs.append(account.ref)
            all_debts.extend(account.debt_refs)
            all_obligations.extend(account.obligation_refs)
            sources[source.ref.key()] = source
            accounts.append(CashAccount(source_ref=source.ref, opening_available=money(free, total.basis_ref)))
            provenance.extend([source.ref, account.ref])
            for release in source.releases:
                release_refs.append(release.ref)
                available(release.available_at, 'available_approved_funding_release')
                clock(release.time)
                if release.state != 'committed':
                    continue
                if release.time.offset <= now.offset:
                    _needs('reconcile_due_funding_release', [source.ref])
                value = _known(release.amount, 'approved_funding_release_amount')
                amount(value)
                if release.approval_ref.kind == 'Authorization':
                    _unsupported('owner-financing-permission-is-not-funding-approval')
                if release.approval_ref.kind == 'FinanceArrangement':
                    if release.approval_ref.key() not in arrangements:
                        raise ValueError('Committed release omits its original arrangement from the portfolio')
                    arrangement, offer = arrangements[release.approval_ref.key()]
                    if (arrangement.source_ref != source.ref or not scope_covers(arrangement.scope_ref, scope)
                            or offer.terms.purpose_ref != profile.purpose_ref):
                        raise ValueError('Committed release changes funding source, scope or purpose')
                    if arrangement.status != 'active' or not active(arrangement.effective_window, release.time):
                        _needs('active_financing_arrangement_for_release')
                    required = {*arrangement.condition_refs, *release.condition_refs}
                    if not conditions(list(required), arrangement=arrangement, scope=scope, at=release.time):
                        return None
                    used = release_totals.get(arrangement.ref.key(), Fraction()) + amount(value)
                    if used > amount(_known(arrangement.undrawn_amount, 'actual_undrawn_financing')):
                        raise ValueError('Funding releases overdraw the same original arrangement')
                    release_totals[arrangement.ref.key()] = used
                else:
                    approval = read(release.approval_ref, FinancingApprovalView)
                    approval_refs.append(approval.ref)
                    available(approval.available_at, 'available_nonbank_funding_approval')
                    if (approval.source_ref != source.ref or approval.organization_id != borrower
                            or approval.purpose_ref != profile.purpose_ref or not scope_covers(approval.scope_ref, scope)
                            or approval.release_time != release.time or amount(approval.amount) != amount(value)):
                        raise ValueError('Approved nonbank release changes exact source, party, purpose, time or amount')
                    if release.condition_refs:
                        _unsupported('owner-financing-nonbank-release-condition-method')
                    if not active(approval.effective_window, release.time) or not _known(approval.approved, 'approved_nonbank_funding'):
                        return None
                    provenance.append(approval.ref)
                inflows.append(CashFlow(local_key=f'release:{release.ref.id}', source_ref=source.ref,
                                        time=release.time, amount=value))
        for refs in (account_refs, all_debts, all_obligations, release_refs, approval_refs):
            unique_refs(refs)
        if set(all_debts) != set(profile.debt_refs) or set(all_obligations) != set(profile.obligation_refs):
            raise ValueError('Funding profile omits or duplicates the complete account debt/obligation set')
        debt_obligations = []
        debt_rows = {}
        for ref in profile.debt_refs:
            debt = read(ref, FinancingDebtView)
            if debt.borrower_id != borrower:
                raise ValueError('Existing debt changes its original legal borrower')
            if debt.as_of != now or debt.coverage != 'complete':
                _needs('current_complete_existing_debt')
            amount(_known(debt.outstanding_principal, 'actual_existing_debt_principal'))
            if debt.arrangement_ref.key() not in arrangements:
                raise ValueError('Existing debt omits its original financing arrangement')
            arrangement, _ = arrangements[debt.arrangement_ref.key()]
            if debt.lender_id != arrangement.lender_id or debt.origin_scope != arrangement.scope_ref:
                raise ValueError('Existing debt changes its original lender or project')
            debt_obligations.extend(debt.obligation_refs)
            debt_rows[ref.key()] = debt
            provenance.append(ref)
        unique_refs(debt_obligations)
        if not set(debt_obligations) <= set(profile.obligation_refs):
            raise ValueError('Existing debt obligations are omitted from the funding plan')
        for ref in profile.obligation_refs:
            row = read(ref, FinancingObligationView)
            if row.debtor_id != borrower or row.source_ref.key() not in sources:
                raise ValueError('Existing obligation changes its debtor or actual funding source')
            if row.as_of != now:
                _needs('current_existing_funding_obligation')
            source_account = read(sources[row.source_ref.key()].account_ref, FinancingAccountView)
            if ref not in source_account.obligation_refs:
                raise ValueError('Existing obligation changes its actual account')
            component_refs.extend(row.component_refs)
            if row.debt_ref is not None:
                debt = debt_rows.get(row.debt_ref.key())
                if (debt is None or row.ref not in debt.obligation_refs or row.origin_scope != debt.origin_scope
                        or row.payee_id != debt.lender_id):
                    raise ValueError('Debt obligation changes original debt, lender or project')
            elif ref in debt_obligations:
                raise ValueError('A debt obligation cannot discard its original debt identity')
            due, paid = _known(row.actual_due, 'actual_due_funding_obligation'), _known(row.actual_paid, 'actual_paid_funding_obligation')
            unpaid = amount(due) - amount(paid)
            if unpaid < 0:
                raise ValueError('An existing obligation cannot be overpaid')
            clock(row.due_at)
            when = row.due_at if row.due_at.offset >= now.offset else now
            existing.append(CashFlow(local_key=f'obligation:{row.ref.id}', source_ref=row.source_ref,
                                    time=when, amount=money(unpaid, due.basis_ref)))
            provenance.append(ref)
        unique_refs(component_refs)
        periods = set()
        for index, line in enumerate(lines):
            if line.source_ref.key() not in sources:
                raise ValueError('Funding line changes the portfolio source version')
            source = sources[line.source_ref.key()]
            window = read(line.window_ref, TimeWindow)
            clock(window.start)
            if window.bounds != 'closed_open':
                _unsupported('owner-financing-cash-window-bounds')
            if window.start.offset < now.offset or window.start.offset >= window.end.offset:
                _needs('future_bounded_funding_plan')
            identity = (line.source_ref.key(), line.window_ref.key())
            if identity in periods:
                raise ValueError('Funding line duplicates a source period')
            periods.add(identity)
            unique_refs(line.restriction_refs)
            if not set(source.restriction_refs) <= set(line.restriction_refs):
                raise ValueError('Funding line drops an actual source restriction')
            for ref in line.restriction_refs:
                restriction = read(ref, FinancingRestrictionView)
                if (restriction.source_ref != line.source_ref or restriction.organization_id != borrower
                        or restriction.purpose_ref != profile.purpose_ref or not scope_covers(restriction.scope_ref, scope)):
                    raise ValueError('Funding restriction changes source, borrower, purpose or authorized scope')
                if (not active(restriction.effective_window, window.start)
                        or restriction.effective_window.end.offset < window.end.offset
                        or not _known(restriction.permitted, 'permitted_funding_source_use')):
                    return None
                provenance.append(ref)
            use = _known(line.planned_use, 'declared_planned_funding_use')
            if line.available.state == 'known':
                amount(line.available.value)  # A forecast is checked, never credited as actual cash.
            amount(use)
            proposed.append(CashFlow(local_key=f'planned:{index}', source_ref=line.source_ref, time=window.start, amount=use))
            provenance.append(line.window_ref)
        unique_provenance = list({ref.key(): ref for ref in provenance}.values())
        return CashCalendarInput(clock_ref=now.clock_ref, as_of=now, accounts=accounts, inflows=inflows,
            existing_outflows=existing, proposed_outflows=proposed, source_refs=unique_provenance)

    def cash_feasible(data):
        return data is not None and method(profile.cash_method_ref, data).feasible

    def product_eligible(product, requested):
        if not active(product.effective_window):
            return False
        checks = [(borrower_row.registration_region_id, product.allowed_registration_region_ids, 'registration_region'),
                  (purpose.project_region_id, product.allowed_project_region_ids, 'project_region'),
                  (purpose.purpose_code, product.allowed_purpose_codes, 'funding_purpose'),
                  (purpose.stage, product.allowed_stages, 'application_stage')]
        for actual, allowed, field in checks:
            if _known(actual, field) not in _known(allowed, f'finance_product:{field}'):
                return False
        regions = _known(borrower_row.operating_region_ids, 'borrower_operating_regions')
        if not regions:
            _needs('borrower_operating_regions')
        if not set(regions) <= set(_known(product.allowed_operating_region_ids, 'finance_product:operating_regions')):
            return False
        if requested.currency not in _known(product.allowed_currencies, 'finance_product:currencies'):
            return False
        return (amount(_known(product.minimum_request, 'finance_product:minimum')) <= amount(requested)
                <= amount(_known(product.maximum_request, 'finance_product:maximum')))

    def apply():
        draft = profile.application
        if draft is None:
            _needs('declared_financing_application_draft')
        if (draft.borrower_id != borrower or draft.scope_ref != action_input.scope_ref
                or draft.purpose_ref != profile.purpose_ref or draft.applicant_authority_ref != profile.borrower_authority_ref):
            raise ValueError('Application draft changes borrower, purpose, scope or borrower authority')
        borrower_authority(draft.applicant_authority_ref)
        amount(draft.requested)
        evidence(draft.disclosure_refs)
        for ref in draft.product_candidates:
            product = read(ref, FinanceProductProfileView)
            if product.lender_id != draft.lender_id:
                raise ValueError('Application changes the selected product lender')
            if not product_eligible(product, draft.requested):
                _needs('eligible_financing_application_product', [ref])
        return completed('apply', 'Submit only the borrower-authorized draft; registration and Bank A02 intake remain independent',
                         application=draft.model_dump(mode='python'))

    def resize():
        if profile.revision_ref is None:
            _needs('declared_financing_revision')
        revision = read(profile.revision_ref, FinancingRevisionView)
        if (revision.organization_id != owner or revision.borrower_id != borrower or revision.prior_profile_ref != profile.ref
                or not scope_covers(action_input.scope_ref, revision.change_scope.scope_ref)
                or not revision.change_scope.scope_ref.coverage_refs):
            raise ValueError('Funding revision changes owner, borrower, prior version or bounded scope')
        available(revision.available_at, 'available_funding_revision')
        current(revision.effective_window, 'current_funding_revision')
        evidence(revision.change_scope.basis_refs)
        if revision.change_scope.condition_refs:
            _unsupported('owner-financing-resize-condition-method')
        if not authority(revision.authority_ref, owner, context.actor_id, context.function_ref,
                'Owner', 'OWN-A05', revision.change_scope.scope_ref):
            _needs('current_funding_revision_authority')
        original = sum((amount(_known(row.planned_use, 'original_funding_plan')) for row in action_input.funding_lines), Fraction())
        revised = sum((amount(_known(row.planned_use, 'revised_funding_plan')) for row in revision.revised_lines), Fraction())
        if revised > original:
            raise ValueError('A financing resize cannot silently increase planned spending')
        if not cash_feasible(cash_input(revision.revised_lines, revision.change_scope.scope_ref)):
            _needs('feasible_revised_funding_plan')
        return completed('resize', 'Propose only the bounded reduced/deferred plan; existing debts and unpaid obligations remain',
                         revised_lines=[row.model_dump(mode='python') for row in revision.revised_lines],
                         change_scope=revision.change_scope.model_dump(mode='python'))

    def unavailable(reason):
        fallback = _known(profile.on_unavailable, 'declared_financing_unavailable_policy')
        if fallback == 'apply':
            return apply()
        if fallback == 'resize':
            return resize()
        if fallback == 'defer':
            return deferred()
        return completed('no_finance', reason + '; no new financing is accepted and existing obligations remain')

    try:
        profile = read(action_input.funding_profile_ref, FinancingProfileView)
        if (profile.organization_id != owner or profile.borrower_id != borrower or profile.scope_ref != action_input.scope_ref
                or not scope_covers(context.scope, profile.scope_ref)):
            raise ValueError('Funding profile changes owner, borrower or current scope')
        current(profile.effective_window, 'current_financing_profile')
        if profile.as_of != now:
            _needs('current_financing_profile')
        scope = action_input.scope_ref
        if scope.kind == 'assessment_case':
            case = read(scope.ref, FinancingCaseView)
            if case.organization_id != owner:
                raise ValueError('Financing case belongs to another owner')
            available(case.available_at, 'available_financing_case')
            if case.status != 'active':
                _needs('active_financing_case')
        elif scope.kind == 'project':
            project = read(scope.ref, FinancingProjectView)
            if project.owner_organization_id != owner:
                raise ValueError('Financing project belongs to another owner')
            available(project.available_at, 'available_financing_project')
            if project.status == 'closed':
                _needs('active_financing_project')
        elif scope.ref.id != owner:
            raise ValueError('Financing organization scope changes the owner')
        unique_refs(scope.coverage_refs)
        for ref in scope.coverage_refs:
            work = read(ref, FinancingWorkView)
            if (work.organization_id != owner or work.purpose_ref != profile.purpose_ref
                    or not scope_covers(scope, work.scope_ref) or work.ref not in work.scope_ref.coverage_refs):
                raise ValueError('Financing work changes owner, purpose or bounded scope')
            available(work.available_at, 'available_financing_work')
            current(work.effective_window, 'current_financing_work')
        if not authority(profile.authority_ref, owner, context.actor_id, context.function_ref,
                'Owner', 'OWN-A05', action_input.scope_ref):
            _needs('current_owner_funding_plan_authority')
        unique_refs(action_input.debt_refs)
        unique_refs(action_input.offers)
        if set(action_input.debt_refs) != set(profile.debt_refs):
            raise ValueError('Funding input omits or changes the original debt portfolio')
        if ([row.model_dump(mode='python') for row in action_input.funding_lines]
                != [row.model_dump(mode='python') for row in profile.funding_lines]):
            raise ValueError('Funding input changes the declared same-version plan')
        policy = _known(profile.policy, 'declared_financing_policy')
        if policy == 'no_finance':
            return completed('no_finance', 'The owner declines new financing; all prior debts and obligations remain unchanged')
        if policy == 'defer':
            return deferred()
        borrower_row = read(profile.borrower_ref, BorrowerOrganizationView)
        purpose = read(profile.purpose_ref, FundingPurposeView)
        if purpose.borrower_ref != profile.borrower_ref or purpose.scope_ref != action_input.scope_ref:
            raise ValueError('Funding purpose changes its original borrower or scope')
        for row in (borrower_row, purpose):
            current(row.effective_window, 'current_financing_borrower_purpose')
        if not _known(borrower_row.legal_standing, 'borrower_legal_standing'):
            return completed('no_finance', 'The legal-standing evidence rules out new borrowing by this borrower')
        if policy == 'apply':
            return apply()
        if policy == 'resize':
            return resize()
        borrower_authority(profile.borrower_authority_ref)
        if policy != 'negotiate':
            base = cash_input(action_input.funding_lines, action_input.scope_ref)
            if policy in {'own_funds', 'evaluate'} and cash_feasible(base):
                if not action_input.funding_lines:
                    _needs('nonempty_funding_plan')
                return completed('own_funds', 'Use the checked actual cash and approved timing; no receipt, transfer or reservation is created',
                                 source_refs=list({row.source_ref.key(): row.source_ref for row in action_input.funding_lines}.values()))
            if policy == 'own_funds':
                return unavailable('Actual unrestricted cash and approved timing do not cover this plan')
            if base is None:
                return unavailable('The declared funding source restrictions exclude the planned use')
        candidates = read(context.candidate_set_ref, CandidateSet)
        candidates.check_context(context, tuple(['own_funds', 'apply', 'accept_offer', 'negotiate', 'resize', 'no_finance']))
        pinned = profile.selected_offer_ref
        if pinned is not None and pinned not in action_input.offers:
            raise ValueError('Funding policy selects an offer outside the received version set')
        offers = [pinned] if pinned is not None else action_input.offers
        if policy == 'negotiate' and pinned is None:
            _needs('explicit_financing_negotiation_offer')
        eligible, provenance = [], [profile.ref]
        for ref in offers:
            offer = read(ref, FinancingOfferView, at_field='issued_at')
            if (offer.scope_ref != action_input.scope_ref or offer.terms.borrower_id != borrower
                    or offer.terms.purpose_ref != profile.purpose_ref):
                raise ValueError('Financing offer changes borrower, scope or funding purpose')
            available(offer.available_at, 'available_financing_offer')
            available(offer.issued_at, 'issued_financing_offer')
            validity = read(offer.terms.validity_ref, TimeWindow)
            if offer.status != 'offered' or not active(offer.effective_window) or not active(validity):
                continue
            if not authority(offer.authority_ref, offer.lender_id, offer.author_actor_id, offer.author_function_ref,
                    'Bank', 'BANK-A04', offer.scope_ref, offer.issued_at):
                continue
            product = read(offer.terms.product_ref, FinanceProductProfileView)
            application = read(offer.application_ref, FinanceApplicationView)
            if (product.lender_id != offer.lender_id or application.lender_id != offer.lender_id
                    or application.borrower_id != borrower or application.scope_ref != offer.scope_ref
                    or application.purpose_ref != offer.terms.purpose_ref
                    or offer.terms.product_ref not in application.product_candidates):
                raise ValueError('Financing offer mixes application/product/borrower/lender/purpose versions')
            available(application.submitted_at, 'available_original_financing_application')
            if application.status != 'submitted' or not product_eligible(product, offer.terms.principal_limit):
                continue
            originating_role = {'OWN-A05': 'Owner', 'CONTRACTOR-A10': 'Contractor', 'SUPPLIER-A10': 'Supplier'}[application.originating_action_id]
            if not authority(application.applicant_authority_ref, borrower, application.applicant_actor_id,
                    application.applicant_function_ref, originating_role, application.originating_action_id,
                    application.scope_ref, application.submitted_at):
                _needs('valid_original_financing_application_authority')
            if policy == 'negotiate':
                candidates.check_selected('negotiate', [ref])
                if not profile.question_refs:
                    _needs('specific_financing_negotiation_questions')
                questions = []
                for issue_ref in profile.question_refs:
                    issue = read(issue_ref, FinancingIssueView)
                    if issue.profile_ref != profile.ref or issue.offer_ref != offer.ref or issue.scope_ref != profile.scope_ref:
                        raise ValueError('Financing negotiation changes its exact issue, profile or offer version')
                    available(issue.available_at, 'available_financing_question')
                    current(issue.effective_window, 'current_financing_question')
                    if issue.status != 'unresolved':
                        _needs('unresolved_financing_question')
                    subject = read(issue.subject_ref, FinancingSubjectView)
                    if subject.offer_ref != offer.ref or subject.scope_ref != offer.scope_ref:
                        raise ValueError('Financing question changes the exact business object subject')
                    for requirement_ref in issue.requirement_refs:
                        requirement = read(requirement_ref, FinancingConditionView)
                        if requirement.offer_ref != offer.ref or requirement.arrangement_ref is not None:
                            raise ValueError('Financing question imports another offer requirement')
                    questions.append({'local_key': issue.local_key, 'subject_ref': subject.ref, 'issue_ref': issue.ref, 'request': issue.request,
                        'requirement_refs': issue.requirement_refs, 'evidence_refs': issue.evidence_refs})
                return completed('negotiate', 'Ask only the scoped questions on this exact offer; no acceptance or cash is created',
                                 offer_ref=offer.ref, questions=questions)
            required = list({value.key(): value for value in [*profile.required_condition_refs,
                *product.required_condition_refs, *offer.terms.condition_refs]}.values())
            if not conditions(required, offer=offer):
                continue
            tenor = read(offer.terms.tenor_ref, TimeWindow)
            clock(tenor.start)
            if tenor.bounds not in {'closed_open', 'closed_closed'} or tenor.start.offset < now.offset:
                _unsupported('owner-financing-full-draw-tenor')
            principal = []
            costs = []
            rule_refs = [(offer.terms.pricing_ref, FinancingPricingView),
                *[(value, FinancingFeeView) for value in offer.terms.fee_rule_refs],
                (offer.terms.repayment_rule_ref, FinancingRepaymentView)]
            for rule_ref, schema in rule_refs:
                rule = read(rule_ref, schema)
                if (rule.offer_ref != offer.ref or rule.borrower_id != borrower
                        or rule.lender_id != offer.lender_id or rule.scope_ref != offer.scope_ref):
                    raise ValueError('Financing pricing/fee/repayment rule mixes another exact offer or party')
                available(rule.available_at, 'available_financing_rule')
                current(rule.effective_window, 'current_financing_rule')
                if rule.coverage != 'complete':
                    _needs('complete_financing_rule_schedule')
                rows = _known(rule.schedule, 'explicit_fixed_financing_rule_schedule')
                (principal if schema is FinancingRepaymentView else costs).extend(rows)
                provenance.append(rule.ref)
            schedule = FinancingCandidate(offer_ref=offer.ref, priority=_known(offer.priority, 'declared_financing_priority'),
                principal=offer.terms.principal_limit, tenor=tenor, disbursements=offer.proposed_releases,
                repayments=principal, costs=costs)
            data = base.model_dump(mode='python')
            for name, payments in [('inflows', schedule.disbursements), ('existing_outflows', schedule.repayments + schedule.costs)]:
                for payment in payments:
                    amount(payment.amount)
                    data[name].append(CashFlow(local_key=f'offer:{payment.local_key}', source_ref=payment.source_ref,
                                              time=payment.time, amount=payment.amount))
            data['source_refs'] = list({value.key(): value for value in [*base.source_refs, offer.ref,
                offer.application_ref, product.ref, *[r for r, _ in rule_refs], offer.terms.tenor_ref,
                offer.terms.validity_ref]}.values())
            if cash_feasible(CashCalendarInput.model_validate(data)):
                eligible.append(schedule)
                provenance.extend([offer.ref, offer.application_ref, product.ref, offer.terms.tenor_ref, offer.terms.validity_ref])
        if policy == 'negotiate':
            return unavailable('The explicit negotiation offer is unavailable; no other lender is substituted')
        if not eligible:
            return unavailable('No current same-version finance offer covers the declared funding plan')
        cap = _known(profile.financing_cost_cap, 'declared_financing_cost_cap')
        amount(cap)
        report = method(profile.selection_method_ref, FinancingSelectionInput(cost_cap=cap, candidates=eligible,
            source_refs=list({value.key(): value for value in provenance}.values())))
        if report.ambiguous_refs:
            _needs('explicit_financing_offer_preference', report.ambiguous_refs)
        if report.selected_ref is None:
            return unavailable('No current same-version finance offer covers the plan within the declared cost cap')
        candidates.check_selected('accept_offer', [report.selected_ref])
        return completed('accept_offer', 'Accept only this exact conditional offer version; independent Bank A05 confirmation and formal execution remain required',
                         offer_ref=report.selected_ref)
    except ObservationGap as gap:
        return gap.result
