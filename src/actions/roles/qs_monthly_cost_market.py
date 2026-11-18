"""QS-A01 reviews actual native indices after original source eligibility checks."""
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.qs_monthly_cost_market import MonthlyCostPolicy,MonthlyCostObservation,MonthlyCostJudgment
from src.coordination.tasks import task_digest


def analyze_monthly_cost_market(context,reading,*,strategy,source_refs):
    policy=reading.resolve(strategy.monthly_cost_policy_ref)
    observation=reading.resolve(strategy.monthly_cost_observation_ref)
    if not isinstance(policy,MonthlyCostPolicy) or not isinstance(observation,MonthlyCostObservation):
        raise ValueError('Cost-market analysis requires declared policy and actual typed observations')
    if (policy.organization_id!=reading.organization_id or observation.organization_id!=reading.organization_id
            or policy.scope!=context.scope or observation.scope!=context.scope or observation.as_of!=context.business_time
            or not policy.effective_window.contains(context.business_time)
            or policy.authority_ref!=strategy.author_authority_ref or policy.authority_ref not in context.authorization_refs
            or len(source_refs)!=1):
        raise ValueError('Cost-market analysis changes original own scope, time, authority or source')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:
        evidence=reading.resolve(ref)
        if not isinstance(evidence,EvidenceRecord) or (evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise ValueError('Cost-market analysis lacks current original evidence')
    def number(measured,unit):
        reading.resolve(measured.basis_ref);value=Decimal(measured.value)
        if measured.unit!=unit or not value.is_finite() or value<0:raise ValueError('Invalid original index or explicit unit')
        return value
    current=number(observation.material_index,'index');base=number(policy.baseline_material_index,'index')
    threshold=number(policy.pressure_threshold,'ratio');minimum=number(policy.minimum_relative_change,'ratio')
    if base<=0:raise ValueError('Private baseline must be positive')
    history=observation.prior_own_outcomes;entries=observation.registered_indices
    if len({h['event_id'] for h in history})!=len(history) or any(
            h['micro_identity']['organization_id']!=reading.organization_id or h['micro_identity']['action_id']!='QS-A01'
            or not 0<h['tick']<context.business_time.offset for h in history):
        raise ValueError('Cost-market analysis borrows another firm or future result')
    updates=[h for h in history if h['participated'] and h['operation']=='update_cost_database']
    if {h['event_id'] for h in updates}!={e['native_event_id'] for e in entries}:
        raise ValueError('Registered knowledge must correspond exactly to confirmed own native updates')
    for entry in entries:
        if (entry['organization_id']!=reading.organization_id or not entry['observed_tick']<entry['registered_tick']<=context.business_time.offset
                or entry['record_sha256']!=task_digest({k:v for k,v in entry.items() if k!='record_sha256'})
                or entry['material_index']['unit']!='index' or Decimal(entry['material_index']['value'])<=0):
            raise ValueError('Registered index changes its provenance, ownership or publication time')
    pressure=max(Decimal(0),current/base-1)
    last=max(entries,key=lambda e:e['observed_tick']) if entries else None
    change=None if last is None else (current/Decimal(last['material_index']['value'])-1)
    update=len(updates)<policy.maximum_updates and (last is None or abs(change)>=minimum)
    operation='update_cost_database' if update else 'review_cost_market'
    interpretation=('Register the original dimensionless simulation material index after confirmed native execution.' if update else
        'Review the current simulation material index against the registered original; defer another registration under the private update limit or change threshold.')
    return MonthlyCostJudgment(operation=operation,material_index=observation.material_index,baseline_material_index=policy.baseline_material_index,
        positive_cost_pressure=str(pressure),pressure_priority='urgent' if pressure>=threshold else 'routine',
        relative_change_from_registered=None if change is None else str(change),prior_actual_update_count=len(updates),
        consumed_event_ids=[h['event_id'] for h in history],consumed_registration_keys=[e['key'] for e in entries],
        source_ref=source_refs[0],interpretation=interpretation)
