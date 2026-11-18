"""Declare original QS record-only feedback before native settlement occurs."""
from copy import deepcopy

from integration.native_lifecycle_actions import NativeLifecyclePlan
from integration.professional_feedback_development import feedback_plan


def add_settlement_learning(*, snapshot, document):
    """Extend initial authority, never a registered runtime grant or formal state.

    Only the actual future settlement binds the unbound feedback. The earlier
    original QS review is a private prerequisite, not an agreed final account.
    """
    snapshot, document = deepcopy(snapshot), deepcopy(document)
    reviews = [p for p in document['plans'] if p['context']['contract_ref']['id'] == 'QS-A09'
               and p['event_type'] == 'final_account_review_started']
    if len(reviews) != 1:
        raise ValueError('Settlement learning requires one explicitly declared original QS review')
    review, = reviews
    grant, = [g for g in snapshot['authorizations'] if g['ref'] in review['context']['authorization_refs']]
    intake = deepcopy(review)
    intake['role'] = 'QS'
    intake['tick'] += 1
    intake['context']['business_time']['offset'] = intake['tick']
    plan = feedback_plan(intake, grant=grant, event_type='final_account_settled')
    dependency = {'kind': 'Evidence', 'id': plan['plan_id'] + '-original-review', 'version': '1'}
    plan['depends_on'] = [review['plan_id']]
    plan['dependency_evidence_ref'] = dependency
    plan['objects'].append({'ref': dependency, 'value': {
        'ref': dependency, 'source_kind': 'synthetic', 'basis_kind': 'observed',
        'locator': 'original-own-QS-A09-saved-result', 'content_hash': None,
        'effective_window': deepcopy(grant['validity'])}})
    plan['context']['visible_refs'].append(dependency)
    grant['readable_refs'].append(dependency)
    document['plans'].append(plan)
    # Every initial projection must expose the same original initial grant.
    for row in document['plans']:
        for source in row['objects']:
            if source['ref'] == grant['ref']:
                source['value'] = deepcopy(grant)
    document['plans'][-1] = NativeLifecyclePlan.model_validate(plan).model_dump(mode='json')
    return snapshot, document
