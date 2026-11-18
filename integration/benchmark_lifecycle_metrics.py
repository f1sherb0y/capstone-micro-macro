"""Role-specific historical hits from actual native evaluation/award events."""
from math import comb


CONTRACTOR_ROLES = {'施工/总承包', '专业分包'}


def contractor_truth(rows, role=None):
    roles = CONTRACTOR_ROLES if role is None else {role}
    if not roles <= CONTRACTOR_ROLES:
        raise ValueError('Unsupported contractor benchmark role')
    return sorted({r['company_id'] for r in rows
        if r['company_role_original'] in roles and r['company_id']})


def score_case(result, case_id, truth, *, candidate_stages=None):
    projects = result['simulation']['project_results']
    project, = [p for p in projects if p['project_id'] == case_id]
    events = project['event_log']
    evaluations = [e for e in events if e['event_type'] == 'bid_evaluation_completed']
    if len(evaluations) != 1:
        raise ValueError('Exactly one actual evaluation event required')
    event = evaluations[0]
    data = event['data']
    ranking = [r['contractor_id'] for r in data['ranked_bids']]
    n = data['valid_bid_count']
    if not ranking or len(ranking) != n or len(set(ranking)) != n:
        raise ValueError('Incomplete/duplicate actual ranking; do not infer or fill missing ranks')
    awards = [e for e in events if e['event_type'] == 'contract_awarded']
    settlements = [e for e in events if e['event_type'] == 'final_account_settled']
    truth = set(truth)
    present = truth.intersection(ranking)
    scored = {'case_id': case_id, 'role': 'contractor', 'benchmark_company_ids': sorted(truth),
        'evaluation_event_id': event['event_id'], 'evaluation_tick': event['tick'],
        'ranked_company_ids': ranking, 'valid_bid_count': n,
        'candidate_benchmark_covered': bool(present),
        'benchmark_relation_coverage': len(present) / len(truth) if truth else None,
        'awarded_company_ids': [e['data']['contractor_id'] for e in awards],
        'award_hit': any(e['data']['contractor_id'] in truth for e in awards) if truth else None,
        'award_event_ids': [e['event_id'] for e in awards],
        'settlement_event_ids': [e['event_id'] for e in settlements],
        'closed': project['current_stage'] == 'closed',
        'completed': result['simulation']['status'] == 'completed'}
    for k in (1, 3, 5):
        take = min(k, n)
        scored[f'top{k}'] = bool(truth.intersection(ranking[:take])) if truth else None
        scored[f'top{k}_effective_k'] = take
        scored[f'top{k}_saturated'] = k >= n
        scored[f'top{k}_random_baseline'] = (1 - comb(n - len(present), take) / comb(n, take)) if truth else None
        scored[f'top{k}_precision'] = len(truth.intersection(ranking[:take])) / take if truth else None
        scored[f'top{k}_recall'] = len(truth.intersection(ranking[:take])) / len(truth) if truth else None
    scored['reciprocal_rank'] = next((1 / (i + 1) for i, company in enumerate(ranking) if company in truth), 0) if truth else None
    owner_scores = [r.get('owner_selection_score') for r in data['ranked_bids']]
    scored['top_score_tie_count'] = sum(value == owner_scores[0] for value in owner_scores) if all(v is not None for v in owner_scores) else None
    scored['historical_consistency_only'] = True
    if candidate_stages is not None:
        stages = {key: set(candidate_stages[key]) for key in ('source', 'retrieved', 'active')}
        if not stages['active'] <= stages['retrieved'] <= stages['source'] or not set(ranking) <= stages['active']:
            raise ValueError('Candidate stages must preserve actual source/retrieval/active/ranking membership')
        scored['coverage_stages'] = {key: {'count': len(ids), 'historical_covered': bool(ids & truth) if truth else None,
            'historical_recall': len(ids & truth) / len(truth) if truth else None} for key, ids in
            {**stages, 'valid_bids': set(ranking)}.items()}
        scored['miss_stage'] = next((key for key, ids in stages.items() if truth and not ids & truth),
            'valid_bids' if truth and not present else 'ranking_or_award' if truth and not scored['award_hit'] else None)
    return scored


def aggregate(scores, total, supported):
    eligible = [s for s in scores if s['benchmark_company_ids']]
    covered = [s for s in eligible if s['candidate_benchmark_covered']]
    summary = {'inventory_cases': total, 'currently_supported_cases': supported,
        'completed_scored_cases': len(scores), 'contractor_benchmark_denominator': len(eligible),
        'candidate_covered_cases': len(covered),
        'candidate_coverage': len(covered) / len(eligible) if eligible else None,
        'note': 'Model chooses pricing options only. Hits evaluate the integrated model-and-rule chain, not all-LLM decisions or real-world validation.'}
    for k in (1, 3, 5):
        hits = sum(s[f'top{k}'] for s in eligible)
        summary[f'top{k}'] = {'hits': hits, 'denominator': len(eligible),
            'rate': hits / len(eligible) if eligible else None,
            'conditional_on_covered': sum(s[f'top{k}'] for s in covered) / len(covered) if covered else None,
            'saturated_cases': sum(s[f'top{k}_saturated'] for s in eligible),
            'mean_random_baseline': sum(s[f'top{k}_random_baseline'] for s in eligible) / len(eligible) if eligible else None}
    summary['award_historical_consistency'] = {'hits': sum(s['award_hit'] for s in eligible),
        'denominator': len(eligible), 'rate': sum(s['award_hit'] for s in eligible) / len(eligible) if eligible else None}
    staged = [s for s in eligible if 'coverage_stages' in s]
    if staged:
        summary['coverage_stages'] = {key: {'covered_cases': sum(s['coverage_stages'][key]['historical_covered'] for s in staged),
            'denominator': len(staged), 'rate': sum(s['coverage_stages'][key]['historical_covered'] for s in staged) / len(staged)}
            for key in ('source', 'retrieved', 'active', 'valid_bids')}
        summary['ranking_diagnostics'] = {'mean_reciprocal_rank': sum(s['reciprocal_rank'] for s in staged) / len(staged),
            'top_score_tied_cases': sum((s['top_score_tie_count'] or 0) > 1 for s in staged),
            'denominator': len(staged)}
    return summary
