"""Tighten an explicitly configured private policy using actual own refusals."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def screening_decline_feedback(app, *, plan, objects, history):
    threshold = plan.decline_after_prior_declines
    if threshold is None:
        return None
    if (plan.tick != app.assembly.engine.current_tick
            or len({r['event_id'] for r in history}) != len(history)
            or len({r['micro_task_key'] for r in history}) != len(history)):
        raise TaskConflict('Supplier screening feedback changes its current clock or repeats original outcomes')
    step = plan.quote.product.screening
    records = {TaskIdentity(**r['identity']).key: r for r in app._records()
        if r['state'] == 'formed' and 'identity' in r}
    workers = {'screening': app.screening_worker, 'product': app.product_worker,
        'quote': app.quote_worker, 'order': app.worker}
    for origin in history:
        record = records.get(origin['micro_task_key'])
        if (record is None or origin['organization_id'] != plan.organization_id
                or origin['tick'] >= plan.tick or record['scope']['project_id'] != origin['project_id']
                or record['scope']['tick'] != origin['tick']
                or record['result_sha256'] != origin['micro_result_sha256']):
            raise TaskConflict('Supplier screening feedback lost its own earlier original workflow')
        identity = TaskIdentity(**record['identity'])
        stage = record['terminal_stage']
        earlier = [p for p in app.plans if (p.organization_id, p.project_id, p.tick) ==
            (plan.organization_id, origin['project_id'], origin['tick'])]
        if len(earlier) != 1 or identity.organization_id != plan.organization_id:
            raise TaskConflict('Supplier screening feedback substitutes its original source plan')
        saved = checked_result(workers[stage], identity)
        app._authorize_step(earlier[0], stage, source_reading=saved['source_reading'])
        accepted, _ = app._summary(saved['result'],stage)
        if (saved['result_sha256'] != origin['micro_result_sha256']
                or identity.action_id != origin['micro_action_id']
                or saved['result']['payload']['choice'] != origin['micro_choice']
                or origin['accepted'] is not accepted
                or origin['proposal_response_sha256'] != record['proposal_response_sha256']):
            raise TaskConflict('Supplier screening feedback changes its original deciding result')
    profile, = [r['value'] for r in objects if r['ref'] == step.action_input['screening_profile_ref']]
    evidence_ref = step.native_evidence_ref.model_dump(mode='json')
    if profile['organization_id'] != plan.organization_id or evidence_ref not in profile['evidence_refs']:
        raise TaskConflict('Supplier screening feedback lacks its original private policy evidence')
    baseline = profile['policy']
    declines = [row for row in history if row['accepted'] is False]
    if len(declines) >= threshold and baseline == 'evaluate':
        profile['policy'] = 'decline_new_work'
    return {'source': 'strictly_earlier_own_actual_supply_decisions', 'threshold': threshold,
        'actual_decline_count': len(declines), 'history_sha256': task_digest(history),
        'declines': deepcopy(declines), 'baseline_policy': baseline, 'effective_policy': profile['policy']}
