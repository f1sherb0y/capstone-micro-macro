"""Bounded feedback from actual aggregate events, without work/certificate effects."""
from decimal import Decimal
from src.coordination.tasks import task_digest

EVENT_TYPES = {'construction_progress_updated', 'inspection_passed', 'inspection_failed',
    'variation_requested', 'variation_resolved', 'safety_issue'}


def review_construction(results, policy, *, organization_id, role, run_id, tick):
    groups = {}; seen = set()
    field = {'Architect': 'selected_architect_id', 'Engineer': 'selected_engineer_id'}[role]
    for result in results:
        event = result.event; assignment = result.initial_assignment
        if (result.run_id != run_id or event.get('event_id') in seen
                or event.get('event_type') not in EVENT_TYPES
                or event.get('project_id') != result.project_id
                or not 0 < event.get('tick', tick) < tick
                or task_digest(event) != result.event_sha256
                or task_digest(assignment) != result.initial_assignment_sha256
                or assignment.get('project_id') != result.project_id
                or assignment.get(field) != organization_id
                or not any(e.get('agent_id') == organization_id and e.get('role') == role
                    for e in assignment.get('engagements', []))):
            raise ValueError('Construction feedback changes actual earlier event, own initial assignment or run')
        seen.add(event['event_id']); groups.setdefault(result.project_id, []).append(result)
    reviews = []
    for project_id, rows in sorted(groups.items()):
        rows.sort(key=lambda r: (r.event['tick'], r.event['event_id']))
        progress = [r for r in rows if r.event['event_type'] == 'construction_progress_updated']
        inspections = [r for r in rows if r.event['event_type'].startswith('inspection_')]
        variations = [r for r in rows if r.event['event_type'].startswith('variation_')]
        safety = [r for r in rows if r.event['event_type'] == 'safety_issue']
        delay_excess = shortfall_excess = Decimal(0)
        if progress:
            data = progress[-1].event['data']
            delay = Decimal(str(data['delay_days'])); deviation = Decimal(str(data['progress_deviation']))
            if delay < 0 or not -1 <= deviation <= 1:
                raise ValueError('Native progress feedback requires bounded progress and nonnegative delay')
            delay_excess = max(Decimal(0), delay - Decimal(str(policy.maximum_delay_days)))
            shortfall_excess = max(Decimal(0), -deviation - Decimal(str(policy.maximum_progress_shortfall)))
        quality_review = bool(inspections and inspections[-1].event['event_type'] == 'inspection_failed')
        for inspection in inspections:
            data = inspection.event['data']
            expected = 'passed' if inspection.event['event_type'] == 'inspection_passed' else 'rectification_required'
            if data.get('result') != expected or any(not 0 <= Decimal(str(data[k])) <= 1
                    for k in ('detected_defect_rate', 'safety_risk', 'compliance_risk')):
                raise ValueError('Inspection feedback differs from its native result or normalized risks')
        variation_open = bool(variations and variations[-1].event['event_type'] == 'variation_requested')
        safety_excess = Decimal(0)
        if safety:
            if policy.maximum_safety_risk is None:
                raise ValueError('Actual safety events require an independently declared safety review threshold')
            samples = [r for r in rows if r.event['event_type'] in {'safety_issue', 'inspection_passed', 'inspection_failed'}]
            for sample in samples:
                if not 0 <= Decimal(str(sample.event['data']['safety_risk'])) <= 1:
                    raise ValueError('Safety feedback requires an original bounded risk index')
            safety_excess = max(Decimal(0), Decimal(str(samples[-1].event['data']['safety_risk']))
                - Decimal(str(policy.maximum_safety_risk)))
        priority = ('site_safety_review' if safety_excess else 'quality_remedy_review' if quality_review else 'variation_coordination' if variation_open
            else 'progress_recovery' if delay_excess or shortfall_excess else 'no_aggregate_gap')
        review = {'project_id': project_id, 'priority': priority,
            'needs_review': priority != 'no_aggregate_gap', 'delay_excess_days': str(delay_excess),
            'progress_shortfall_excess': str(shortfall_excess), 'latest_inspection_failed': quality_review,
            'variation_open': variation_open, 'consumed_event_ids': [r.event['event_id'] for r in rows],
            'consumed_event_sha256': [r.event_sha256 for r in rows],
            'latest_progress_event_id': progress[-1].event['event_id'] if progress else None,
            'latest_inspection_event_id': inspections[-1].event['event_id'] if inspections else None,
            'latest_variation_event_id': variations[-1].event['event_id'] if variations else None,
            'formal_work_or_certificate_effect_applied': False}
        if policy.maximum_safety_risk is not None:
            review.update(safety_risk_excess=str(safety_excess),
                latest_safety_issue_event_id=safety[-1].event['event_id'] if safety else None)
        reviews.append(review)
    return reviews
