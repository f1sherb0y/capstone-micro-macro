"""Enrich an original A01 result with actual, strictly earlier demand analysis."""
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_monthly_demand import MonthlyOwnerDemandObservation,MonthlyOwnerDemandJudgment
from src.coordination.tasks import task_digest


def analyze_monthly_demand(context,action_input,reading,*,objective,choice):
    observation=reading.resolve(objective.monthly_demand_observation_ref)
    if not isinstance(observation,MonthlyOwnerDemandObservation):raise ValueError('Monthly demand requires typed actual observations')
    if (observation.organization_id!=reading.organization_id or observation.scope!=context.scope or observation.as_of!=context.business_time
            or context.scope.kind!='organization' or choice not in {'propose','ignore'}
            or action_input.existing_case_refs or action_input.opportunity_refs
            or len(action_input.observations)!=1 or objective.signal_rules.state!='known' or len(objective.signal_rules.value)!=1):
        raise ValueError('Monthly global analysis cannot stand in for a project candidate, existing case or financial review')
    signal=reading.resolve(action_input.observations[0]);rule=objective.signal_rules.value[0]
    if (signal.signal_code!='native_global_market_demand_index' or rule.signal_code!=signal.signal_code
            or signal.region_id!='simulation_global' or signal.use_code!='background_portfolio_demand'
            or rule.comparison!='at_least' or signal.measure.state!='known'
            or signal.measure.value!=observation.current_market_index):
        raise ValueError('Monthly demand changes its actual global source or original screening rule')
    for ref in observation.evidence_refs:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or source.basis_kind!='observed' or (source.effective_window is not None and not source.effective_window.contains(context.business_time)):
            raise ValueError('Monthly demand requires current actual native evidence')
    for measure,unit in [(observation.current_market_index,'index'),(rule.threshold,'index'),(observation.native_available_resource,'native_resource')]:
        reading.resolve(measure.basis_ref)
        if measure.unit!=unit or not Decimal(measure.value).is_finite() or Decimal(measure.value)<0:raise ValueError('Demand analysis requires finite values with original units')
    current=Decimal(observation.current_market_index.value);threshold=Decimal(rule.threshold.value)
    qualifies=current>=threshold
    if qualifies!=(choice=='propose'):raise ValueError('Monthly interpretation contradicts the original A01 threshold judgment')
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(
            h['micro_identity']['organization_id']!=reading.organization_id or h['micro_identity']['action_id']!='OWN-A01'
            or h['operation']!='evaluate_market_demand' or not h['participated'] or not 0<h['tick']<context.business_time.offset for h in history):
        raise ValueError('Demand analysis borrows a different owner, business or future outcome')
    analyses=[]
    for h in history:
        analysis=MonthlyOwnerDemandJudgment.model_validate(h['analysis'])
        if h['analysis_sha256']!=task_digest(h['analysis']):raise ValueError('Earlier executed demand analysis artifact changed')
        analyses.append((h['tick'],analysis))
    previous=max(analyses,key=lambda item:item[0])[1].current_market_index.value if analyses else None
    delta=None if previous is None else current-Decimal(previous)
    trend='initial' if delta is None else 'rising' if delta>0 else 'falling' if delta<0 else 'flat'
    interpretation=('Demand reaches the declared private screening threshold; retain only an unexecuted private follow-up intent.' if qualifies else
        'Demand is below the declared private screening threshold; continue observation without a case or project commitment.')
    interpretation+=' Current demand trend versus the previous actually executed own analysis: '+trend+'.'
    reading.recheck()
    return MonthlyOwnerDemandJudgment(original_choice=choice,current_market_index=observation.current_market_index,
        declared_screening_threshold=rule.threshold,meets_screening_threshold=qualifies,prior_actual_analysis_count=len(history),
        previous_actual_index=previous,change_from_previous_actual_analysis=None if delta is None else str(delta),trend=trend,
        consumed_event_ids=[h['event_id'] for h in history],consumed_analysis_sha256=[h['analysis_sha256'] for h in history],interpretation=interpretation)
