"""Match exact (project, historical role, company) triples.

A project succeeds at K when at least one labelled role has an exact company
match within that role's first K predictions. Role-type presence alone never
counts as a match. Unknown labels are excluded, not treated as negatives.
"""
from collections import defaultdict


def score_roles(predictions, labels, *, ks=(1, 3, 5, 12)):
    if not ks or any(type(k) is not int or k < 1 for k in ks) or len(set(ks)) != len(ks):
        raise ValueError('Declare distinct positive K values')
    predicted = {}
    for row in predictions:
        key = (row['case_id'], row['role'])
        ranking = row['ranked_company_ids']
        if key in predicted or len(set(ranking)) != len(ranking):
            raise ValueError('Duplicate project-role query or company ranking')
        predicted[key] = list(ranking)
    truth = defaultdict(set)
    for row in labels:
        if row.get('case_id') and row.get('company_role_original') and row.get('company_id'):
            truth[(row['case_id'], row['company_role_original'])].add(row['company_id'])
    projects = sorted({case for case, _ in truth})
    pairs = []
    for (case, role), targets in sorted(truth.items()):
        ranking = predicted.get((case, role), [])
        pairs.append({'case_id': case, 'role': role, 'historical_company_ids': sorted(targets),
            'query_present': (case, role) in predicted, 'prediction_count': len(ranking),
            'matched_company_ids_at_k': {str(k): sorted(targets & set(ranking[:k])) for k in ks},
            'hit_at_k': {str(k): bool(targets & set(ranking[:k])) for k in ks}})
    per_project = []
    for case in projects:
        rows = [row for row in pairs if row['case_id'] == case]
        per_project.append({'case_id': case, 'labelled_role_count': len(rows),
            'queried_labelled_roles': sum(row['query_present'] for row in rows),
            'matched_roles_at_k': {str(k): [row['role'] for row in rows if row['hit_at_k'][str(k)]] for k in ks},
            'any_role_hit_at_k': {str(k): any(row['hit_at_k'][str(k)] for row in rows) for k in ks}})
    role_summary = []
    for role in sorted({row['role'] for row in pairs}):
        rows = [row for row in pairs if row['role'] == role]
        role_summary.append({'role': role, 'denominator': len(rows), 'unqueried_pairs': sum(not row['query_present'] for row in rows),
            'hits_at_k': {str(k): sum(row['hit_at_k'][str(k)] for row in rows) for k in ks}})
    return {'definition': 'Exact company_id in the same project and historical role; at least one role suffices per project.',
        'k_values': list(ks), 'eligible_projects': len(projects), 'eligible_project_role_pairs': len(pairs),
        'project_any_role': {str(k): {'hits': sum(row['any_role_hit_at_k'][str(k)] for row in per_project),
            'denominator': len(projects), 'rate': sum(row['any_role_hit_at_k'][str(k)] for row in per_project) / len(projects) if projects else None} for k in ks},
        'role_pair_hits': {str(k): {'hits': sum(row['hit_at_k'][str(k)] for row in pairs),
            'denominator': len(pairs)} for k in ks},
        'per_role': role_summary, 'projects': per_project, 'project_roles': pairs}
