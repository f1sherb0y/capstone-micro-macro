"""Original commercial record_lesson may retain a sourced future bid policy."""
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.contractor_monthly_strategy import MonthlyBidStrategyPolicy,MonthlyBidStrategyObservation,MonthlyBidStrategyJudgment


def analyze_monthly_bid_strategy(context,action_input,reading,*,profile,state,action_id):
    policy=reading.resolve(profile.monthly_bid_policy_ref);observation=reading.resolve(profile.monthly_bid_observation_ref)
    if not isinstance(policy,MonthlyBidStrategyPolicy) or not isinstance(observation,MonthlyBidStrategyObservation):raise ValueError('Typed private strategy sources required')
    if (action_id!='CONTRACTOR-A12' or profile.choice!='record_lesson' or context.scope.kind!='organization'
            or policy.scope!=context.scope or observation.scope!=context.scope or policy.organization_id!=reading.organization_id
            or observation.organization_id!=reading.organization_id or policy.authority_ref not in context.authorization_refs
            or not policy.effective_window.contains(context.business_time) or observation.as_of!=context.business_time
            or state.as_of!=context.business_time or state.coverage!='unknown'
            or any(getattr(action_input,f) for f in ('resource_commitment_refs','material_position_refs','obligation_refs'))
            or len(action_input.observation_refs)!=1 or profile.source_refs!=action_input.observation_refs or state.observation_refs!=action_input.observation_refs
            or any(getattr(profile,f) for f in ('retain_resource_refs','release_candidate_refs','readiness_refs'))
            or profile.transfer_plan_ref is not None or profile.learning_method_ref is None or profile.lesson_assessment_ref is not None):
        raise ValueError('Monthly private policy must not substitute a transition, learned performance or complete commercial ledger')
    for ref in [*policy.evidence_refs,*observation.evidence_refs,policy.material_index_threshold.basis_ref,observation.material_index.basis_ref]:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or source.effective_window is None or not source.effective_window.contains(context.business_time):
            raise ValueError('Current authorized original strategy evidence required')
    current=Decimal(observation.material_index.value);threshold=Decimal(policy.material_index_threshold.value)
    base=Decimal(policy.base_markup);increment=Decimal(policy.risk_markup_increment)
    if (observation.material_index.unit!='index' or policy.material_index_threshold.unit!='index'
            or any(not n.is_finite() for n in (current,threshold,base,increment)) or min(current,threshold)<=0
            or min(base,increment)<0 or base+increment>1):raise ValueError('Finite dimensionless index and bounded independent markup policy required')
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(h['micro_identity']['organization_id']!=reading.organization_id
            or h['micro_identity']['action_id']!='CONTRACTOR-A12' or h['operation']!='adjust_bid_strategy'
            or not h['participated'] or not 0<h['tick']<context.business_time.offset for h in history):
        raise ValueError('Private strategy cannot borrow future, foreign or unexecuted outcomes')
    high=current>threshold;markup=base+(increment if high else 0)
    note='Recommend the independently authorized material-risk markup for a future private bid dossier.' if high else 'Retain the independently authorized base markup for a future private bid dossier.'
    note+=' This dimensionless simulation signal is not a monetary cost, actual bid outcome, learned win rate, completed work or firm-wide financial ledger.'
    reading.recheck()
    return MonthlyBidStrategyJudgment(material_index=observation.material_index,threshold=policy.material_index_threshold,
        high_material_risk=high,next_private_markup=str(markup),consumed_event_ids=[h['event_id'] for h in history],
        consumed_result_sha256=[h['micro_result_sha256'] for h in history],interpretation=note)
