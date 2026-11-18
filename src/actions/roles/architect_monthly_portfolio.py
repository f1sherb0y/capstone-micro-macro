"""Original A12 computes a private portfolio update from authenticated selections."""
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.architect_monthly_portfolio import (
    MonthlyPortfolioPolicy,MonthlyPortfolioObservation,MonthlyPortfolioJudgment,PortfolioEntry,
)


def analyze_monthly_portfolio(context,action_input,reading,*,decision,state,capability):
    policy=reading.resolve(decision.monthly_portfolio_policy_ref)
    observation=reading.resolve(decision.monthly_portfolio_observation_ref)
    org=reading.organization_id;now=context.business_time
    if not isinstance(policy,MonthlyPortfolioPolicy) or not isinstance(observation,MonthlyPortfolioObservation):
        raise ValueError('Portfolio requires both typed independent policy and actual observations')
    if (policy.organization_id!=org or observation.organization_id!=org
            or policy.scope!=context.scope or observation.scope!=context.scope or context.scope.kind!='organization'
            or context.scope.ref.id!=org
            or observation.as_of!=now or state.as_of!=now or not policy.effective_window.contains(now)
            or policy.authority_ref!=decision.authority_ref or policy.authority_ref not in context.authorization_refs):
        raise ValueError('Portfolio substitutes original own scope, authority or current time')
    if (decision.choice!='record_feedback' or action_input.learning_profile_ref is not None or action_input.feedback_refs
            or decision.feedback_refs or decision.assessment_ref is not None or decision.training_profile_ref is not None
            or state.coverage!='unknown' or capability.status!='unknown' or state.received_feedback_refs
            or state.applied_feedback_refs or state.execution_refs or capability.verified_capability_codes or capability.qualification_refs):
        raise ValueError('Selection portfolio cannot assert complete learning, training or qualifications')
    if not policy.permitted_regions or len(set(policy.permitted_regions))!=len(policy.permitted_regions):
        raise ValueError('Portfolio requires distinct explicitly permitted regions')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or source.content_hash is None or (
                source.effective_window is not None and not source.effective_window.contains(now)):
            raise ValueError('Portfolio lacks actually received current evidence')
    def number(value,unit,upper=None):
        reading.resolve(value.basis_ref);n=Decimal(value.value)
        if value.unit!=unit or n<0 or upper is not None and n>upper:
            raise ValueError('Portfolio requires explicit nonnegative native indices and bounded ratios')
        return n
    market=number(observation.market_demand,'index');free=number(observation.native_free_ratio,'ratio',1)
    market_gate=market>=number(policy.minimum_market_demand,'index')
    capacity_gate=free>=number(policy.minimum_free_ratio,'ratio',1)
    entries=observation.selected_entries
    if len({e.event_id for e in entries})!=len(entries) or any(
            e.organization_id!=org or not 0<e.tick<=now.offset or e.region not in policy.permitted_regions
            or e.appointment_identity.get('organization_id')!=org
            or e.appointment_identity.get('run_id')!=context.run_id
            or e.appointment_identity.get('action_id')!='ARCHITECT-A03' for e in entries):
        raise ValueError('Portfolio borrows another organization, run, region, future or unconfirmed selection')
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(
            h['micro_identity']['organization_id']!=org or h['micro_identity']['run_id']!=context.run_id
            or h['micro_identity']['action_id']!='ARCHITECT-A12' or not 0<h['tick']<now.offset for h in history):
        raise ValueError('Portfolio consumes another firm, run or future monthly outcome')
    previous=[]
    for h in sorted(history,key=lambda h:h['tick']):
        prior=MonthlyPortfolioJudgment.model_validate(h['portfolio_judgment'])
        if prior.participate!=h['participated']:
            raise ValueError('Portfolio artifact differs from confirmed original operation')
        previous=[PortfolioEntry.model_validate(e) for e in prior.adopted_entries]
    current={e.event_id:e for e in entries};old={e.event_id:e for e in previous}
    if any(k not in current or current[k]!=v for k,v in old.items()):
        raise ValueError('Portfolio rewrites an earlier adopted original selection')
    new=sorted(set(current)-set(old));participate=market_gate and capacity_gate and bool(new)
    judgment=MonthlyPortfolioJudgment(participate=participate,market_demand=observation.market_demand,
        native_free_ratio=observation.native_free_ratio,market_gate=market_gate,capacity_gate=capacity_gate,
        selected_entries=entries,new_entry_event_ids=new,adopted_entries=entries if participate else previous,
        consumed_monthly_event_ids=[h['event_id'] for h in history],interpretation=(
            'Update the private selected-project portfolio from received and privately confirmed native appointments.' if participate else
            'Retain the prior confirmed private portfolio after checking market demand, free ratio and new selection evidence.'))
    reading.recheck();return judgment.model_dump_json()
