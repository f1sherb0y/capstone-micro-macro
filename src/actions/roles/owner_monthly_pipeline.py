"""Reuse original A03 results; decide whether to review their actual current set."""
from decimal import Decimal
from src.actions.contracts.owner_monthly_pipeline import OwnerPipelinePolicy, OwnerPipelineJudgment
from src.coordination.tasks import TaskConflict, task_digest


def decide_pipeline_review(policy, *, organization_id, tick, market_demand, candidates, history):
    policy = OwnerPipelinePolicy.model_validate(policy)
    if (policy.organization_id != organization_id or type(tick) is not int or tick not in policy.authorized_ticks
            or policy.purpose != 'review_received_native_candidates_only' or not candidates):
        raise TaskConflict('Pipeline review requires its authorized current own received candidate set')
    demand, minimum = Decimal(str(market_demand)), Decimal(policy.minimum_market_demand)
    if not demand.is_finite() or not minimum.is_finite() or minimum < 0:
        raise TaskConflict('Pipeline demand gate requires finite original index and independent threshold')
    keys = [r['micro_task_key'] for r in candidates]
    scopes = [task_digest(r['scope']) for r in candidates]
    if (len(set(keys)) != len(keys) or len(set(scopes)) != len(scopes)
            or any(r['scope']['owner_id'] != organization_id or r['scope']['tick'] != tick
                or r['choice'] not in {'invest', 'reject', 'authorize_preparation'} for r in candidates)):
        raise TaskConflict('Pipeline review substitutes, duplicates or defers an original candidate result')
    ids = [h['event_id'] for h in history]
    if (len(set(ids)) != len(ids) or any(h['organization_id'] != organization_id or not 0 < h['tick'] < tick
            or h['operation'] != 'screen_investment_pipeline' for h in history)):
        raise TaskConflict('Pipeline review borrows foreign, future or unrelated native feedback')
    participate = demand >= minimum
    return OwnerPipelineJudgment(organization_id=organization_id, tick=tick, participate=participate,
        reason_code='current_received_candidates_reviewed' if participate else 'market_demand_below_review_threshold',
        market_demand=str(demand), minimum_market_demand=str(minimum), candidate_count=len(candidates),
        prior_completed_screens=len(history), candidate_source_sha256=task_digest(candidates), candidate_task_keys=keys,
        investment_recommendations=[r['scope']['candidate_project_id'] for r in candidates if r['choice']=='invest'],
        consumed_event_ids=ids)
