"""QS-A12 records a bounded, sourced future estimate sensitivity judgment."""
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.qs_monthly_estimation import (
    MonthlyEstimationPolicy, MonthlyEstimationObservation, MonthlyEstimationJudgment,
)
from src.coordination.tasks import task_digest


def evaluate(policy, observation, *, organization_id, scope, now):
    if (policy.organization_id!=organization_id or observation.organization_id!=organization_id
            or policy.scope!=scope or observation.scope!=scope or observation.as_of!=now
            or not policy.effective_window.contains(now)):
        raise ValueError('Estimation review changes current own scope or clock')
    def number(value,unit,*,positive=False):
        result=Decimal(value.value)
        if not result.is_finite() or value.unit!=unit or result<0 or positive and result==0:
            raise ValueError('Estimation review requires finite explicit positive indices and units')
        return result
    current=number(observation.material_index,'index',positive=True)
    baseline=number(policy.baseline_material_index,'index',positive=True)
    free=number(observation.native_free_ratio,'ratio')
    minimum=number(policy.minimum_relative_change,'ratio')
    free_limit=number(policy.minimum_free_ratio,'ratio')
    if free>1 or free_limit>1 or minimum>1:raise ValueError('Invalid bounded resource/change rule')
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(
            h['micro_identity']['organization_id']!=organization_id or h['micro_identity']['action_id']!='QS-A12'
            or h['micro_identity']['role']!='QS' or not 0<h['tick']<now.offset
            or h['operation']!=('improve_cost_estimation' if h['participated'] else 'maintain_operations')
            or h['review_sha256']!=task_digest(h['review']) for h in history):
        raise ValueError('Estimation history changes own actually executed earlier result')
    accepted=baseline;factor=Decimal(1);count=0
    for h in sorted(history,key=lambda x:x['tick']):
        prior=MonthlyEstimationJudgment.model_validate(h['review'])
        if prior.participate!=h['participated']:raise ValueError('Estimation feedback changes native participation')
        if h['participated']:
            accepted=Decimal(prior.material_index.value);factor=Decimal(prior.proposed_material_factor);count+=1
            if accepted<=0 or factor!=accepted/baseline:raise ValueError('Invalid actually accepted private index assumption')
    projects=observation.own_project_evidence
    if not projects or len({p['project_id'] for p in projects})!=len(projects):
        raise ValueError('Estimation review requires unique actual own project evidence')
    for p in projects:
        if (p['project_id'] not in policy.authorized_project_ids or p['selected_qs_id']!=organization_id
                or p['tick']!=now.offset or p['unit']!='native_model_cost_unit'
                or p['native_event']['event_type']!='project_state_updated'
                or p['native_event']['tick']!=now.offset or p['native_event']['project_id']!=p['project_id']
                or p['native_event_sha256']!=task_digest(p['native_event'])
                or str(p['native_event']['data']['planned_cost'])!=p['reference_estimate']):
            raise ValueError('Estimation substitutes project, future evidence, units or original planned estimate')
        amount=Decimal(p['reference_estimate'])
        if not amount.is_finite() or amount<=0:raise ValueError('Estimation requires a positive original reference estimate')
    delta=(current-accepted)/accepted
    participate=abs(delta)>=minimum and free>=free_limit and count<policy.maximum_updates
    proposed=current/baseline
    applied=proposed if participate else factor
    estimates=[{'project_id':p['project_id'],'native_event_id':p['native_event']['event_id'],
        'reference_estimate':p['reference_estimate'],'unit':p['unit'],
        'previously_accepted_factor':str(factor),'estimate_using_previous_factor':str(Decimal(p['reference_estimate'])*factor),
        'applied_factor':str(applied),'indicative_estimate':str(Decimal(p['reference_estimate'])*applied)} for p in projects]
    return MonthlyEstimationJudgment(participate=participate,material_index=observation.material_index,
        native_free_ratio=observation.native_free_ratio,accepted_material_index=str(accepted),relative_index_change=str(delta),
        proposed_material_factor=str(proposed),applied_material_factor=str(applied),indicative_estimates=estimates,
        prior_actual_update_count=count,consumed_event_ids=[h['event_id'] for h in history],
        interpretation='Review a private future index sensitivity assumption against original own planned-cost evidence; '
            + ('propose a monthly method update.' if participate else 'retain the actually accepted assumption after consuming prior native feedback.'))


def analyze_monthly_estimation(context,action_input,reading,*,decision,state,capability):
    if decision.monthly_estimation_policy_ref is None or decision.monthly_estimation_observation_ref is None:
        raise ValueError('Monthly estimation requires both independent policy and actual observation')
    policy=reading.resolve(decision.monthly_estimation_policy_ref)
    observation=reading.resolve(decision.monthly_estimation_observation_ref)
    if not isinstance(policy,MonthlyEstimationPolicy) or not isinstance(observation,MonthlyEstimationObservation):
        raise ValueError('Monthly estimation requires original typed sources')
    if (decision.choice!='record_feedback' or state.coverage!='unknown' or capability.status!='unknown'
            or decision.authority_ref!=policy.authority_ref or policy.authority_ref not in context.authorization_refs
            or decision.monthly_method_policy_ref is not None or decision.monthly_method_observation_ref is not None
            or decision.feedback_refs or decision.forecast_ref is not None or decision.outcome_ref is not None
            or decision.error_result_ref is not None or decision.assessment_ref is not None or decision.training_profile_ref is not None
            or state.learning_profile_ref is not None
            or action_input.learning_profile_ref is not None or action_input.feedback_refs
            or action_input.forecast_refs or action_input.outcome_refs or action_input.comparability_result_ref is not None
            or state.forecast_refs or state.outcome_refs or state.applied_error_pair_keys
            or state.received_feedback_refs or state.applied_feedback_refs or state.execution_refs
            or capability.verified_capability_codes or capability.qualification_refs):
        raise ValueError('Monthly index review cannot assert detailed forecast-error learning, qualifications or training')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or source.effective_window is not None and not source.effective_window.contains(context.business_time):
            raise ValueError('Estimation review lacks current original evidence')
    for measure in [policy.baseline_material_index,policy.minimum_relative_change,policy.minimum_free_ratio,
            observation.material_index,observation.native_free_ratio]:
        reading.resolve(measure.basis_ref)
    judgment=evaluate(policy,observation,organization_id=reading.organization_id,scope=context.scope,now=context.business_time)
    reading.recheck()
    return judgment.model_dump_json()
