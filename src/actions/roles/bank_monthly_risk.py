"""BANK-A01 optional monthly risk analysis inside its original strategy decision."""
from decimal import Decimal

from src.actions.contracts.bank_monthly_risk_objects import (
    MonthlyBorrowerRiskJudgment, MonthlyBorrowerRiskObservation, MonthlyBorrowerRiskPolicy,
)
from src.actions.contracts.common import EvidenceRecord
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def monthly_risk_note(context, reading, space, *, choice, note):
    policy_ref, observation_ref = space.monthly_risk_policy_ref, space.monthly_risk_observation_ref
    if policy_ref is None and observation_ref is None:
        return note
    if policy_ref is None or observation_ref is None:
        raise ValueError('Monthly borrower monitoring requires both independently authorized policy and actual observations')
    policy, observation = reading.resolve(policy_ref), reading.resolve(observation_ref)
    if not isinstance(policy, MonthlyBorrowerRiskPolicy) or not isinstance(observation, MonthlyBorrowerRiskObservation):
        raise ValueError('Monthly borrower monitoring changes its original typed projections')
    grant = reading.resolve(policy.authority_ref)
    if (policy.organization_id != reading.organization_id or observation.organization_id != reading.organization_id
            or policy.scope != context.scope or observation.scope != context.scope
            or policy.authority_ref not in context.authorization_refs or not isinstance(grant, Authorization)
            or grant.organization_id != reading.organization_id or grant.actor_id != context.actor_id
            or grant.function_ref != context.function_ref or 'BANK-A01' not in grant.action_ids
            or not any(scope_covers(s, context.scope) for s in grant.scopes)
            or not grant.validity.contains(context.business_time) or not policy.effective_window.contains(context.business_time)
            or observation.as_of != context.business_time):
        raise ValueError('Monthly risk monitoring changes its current bank, authority, scope or clock')
    for ref in [*policy.evidence_refs, *observation.evidence_refs]:
        source = reading.resolve(ref)
        if not isinstance(source, EvidenceRecord) or (source.effective_window is not None and not source.effective_window.contains(context.business_time)):
            raise ValueError('Monthly risk monitoring lacks applicable original evidence')
    def number(measure, unit):
        reading.resolve(measure.basis_ref)
        if measure.unit != unit or Decimal(measure.value) < 0:
            raise ValueError('Monthly risk monitoring requires explicit nonnegative compatible units')
        return Decimal(measure.value)
    condition = number(observation.financing_condition, 'index')
    market_weight = number(policy.market_stress_weight, 'ratio')
    borrower_weight = number(policy.borrower_weakness_weight, 'ratio')
    threshold = number(policy.monitoring_threshold, 'ratio')
    if any(v > 1 for v in (market_weight, borrower_weight, threshold)):
        raise ValueError('Monthly risk weights and threshold must lie in [0,1]')
    stress = max(Decimal(0), Decimal(1)-condition)
    scores, identities = [], set()
    for case in observation.received_cases:
        key = (case['project_id'], case['borrower_id'], case['observed_tick'])
        if key in identities or case['organization_id'] != reading.organization_id or not 0 < case['observed_tick'] < context.business_time.offset:
            raise ValueError('Monthly risk monitoring repeats, borrows or backdates an original financing case')
        identities.add(key)
        project_risk = Decimal(str(case['original_inputs']['project_risk']))
        capacity = Decimal(str(case['original_inputs']['borrower_financial_capacity']))
        if not 0 <= project_risk <= 1 or not 0 <= capacity <= 1:
            raise ValueError('Received native risk estimates must be bounded')
        score = min(Decimal(1), project_risk + market_weight*stress + borrower_weight*(1-capacity))
        scores.append({'project_id':case['project_id'], 'borrower_id':case['borrower_id'], 'observed_tick':case['observed_tick'],
            'original_request_sha256':case['original_request_sha256'], 'project_risk':str(project_risk),
            'borrower_financial_capacity':str(capacity), 'risk_score':str(score),
            'selected_by_this_borrower':case['actual_own_selection'] is not None})
    history = observation.prior_own_operations
    if len({h['event_id'] for h in history}) != len(history) or any(h['organization_id'] != reading.organization_id
            or not 0 < h['tick'] < context.business_time.offset for h in history):
        raise ValueError('Monthly monitoring history must contain strictly earlier own actual operations')
    count = sum(h.get('operation')=='monitor_borrower_risk' for h in history)
    maximum = max((Decimal(s['risk_score']) for s in scores), default=None)
    monitor = maximum is not None and maximum >= threshold and count < policy.maximum_prior_monitoring
    operation = 'monitor_borrower_risk' if monitor else ('adjust_credit_terms' if choice=='revise_strategy' else 'review_credit_pipeline')
    interpretation = ('Review received borrower financing-case risk estimates under current financing stress; no verified default, loan balance, payment or covenant finding is inferred.'
        if monitor else 'Retain the original strategy operation after evaluating received case risk, current financing stress and the count of earlier actual monitoring operations.')
    judgment = MonthlyBorrowerRiskJudgment(operation=operation, original_strategy_choice=choice, original_strategy_note=note,
        financing_condition=observation.financing_condition, market_stress=str(stress), case_scores=scores,
        maximum_risk_score=None if maximum is None else str(maximum), prior_actual_monitoring_count=count,
        monitoring_threshold=policy.monitoring_threshold, monitored_case_count=len(scores) if monitor else 0, interpretation=interpretation)
    reading.recheck()
    return judgment.model_dump_json()
