"""Interpret the original A05 cash calculation and actual earlier own review."""
from decimal import Decimal
from fractions import Fraction
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_monthly_capacity import MonthlyOwnerCapacityObservation,MonthlyOwnerCapacityJudgment
from src.methods.pricing import exact_decimal
from src.coordination.tasks import task_digest


def review_monthly_capacity(context,reading,*,profile,choice,cash_input,cash_report):
    observation=reading.resolve(profile.monthly_capacity_observation_ref)
    if (not isinstance(observation,MonthlyOwnerCapacityObservation) or observation.organization_id!=reading.organization_id
            or observation.scope!=context.scope or observation.as_of!=context.business_time
            or context.scope.kind!='organization' or context.scope.ref.id!=reading.organization_id
            or profile.borrower_id!=reading.organization_id or profile.policy.state!='known' or profile.policy.value!='own_funds'
            or profile.coverage!='complete' or choice not in {'own_funds','no_finance'} or len(cash_input.accounts)!=1
            or len(profile.source_refs)!=1 or len({r.source_ref.key() for r in cash_report.checkpoints})!=1):
        raise ValueError('Monthly capacity requires its exact complete single-account own portfolio and original cash calculation')
    if cash_report.feasible!=(choice=='own_funds'):raise ValueError('Review contradicts the original financing choice')
    for ref in observation.evidence_refs:
        evidence=reading.resolve(ref)
        if not isinstance(evidence,EvidenceRecord) or evidence.basis_kind!='observed' or (evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise ValueError('Monthly review requires actual current native evidence')
    for measure in (observation.actual_financing_index,observation.independent_watch_threshold):
        reading.resolve(measure.basis_ref)
        if measure.unit!='index' or not Decimal(measure.value).is_finite() or Decimal(measure.value)<0:raise ValueError('Environment signal must retain its dimensionless index')
    minimum=min(Fraction(p.available.numerator,p.available.denominator) for p in cash_report.checkpoints)
    environment=Decimal(observation.actual_financing_index.value)<Decimal(observation.independent_watch_threshold.value)
    history=observation.prior_own_reviews;prior=[]
    if len({h['event_id'] for h in history})!=len(history):raise ValueError('Monthly review repeats actual feedback')
    for h in history:
        if (h['micro_identity']['organization_id']!=reading.organization_id or h['micro_identity']['action_id']!='OWN-A05'
                or h['operation']!='review_financing_capacity' or h['participated'] is not True or not 0<h['tick']<context.business_time.offset
                or h['review_sha256']!=task_digest(h['review'])):
            raise ValueError('Monthly review borrows foreign, future or changed actual feedback')
        judgment=MonthlyOwnerCapacityJudgment.model_validate(h['review'])
        if judgment.currency!=profile.currency or judgment.independent_watch_threshold!=observation.independent_watch_threshold:
            raise ValueError('Monthly review changes its comparable currency or independent risk rule')
        prior.append((h['tick'],judgment))
    previous=max(prior,key=lambda x:x[0])[1] if prior else None
    delta=None if previous is None else minimum-Fraction(Decimal(previous.minimum_available))
    watch=not cash_report.feasible or environment or (delta is not None and delta<0)
    transition=('initial_watch' if watch else 'initial_clear') if previous is None else ('watch_continues' if previous.financing_watch else 'watch_started') if watch else ('watch_resolved' if previous.financing_watch else 'clear_continues')
    interpretation='Review only: original cash calendar '+('covers' if cash_report.feasible else 'does not cover')+' the declared plan and all supplied existing obligations. Environment index is a risk signal, never cash, credit or a financial receipt. Monitoring transition: '+transition+'.'
    reading.recheck()
    return MonthlyOwnerCapacityJudgment(original_choice=choice,cash_feasible=cash_report.feasible,currency=profile.currency,minimum_available=exact_decimal(minimum),
        actual_financing_index=observation.actual_financing_index,independent_watch_threshold=observation.independent_watch_threshold,environment_watch=environment,financing_watch=watch,
        prior_review_count=len(history),previous_minimum_available=None if previous is None else previous.minimum_available,
        change_in_minimum_available=None if delta is None else exact_decimal(delta),previous_environment_index=None if previous is None else previous.actual_financing_index.value,
        change_in_environment_index=None if previous is None else str(Decimal(observation.actual_financing_index.value)-Decimal(previous.actual_financing_index.value)),
        monitoring_transition=transition,consumed_event_ids=[h['event_id'] for h in history],consumed_review_sha256=[h['review_sha256'] for h in history],interpretation=interpretation)
