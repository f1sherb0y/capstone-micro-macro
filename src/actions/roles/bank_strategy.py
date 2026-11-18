"""BANK-A01 explicit policy selection with original commitments preserved."""
from fractions import Fraction

from src.actions.contracts.bank_credit_objects import CreditCommitmentView, CreditLendingCapacityView, unique_identities
from src.actions.contracts.bank_strategy_objects import (
    LendingStrategyView, StrategyIssueView, StrategyMarketView, StrategyObservationView,
    StrategyObligationView, StrategyPolicyView, StrategyPortfolioView, StrategySpaceView,
)
from src.actions.contracts.common import EvidenceRecord
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def manage_strategy(context,action_input,reading):
    now,lender=context.business_time,reading.organization_id

    def current(window,field):
        if window.start.clock_ref!=now.clock_ref:_unsupported('bank-strategy-clock-alignment')
        if not window.contains(now):_needs(field)

    def available(point,field,exact=False):
        if point.clock_ref!=now.clock_ref:_unsupported('bank-strategy-clock-alignment')
        if point.offset>now.offset or (exact and point!=now):_needs(field)

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):_unsupported('bank-strategy-evidence-schema')
            if row.effective_window is not None:current(row.effective_window,'current_strategy_evidence')

    def read(ref,schema):
        row=reading.resolve(ref)
        if not isinstance(row,schema):_unsupported(f'bank-strategy-projection:{ref.kind}')
        evidence(getattr(row,'evidence_refs',[]));return row

    def amount(value):
        evidence([value.basis_ref])
        if value.currency!=capacity.currency:_unsupported('bank-strategy-currency-conversion')
        return decimal_fraction(value.value)

    def completed(choice,note,**fields):
        if choice in {'retain_strategy','revise_strategy'}:
            from src.actions.roles.bank_monthly_risk import monthly_risk_note
            note=monthly_risk_note(context,reading,space,choice=choice,note=note)
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,'basis_refs':list(basis.values()),'note':note,**fields}}

    def investigate(note):
        subjects={ref.key() for ref in [action_input.portfolio_ref,action_input.capacity_ref,space.ref,
            *action_input.obligation_refs,*action_input.market_refs,*action_input.policy_refs,*basis.values()]}
        if space.current_strategy_ref.state=='known':subjects.add(space.current_strategy_ref.value.key())
        if space.candidate_refs.state=='known':subjects.update(ref.key() for ref in space.candidate_refs.value)
        for ref in space.investigation_issue_refs:
            row=read(ref,StrategyIssueView)
            if (row.lender_id!=lender or row.scope_ref!=space.scope_ref
                    or not any(ref.key() in subjects for ref in row.subject_refs)):
                raise ValueError('Strategy investigation issue changes bank, scope or supplied subject')
            current(row.effective_window,'current_strategy_issue')
            if row.status!='open':_needs('open_strategy_investigation_issue')
        return completed('investigate',note,issue_refs=space.investigation_issue_refs,scope_ref=space.scope_ref)

    try:
        portfolio=read(action_input.portfolio_ref,StrategyPortfolioView)
        capacity=read(action_input.capacity_ref,CreditLendingCapacityView)
        space=read(action_input.strategy_space_ref,StrategySpaceView)
        if (portfolio.lender_id!=lender or capacity.lender_id!=lender or space.lender_id!=lender
                or capacity.portfolio_ref!=portfolio.ref or not scope_covers(context.scope,space.scope_ref)):
            raise ValueError('Strategy decision changes the original bank, capacity portfolio or authorized scope')
        available(portfolio.as_of,'current_strategy_portfolio',exact=True)
        available(capacity.as_of,'current_strategy_capacity',exact=True)
        current(space.effective_window,'current_strategy_space')
        for refs in (action_input.obligation_refs,action_input.market_refs,action_input.policy_refs):unique_identities(refs)
        if portfolio.coverage!='complete':_needs('complete_visible_bank_portfolio')
        if set(action_input.obligation_refs)!=set(portfolio.obligation_refs):_needs('complete_original_bank_obligations',portfolio.obligation_refs)
        if set(action_input.market_refs)!=set(space.market_refs) or set(action_input.policy_refs)!=set(space.policy_refs):
            _needs('complete_strategy_market_and_policy_inputs',[*space.market_refs,*space.policy_refs])
        limit=amount(_known(capacity.commitment_limit,'current_lending_commitment_limit'));occupied=Fraction()
        for ref in portfolio.commitment_refs:
            row=read(ref,CreditCommitmentView)
            if row.lender_id!=lender:raise ValueError('Strategy portfolio contains another bank commitment')
            available(row.as_of,'current_original_bank_commitment',exact=True)
            if row.status=='released':evidence([row.release_evidence_ref])
            else:occupied+=amount(_known(row.amount,'actual_reserved_or_committed_occupancy'))
        obligations=[]
        for ref in portfolio.obligation_refs:
            row=read(ref,StrategyObligationView)
            if row.lender_id!=lender:raise ValueError('Strategy obligation belongs to another bank')
            available(row.as_of,'current_original_bank_obligation',exact=True)
            if row.due_at.clock_ref!=now.clock_ref:_unsupported('bank-strategy-clock-alignment')
            unpaid=amount(_known(row.actual_due,'actual_bank_obligation_due'))-amount(_known(row.actual_paid,'actual_bank_obligation_paid'))
            if unpaid<0:raise ValueError('Bank obligation paid amount exceeds actual due')
            obligations.append((row,unpaid))
        remaining=max(Fraction(),limit-occupied)
        observations={};basis={};policies=[]
        for ref,schema in [(ref,StrategyMarketView) for ref in space.market_refs]+[(ref,StrategyPolicyView) for ref in space.policy_refs]:
            row=read(ref,schema)
            if getattr(row,'recipient_lender_id',getattr(row,'lender_id',None))!=lender:
                raise ValueError('Strategy observation is addressed to another bank')
            current(row.effective_window,'applicable_strategy_observation')
            original=read(row.observation_ref,StrategyObservationView)
            if original.recipient_lender_id!=lender or not scope_covers(original.scope_ref,space.scope_ref):
                raise ValueError('Strategy observation changes authorized recipient or scope')
            available(original.observed_at,'observed_strategy_signal');available(original.available_at,'available_strategy_signal')
            if original.observed_at.offset>original.available_at.offset:raise ValueError('Signal receipt precedes its observation')
            current(original.effective_window,'current_original_strategy_observation')
            observations[original.ref.key()]=original;basis[original.ref.key()]=original.ref
            if isinstance(row,StrategyPolicyView):policies.append(row)
        if not basis:_needs('sourced_strategy_observations')
        unique_identities(list(basis.values()))

        def eligible(ref):
            profile=read(ref,LendingStrategyView)
            if profile.lender_id!=lender or profile.scope_ref!=space.scope_ref:
                raise ValueError('Strategy profile changes bank or authorized scope')
            current(profile.effective_window,'current_strategy_candidate')
            grant=read(profile.authority_ref,Authorization);assignment=read(profile.author_function_ref,RoleAssignment)
            if (grant.actor_id!=profile.author_actor_id or grant.organization_id!=lender
                    or grant.function_ref!=profile.author_function_ref or assignment.role!='Bank'
                    or profile.originating_action_id not in grant.action_ids or not grant.validity.contains(now)
                    or not any(scope_covers(scope,space.scope_ref) for scope in grant.scopes)):
                _needs('authorized_strategy_candidate')
            evidence([ref for ref in [*grant.basis_refs,*assignment.basis_refs] if ref.kind=='Evidence'])
            for policy in policies:
                if ref not in _known(policy.allowed_strategy_refs,'known_policy_strategy_permissions'):return False
            max_new=amount(_known(profile.maximum_new_commitment,'strategy_new_commitment_limit'))
            if max_new>remaining:return False
            current(profile.obligation_horizon,'strategy_obligation_horizon')
            due=sum((unpaid for row,unpaid in obligations if row.due_at.offset<=profile.obligation_horizon.end.offset),Fraction())
            if due>amount(_known(profile.maximum_due_obligations,'strategy_due_obligation_threshold')):return False
            for test in profile.signal_tests:
                signal=observations.get(test.observation_ref.key())
                if signal is None:_needs('declared_strategy_signal',[test.observation_ref])
                interval=_known(signal.interval,'known_strategy_signal_interval')
                if interval.lower.unit!=test.threshold.unit:_unsupported('bank-strategy-unit-conversion')
                evidence([test.threshold.basis_ref,interval.lower.basis_ref,interval.upper.basis_ref])
                lower,upper,threshold=(decimal_fraction(v.value) for v in (interval.lower,interval.upper,test.threshold))
                if test.predicate=='at_most':
                    if upper<=threshold:continue
                    if lower>threshold:return False
                else:
                    if lower>=threshold:continue
                    if upper<threshold:return False
                _needs('determinate_strategy_signal_threshold',[signal.ref])
            return True

        unknowns=[]
        if space.current_strategy_ref.state=='known':
            try:
                if eligible(space.current_strategy_ref.value):
                    return completed('retain_strategy','The authorized current strategy remains eligible; original contracts and occupancy stay unchanged')
            except ObservationGap as gap:unknowns.append(gap.result)
        elif space.current_strategy_ref.state not in {'not_applicable'}:
            _known(space.current_strategy_ref,'declared_current_strategy')
        if space.candidate_refs.state=='not_supported':_known(space.candidate_refs,'defined_strategy_candidates')
        if space.candidate_refs.state!='known':
            if unknowns:return investigate('Current strategy evidence is unresolved; investigate without inventing a replacement')
            _known(space.candidate_refs,'defined_strategy_candidates')
        candidates=[]
        for ref in space.candidate_refs.value:
            try:
                if eligible(ref):
                    profile=read(ref,LendingStrategyView)
                    candidates.append((_known(profile.selection_priority,'declared_strategy_priority'),ref))
            except ObservationGap as gap:unknowns.append(gap.result)
        if unknowns:
            if any(gap['kind']=='unsupported' for gap in unknowns):raise ObservationGap(next(gap for gap in unknowns if gap['kind']=='unsupported'))
            return investigate('Unresolved current or candidate evidence requires a sourced investigation')
        if not candidates:return investigate('No supplied authorized strategy meets current original capacity, obligations and policy')
        best=min(priority for priority,_ in candidates);selected=[ref for priority,ref in candidates if priority==best]
        if len(selected)!=1:return investigate('Declared strategy priorities leave a tie requiring investigation')
        return completed('revise_strategy','Select this authorized new-business profile; existing contract terms and commitments are untouched',strategy_ref=selected[0])
    except ObservationGap as gap:
        return gap.result
