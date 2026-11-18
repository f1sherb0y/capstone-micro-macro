"""Optional GOV-A12 analysis chooses the original bounded monthly business."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_monthly_objects import GovMonthlyPolicy,GovMonthlyObservation,GovMonthlyJudgment,OPERATIONS
from src.methods.pricing import decimal_fraction


def analyze_monthly_business(context,reading,profile):
    if profile.monthly_policy_ref is None:return None
    policy=reading.resolve(profile.monthly_policy_ref)
    observed=reading.resolve(profile.monthly_observation_ref)
    if (not isinstance(policy,GovMonthlyPolicy) or not isinstance(observed,GovMonthlyObservation)
            or policy.organization_id!=reading.organization_id or observed.organization_id!=reading.organization_id
            or policy.scope!=context.scope or observed.scope!=context.scope or observed.as_of!=context.business_time
            or policy.actor_id!=context.actor_id or policy.function_ref!=context.function_ref
            or policy.authority_ref!=profile.authority_ref or not policy.effective_window.contains(context.business_time)):
        raise ValueError('Monthly regulatory analysis changes original current own authority or scope')
    if set(policy.allowed_operations)!=OPERATIONS or len(policy.allowed_operations)!=len(OPERATIONS):
        raise ValueError('Monthly regulatory policy requires the independently authorized bounded operation set')
    demand,threshold=observed.market_demand,policy.minimum_demand_for_focus
    if demand.unit!='index' or threshold.unit!='index' or min(decimal_fraction(demand.value),decimal_fraction(threshold.value))<0:
        raise ValueError('Monthly regulatory demand requires nonnegative original index units')
    refs=[*policy.evidence_refs,*observed.evidence_refs,demand.basis_ref,threshold.basis_ref]
    for ref in refs:
        source=reading.resolve(ref)
        if (not isinstance(source,EvidenceRecord) or source.content_hash is None
                or source.effective_window is not None and not source.effective_window.contains(context.business_time)):
            raise ValueError('Monthly regulatory analysis lacks current authenticated source evidence')
    counts={op:0 for op in sorted(OPERATIONS)}
    for previous in observed.prior_own_operations:
        op=previous.get('operation','review_policy_feedback')
        if (previous['organization_id']!=reading.organization_id or previous['tick']>=context.business_time.offset
                or op not in OPERATIONS or not previous['source_event_sha256']):
            raise ValueError('Monthly regulatory analysis borrows another agency or nonprior result')
        counts[op]+=1
    outcomes=observed.prior_own_approval_outcomes
    for previous in outcomes:
        if previous['organization_id']!=reading.organization_id or previous['tick']>=context.business_time.offset:
            raise ValueError('Monthly regulatory analysis substitutes own actual approval history')
    rectifications=sum(p.get('native_outcome')=='rectification_required' for p in outcomes)
    if (decimal_fraction(demand.value)>=decimal_fraction(threshold.value) or rectifications>0) and counts['adjust_regulatory_focus']<policy.maximum_focus_operations:
        operation='adjust_regulatory_focus'
    elif counts['monitor_compliance']==0:operation='monitor_compliance'
    elif counts['publish_guidelines']<policy.maximum_guidance_operations:operation='publish_guidelines'
    else:operation='review_policy_feedback'
    interpretation=(f'Original monthly analysis: demand={demand.value}, threshold={threshold.value}; '
        f'own prior operations={counts}; authenticated own prior approval outcomes={len(outcomes)}, '
        f'actual rectification outcomes={rectifications}. Selected {operation}. '
        'Signals are limited to this current macro input and own authenticated outcomes; missing physical inspection, '
        'safety, procurement and formal compliance evidence remains unknown.')
    guidance=None
    if operation=='publish_guidelines':
        guidance='Monthly guidance prepared from own monitored signals: '+'; '.join(policy.guidance_principles)+'. '+interpretation
    return GovMonthlyJudgment(operation=operation,market_demand=demand,threshold=threshold,
        own_prior_operation_counts=counts,prior_own_approval_count=len(outcomes),prior_actual_rectification_count=rectifications,
        interpretation=interpretation,guidance=guidance,evidence_refs=list({r.key():r for r in refs}.values()))
