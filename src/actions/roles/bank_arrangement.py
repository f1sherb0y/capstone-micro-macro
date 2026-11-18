"""BANK-A05 independent acceptance checks; no formal arrangement writes."""
from src.actions.contracts.bank_arrangement_objects import (
    ArrangementAcceptanceView, ArrangementBorrowerDecisionView, ArrangementCommitmentView,
    ArrangementFormationView, ArrangementOfferView, ArrangementTimeRuleView, accepted_offer_digest,
)
from src.actions.contracts.bank_credit_objects import CreditBankPortfolioView, CreditLendingCapacityView, unique_identities
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.bank_quote_objects import QuoteConditionView, QuoteReservationView
from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def form_arrangement(context, action_input, reading):
    now, lender = context.business_time, reading.organization_id

    def current(window, field):
        if window.start.clock_ref != now.clock_ref:
            _unsupported('bank-arrangement-clock-alignment')
        if not window.contains(now):
            _needs(field)

    def available(point, field, exact=False):
        if point.clock_ref != now.clock_ref:
            _unsupported('bank-arrangement-clock-alignment')
        if point.offset > now.offset or (exact and point != now):
            _needs(field)

    def evidence(refs, point=None, *, check_window=True):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('bank-arrangement-evidence-schema')
            if row.effective_window is not None:
                if row.effective_window.start.clock_ref != now.clock_ref:
                    _unsupported('bank-arrangement-clock-alignment')
                if check_window and not row.effective_window.contains(point or now):
                    _needs('applicable_formation_evidence', [ref])

    def read(ref, schema, *, at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'bank-arrangement-projection:{ref.kind}')
        point = None
        if at_field is not None:
            point = getattr(row, at_field)
            available(point, 'available_original_formation_source')
        evidence(getattr(row, 'evidence_refs', []), point)
        return row

    def amount(value):
        evidence([value.basis_ref])
        if value.currency != offer.terms.principal_limit.currency:
            _unsupported('bank-arrangement-currency-conversion')
        return decimal_fraction(value.value)

    def authority(ref, actor, organization, function, action, point, required_reads=(), *, target_scope=None):
        grant = read(ref, Authorization)
        assignment = read(function, RoleAssignment)
        expected_role = {'OWN':'Owner','BANK':'Bank','CONTRACTOR':'Contractor','SUPPLIER':'Supplier',
                         'GOV':'Government','ENGINEER':'Engineer','ARCHITECT':'Architect','QS':'QS'}.get(action.split('-')[0])
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], point)
            else:
                reading.resolve(basis_ref)
        return (grant.actor_id == actor and grant.organization_id == organization and grant.function_ref == function
            and assignment.function_ref == function and assignment.role == expected_role and action in grant.action_ids
            and grant.validity.contains(point) and any(scope_covers(scope, target_scope or offer.scope_ref) for scope in grant.scopes)
            and {ref.key() for ref in required_reads} <= {ref.key() for ref in grant.readable_refs})

    def completed(choice, note, **fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,'note':note,**fields}}

    def requote(note):
        for ref in profile.requote_requirement_refs:
            condition = read(ref, QuoteConditionView)
            if (condition.application_ref != offer.application_ref or condition.product_ref != offer.terms.product_ref
                    or not scope_covers(condition.scope_ref, offer.scope_ref)):
                raise ValueError('Requotation requirement belongs to another financing scope')
        return completed('requote',note,affected_requirement_refs=profile.requote_requirement_refs)

    def conditions():
        refs = [*offer.terms.condition_refs,*profile.formation_condition_refs]
        rows, pending = {}, list(refs)
        while pending:
            ref = pending.pop()
            if ref.key() in rows:continue
            unique_identities([*(row.ref for row in rows.values()),ref])
            row = reading.resolve(ref)
            if not isinstance(row,QuoteConditionView):
                _unsupported(f'bank-arrangement-projection:{ref.kind}')
            point = row.verification.verified_at if row.verification is not None else now
            available(point,'available_formation_verification')
            evidence(row.evidence_refs,point)
            if (row.application_ref != offer.application_ref or row.product_ref != offer.terms.product_ref
                    or not scope_covers(row.scope_ref,offer.scope_ref)):
                raise ValueError('Formation condition changes the original application, product or scope')
            current(row.effective_window,'current_formation_condition')
            rows[ref.key()]=row;pending.extend(row.dependency_refs)
        states={}
        supplied={ref.key() for ref in action_input.condition_evidence_refs}
        for key,row in rows.items():
            state=row.outcome.value if row.outcome.state=='known' else 'unknown'
            if row.outcome.state=='not_supported':_known(row.outcome,'supported_formation_condition')
            if row.verification is None:state='unknown'
            else:
                verifier=row.verification
                available(verifier.verified_at,'available_formation_verification')
                permitted=(verifier.organization_id in _known(row.authorized_verifier_organization_ids,'formation_verifiers')
                    and verifier.action_id in _known(row.authorized_verifier_action_ids,'formation_verifier_actions')
                    and authority(verifier.authority_ref,verifier.actor_id,verifier.organization_id,
                        verifier.function_ref,verifier.action_id,verifier.verified_at,row.evidence_refs,
                        target_scope=row.scope_ref))
                if not permitted or not {ref.key() for ref in row.evidence_refs} <= supplied:state='unknown'
                else:evidence(row.evidence_refs,verifier.verified_at)
            states[key]=state
        # Cycles block formation; solve remaining prerequisite states to a
        # fixed point, independently of the received graph traversal order.
        for start in rows:
            pending=[ref.key() for ref in rows[start].dependency_refs];seen=set()
            while pending:
                key=pending.pop()
                if key==start:
                    states[start]='unknown';break
                if key not in seen:
                    seen.add(key);pending.extend(ref.key() for ref in rows[key].dependency_refs)
        changed=True
        while changed:
            changed=False
            for key,row in rows.items():
                if states[key]!='satisfied':continue
                dependencies=[states[ref.key()] for ref in row.dependency_refs]
                if any(state!='satisfied' for state in dependencies):
                    states[key]='unknown' if 'unknown' in dependencies else 'unsatisfied';changed=True
        result=[{'requirement_ref':row.ref,'scope_ref':row.scope_ref,'responsible_id':row.responsible_id,
                 'evidence_refs':row.evidence_refs,'outcome':states[key]} for key,row in sorted(rows.items(),key=lambda p:repr(p[0]))]
        unresolved=[row.ref for key,row in rows.items() if states[key]!='satisfied' and row.stage=='arrangement_effective']
        return result,unresolved

    try:
        offer=read(action_input.offer_ref,ArrangementOfferView,at_field='issued_at')
        acceptance=read(action_input.borrower_acceptance_ref,ArrangementAcceptanceView,at_field='accepted_at')
        profile=read(action_input.formation_profile_ref,ArrangementFormationView)
        application=read(offer.application_ref,FinanceApplicationView)
        if (offer.lender_id!=lender or application.lender_id!=lender or offer.terms.borrower_id!=application.borrower_id
                or offer.scope_ref!=application.scope_ref or profile.offer_ref!=offer.ref or profile.lender_id!=lender
                or profile.borrower_id!=offer.terms.borrower_id or profile.scope_ref!=offer.scope_ref):
            raise ValueError('Arrangement mixes original bank, borrower, application or offer scope')
        if not scope_covers(context.scope,offer.scope_ref):raise ValueError('Arrangement exceeds its invocation scope')
        current(profile.effective_window,'current_formation_profile')
        if profile.authority_ref!=action_input.bank_authority_ref or action_input.bank_authority_ref not in context.authorization_refs:
            _needs('current_independent_arrangement_authority')
        if not authority(action_input.bank_authority_ref,context.actor_id,lender,context.function_ref,'BANK-A05',now):
            _needs('current_independent_arrangement_authority')
        available(offer.issued_at,'available_original_offer');available(offer.available_at,'received_original_offer')
        available(acceptance.accepted_at,'available_borrower_acceptance');available(acceptance.available_at,'received_borrower_acceptance')
        if acceptance.accepted_at.offset > acceptance.available_at.offset:raise ValueError('Acceptance receipt precedes its authored decision')
        if (acceptance.offer_ref!=offer.ref or acceptance.scope_ref!=offer.scope_ref
                or acceptance.organization_id!=offer.terms.borrower_id):
            return completed('decline','The borrower acceptance addresses another bank, offer version or scope')
        recorded=read(acceptance.recorded_decision_ref,ArrangementBorrowerDecisionView,at_field='decided_at')
        for field in ('offer_ref','scope_ref','organization_id','actor_id','function_ref','authority_ref','action_id',
                      'decision','accepted_terms','agreement_sha256'):
            if getattr(recorded,field)!=getattr(acceptance,field):raise ValueError('Acceptance differs from its recorded independent decision')
        if recorded.decided_at!=acceptance.accepted_at:raise ValueError('Acceptance changes original decision time')
        if not authority(acceptance.authority_ref,acceptance.actor_id,acceptance.organization_id,acceptance.function_ref,
                         acceptance.action_id,acceptance.accepted_at,[offer.ref]):
            return completed('decline','The received borrower decision lacks lawful independent acceptance authority')
        if acceptance.actor_id==context.actor_id or acceptance.organization_id==lender:
            return completed('decline','The bank cannot substitute its own decision for borrower acceptance')
        if acceptance.decision in {'reject','withdrawn'}:
            return completed('decline','The borrower has rejected or withdrawn its decision')
        if acceptance.decision=='revise':return requote('The borrower proposes different terms requiring a new quotation')
        if acceptance.accepted_terms!=offer.terms or acceptance.agreement_sha256!=accepted_offer_digest(offer):
            return completed('decline','Accepted terms do not match the complete original quotation')
        if not authority(offer.authority_ref,offer.author_actor_id,lender,offer.author_function_ref,'BANK-A04',offer.issued_at):
            _needs('lawfully_issued_original_offer')
        validity=read(offer.terms.validity_ref,TimeWindow)
        time_rule=read(profile.time_rule_ref,ArrangementTimeRuleView)
        if time_rule.lender_id!=lender or time_rule.product_ref!=offer.terms.product_ref:
            raise ValueError('Formation time rule changes the bank or product')
        current(time_rule.effective_window,'current_formation_time_rule')
        def valid(point, window=validity):
            if point.clock_ref!=window.start.clock_ref:_unsupported('bank-arrangement-clock-alignment')
            if point.offset==window.end.offset:
                return time_rule.equality_rule=='acceptance_first' and point.offset>=window.start.offset
            return window.contains(point)
        if (offer.status!='offered' or not valid(acceptance.accepted_at) or not valid(now)
                or not valid(now,offer.effective_window)
                or acceptance.accepted_at.offset<max(offer.issued_at.offset,offer.available_at.offset)):
            return requote('The original quotation or acceptance has expired, been superseded or is not yet valid')
        if application.status=='withdrawn':return completed('decline','The underlying application has been withdrawn')
        if application.status!='submitted':_needs('submitted_finance_application')
        if offer.terms.product_ref not in application.product_candidates:raise ValueError('Offered product was not requested')
        if offer.terms.purpose_ref!=application.purpose_ref:raise ValueError('Offer changes original requested purpose')
        if offer.terms.product_ref not in profile.allowed_product_refs or offer.terms.pricing_ref not in profile.allowed_pricing_refs:
            return completed('decline','The final terms are outside the independent formation authority')
        principal=amount(offer.terms.principal_limit)
        if principal>amount(application.requested) or principal>amount(_known(profile.maximum_principal,'formation_authority_limit')):
            return completed('decline','Offered principal exceeds the request or current independent authority limit')
        unique_identities(action_input.condition_evidence_refs)
        evidence(action_input.condition_evidence_refs,check_window=False)
        condition_rows,unresolved=conditions()
        if unresolved and not profile.allow_signed_pending_conditions:_needs('arrangement_effective_conditions',unresolved)
        reservation=read(offer.reservation_policy_ref,QuoteReservationView)
        if (reservation.application_ref!=application.ref or reservation.product_ref!=offer.terms.product_ref
                or reservation.borrower_id!=offer.terms.borrower_id or reservation.lender_id!=lender
                or reservation.expiry_ref!=offer.terms.validity_ref
                or reservation.acceptance_action_id!=acceptance.action_id):
            raise ValueError('Original reservation policy changes the accepted quotation')
        current(reservation.effective_window,'current_original_reservation_policy')
        capacity=read(action_input.capacity_snapshot_ref,CreditLendingCapacityView)
        portfolio=read(capacity.portfolio_ref,CreditBankPortfolioView)
        if capacity.lender_id!=lender or portfolio.lender_id!=lender:raise ValueError('Current capacity belongs to another bank')
        available(capacity.as_of,'current_formation_capacity',exact=True)
        available(portfolio.as_of,'current_bank_portfolio',exact=True)
        if portfolio.coverage!='complete':_needs('complete_current_bank_portfolio')
        if capacity.currency!=offer.terms.principal_limit.currency:_unsupported('bank-arrangement-capacity-currency')
        limit=amount(_known(capacity.commitment_limit,'current_bank_commitment_limit'));occupied=0;own_reserved=[]
        for ref in portfolio.commitment_refs:
            item=read(ref,ArrangementCommitmentView)
            if item.lender_id!=lender:raise ValueError('Bank portfolio includes another bank commitment')
            available(item.as_of,'current_commitment_occupancy',exact=True)
            if item.status=='released':evidence([item.release_evidence_ref]);continue
            value=amount(_known(item.amount,'actual_bank_commitment_occupancy'));occupied+=value
            if item.origin_offer_ref==offer.ref:
                if item.borrower_id!=offer.terms.borrower_id or item.scope_ref!=offer.scope_ref or value!=principal:
                    raise ValueError('Original quotation reservation changes its borrower, scope or amount')
                if item.status=='committed' or item.origin_arrangement_ref is not None:
                    _needs('reconcile_existing_financing_arrangement',[item.ref])
                own_reserved.append(item)
        if len(own_reserved)>1:raise ValueError('One quotation has multiple active original reservations')
        if reservation.reserves_capacity and not own_reserved:_needs('actual_original_quote_reservation')
        if not reservation.reserves_capacity and own_reserved:raise ValueError('An unreserved offer claims existing reservation capacity')
        increment=0 if own_reserved else principal
        if occupied+increment>limit:return requote('Current capacity no longer permits the accepted quotation')
        return completed('confirm','Confirm this exact independent acceptance; formal signature/effectiveness and capacity conversion remain host-owned',
            offer_ref=offer.ref,acceptance_ref=acceptance.ref,conditions=condition_rows)
    except ObservationGap as gap:
        return gap.result
