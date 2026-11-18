"""Select a declared future private preference without rewriting returns, cash or obligations."""
from decimal import Decimal
from src.actions.contracts.owner_monthly_strategy import MonthlyInvestmentPolicy,MonthlyInvestmentObservation,MonthlyInvestmentJudgment
from src.actions.contracts.owner_operating_objects import OwnerOperatingPreferenceView
from src.actions.contracts.common import EvidenceRecord
from src.coordination.tasks import task_digest


def select_monthly_strategy(context,action_input,reading,*,profile,portfolio,observations,read,author):
    if (profile.monthly_strategy_policy_ref is None or profile.monthly_strategy_observation_ref is None
            or profile.choice!='retain_policy' or profile.preference_profile_ref is not None
            or action_input.learning_method_ref is not None or profile.proposed_limit is not None
            or profile.budget_authority_ref is not None or profile.allocations or profile.allocation_task_refs
            or profile.replaced_commitment_refs or profile.allocation_revision_ref is not None):
        raise ValueError('Monthly strategy requires unselected preferences and cannot substitute learning, budgets or allocations')
    policy=reading.resolve(profile.monthly_strategy_policy_ref);observation=reading.resolve(profile.monthly_strategy_observation_ref)
    if not isinstance(policy,MonthlyInvestmentPolicy) or not isinstance(observation,MonthlyInvestmentObservation):
        raise ValueError('Monthly strategy requires typed independent policy and actual observation')
    if (policy.organization_id!=reading.organization_id or observation.organization_id!=reading.organization_id
            or policy.scope!=context.scope or observation.scope!=context.scope or observation.as_of!=context.business_time
            or not policy.effective_window.contains(context.business_time) or policy.authority_ref!=profile.authority_ref
            or portfolio.execution_refs):
        raise ValueError('Monthly strategy changes current own authority, scope, clock or isolated portfolio history')
    for ref in [*policy.evidence_refs,*observation.evidence_refs,policy.financing_watch_threshold.basis_ref,observation.financing_index.basis_ref]:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or source.effective_window is not None and not source.effective_window.contains(context.business_time):
            raise ValueError('Monthly strategy lacks original current source evidence')
    if (not observations or any(o.kind!='market' or o.outcome_code is not None or o.dimension_codes for o in observations.values())):
        raise ValueError('Monthly environment review is not a mature investment outcome or learned return')
    current=Decimal(observation.financing_index.value);threshold=Decimal(policy.financing_watch_threshold.value)
    minimum=Decimal(policy.minimum_weight_change)
    if (not current.is_finite() or not threshold.is_finite() or not minimum.is_finite() or current<=0 or threshold<=0
            or not 0<minimum<=1 or observation.financing_index.unit!='index' or policy.financing_watch_threshold.unit!='index'):
        raise ValueError('Monthly strategy requires positive explicit index and bounded change threshold')
    prior=read(portfolio.current_preference_ref,OwnerOperatingPreferenceView,linked=True);author(prior)
    candidates=[read(ref,OwnerOperatingPreferenceView,linked=True) for ref in [policy.normal_preference_ref,policy.watch_preference_ref]]
    for candidate in candidates:
        author(candidate)
        if (candidate.organization_id!=reading.organization_id or candidate.author_organization_id!=reading.organization_id
                or candidate.prior_profile_ref!=prior.ref or candidate.purpose!=prior.purpose
                or set(candidate.scores)!=set(prior.scores) or candidate.requires_learning or candidate.learning_assessment_ref is not None
                or candidate.basis_refs!=profile.basis_refs):
            raise ValueError('Monthly strategy candidate changes authorized prior, purpose, dimensions or source basis')
    weights=[Decimal(v) for p in [prior,*candidates] for v in p.scores.values()]
    if any(not v.is_finite() or not 0<v<=1 for v in weights):raise ValueError('Private comparison weights require bounded positive values')
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(
            h['micro_identity']['organization_id']!=reading.organization_id or h['micro_identity']['action_id']!='OWN-A15'
            or not 0<h['tick']<context.business_time.offset or h['strategy_sha256']!=task_digest(h['strategy'])
            or h['operation']!=('adjust_investment_strategy' if h['participated'] else 'maintain_operations') for h in history):
        raise ValueError('Monthly strategy borrows foreign, future, rewritten or unexecuted policy history')
    active=[h for h in sorted(history,key=lambda h:h['tick']) if h['participated']]
    if active:
        accepted=MonthlyInvestmentJudgment.model_validate(active[-1]['strategy'])
        if prior.ref!=accepted.effective_preference_ref or prior.scores!=accepted.effective_scores:
            raise ValueError('Current private preferences differ from the actually accepted earlier strategy')
    watch=current<threshold;proposed=candidates[int(watch)]
    change=max(abs(Decimal(proposed.scores[k])-Decimal(prior.scores[k])) for k in prior.scores)
    participate=change>=minimum and len(active)<policy.maximum_updates
    effective=proposed if participate else prior
    return MonthlyInvestmentJudgment(original_choice='revise_preferences' if participate else 'retain_policy',participate=participate,
        financing_index=observation.financing_index,financing_watch=watch,current_preference_ref=prior.ref,
        proposed_preference_ref=proposed.ref,effective_preference_ref=effective.ref,proposed_scores=proposed.scores,effective_scores=effective.scores,
        maximum_weight_change=str(change),prior_actual_update_count=len(active),consumed_event_ids=[h['event_id'] for h in history],
        interpretation='Apply the independently authorized financing-environment rule to future private investment criteria only; '
            + ('propose a preference revision.' if participate else 'retain the actual earlier adopted version after current review.'))
