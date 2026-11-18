"""Bind actual monthly sources and read the original GOV-A12 interpretation."""
from src.actions.contracts.government_monthly_objects import GovMonthlyJudgment
from src.coordination.tasks import TaskConflict


def result_judgment(saved):
    profiles=[r['projection'] for r in saved['source_reading'] if r['ref']['kind']=='ObservationProfile']
    if len(profiles)!=1:raise TaskConflict('Monthly result lacks its exact original observation profile')
    if profiles[0].get('monthly_policy_ref') is None:return None
    return GovMonthlyJudgment.model_validate_json(saved['result']['payload']['interpretation'])


def result_operation(saved):
    judgment=result_judgment(saved)
    return 'review_policy_feedback' if judgment is None else judgment.operation


def bind_observation(plan,objects,observed):
    profile,=[r['value'] for r in objects if r['ref']==plan.feedback.action_input['observation_profile_ref']]
    if profile.get('monthly_policy_ref') is None:return
    row,=[r['value'] for r in objects if r['ref']==profile['monthly_observation_ref']]
    if any(row[k] is not None for k in ('market_demand','prior_own_operations','prior_own_approval_outcomes')):
        raise TaskConflict('Monthly regulatory sources must remain originally unbound, never a prefilled decision')
    row.update(market_demand={'value':str(observed['macro_environment']['market_demand_index']), 'unit':'index',
        'basis_ref':plan.feedback.native_evidence_ref.model_dump(mode='json')},
        prior_own_operations=observed['prior_monthly_feedback'],prior_own_approval_outcomes=observed['prior_approval_decisions'])
