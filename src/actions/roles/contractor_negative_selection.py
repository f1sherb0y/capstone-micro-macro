"""Bounded A05 wait judgment; does not issue an inquiry or create an order."""
from src.actions.contracts.contractor_negative_selection import NativeSupplySelectionObservation
from src.actions.contracts.common import EvidenceRecord
from src.coordination.tasks import task_digest


WAIT = 'contractor-plan-no-accepted-native-supplier'
REPEATED_WAIT = 'contractor-plan-repeated-no-accepted-native-supplier'
WAIT_CODES = {WAIT, REPEATED_WAIT}


def judge_negative_selection(context, reading, *, profile, organization_id):
    observation = reading.resolve(profile.negative_selection_observation_ref)
    if (not isinstance(observation, NativeSupplySelectionObservation)
            or observation.organization_id != organization_id or observation.scope != context.scope
            or observation.project_id != context.scope.ref.id or observation.tick != context.business_time.offset
            or observation.available_at != context.business_time
            or profile.choice != 'accept_supply_offer' or profile.selected_offer_ref is not None
            or profile.procurement_authority_ref is not None or profile.monthly_supplier_policy_ref is not None
            or profile.monthly_supplier_observation_ref is not None):
        raise ValueError('Negative selection changes actual buyer, scope, clock or planning mode')
    for ref in observation.evidence_refs:
        evidence = reading.resolve(ref)
        if not isinstance(evidence, EvidenceRecord) or not evidence.effective_window.contains(context.business_time):
            raise ValueError('Negative selection requires current actual source evidence')
    seen = set()
    for event in observation.supplier_decisions:
        if (event.get('event_type') != 'supplier_order_decision' or event.get('project_id') != observation.project_id
                or event.get('tick') != observation.tick or event.get('agent_id') in seen
                or event['data'].get('accepted') is not False
                or not event['data'].get('micro_result_sha256')):
            raise ValueError('Negative selection requires distinct actual current supplier refusals')
        seen.add(event['agent_id'])
    history = observation.prior_failures
    if len({h['event']['event_id'] for h in history}) != len(history):
        raise ValueError('Negative selection repeats an earlier failure')
    for h in history:
        event = h['event']
        if (event.get('event_type') != 'supplier_selection_failed' or event.get('agent_id') != organization_id
                or not 0 < event['tick'] < observation.tick or task_digest(event) != h['event_sha256']
                or event['data']['contractor_decision'].get('accepted') is not False):
            raise ValueError('Negative selection borrows another buyer or unconfirmed/future failure')
    reading.recheck()
    # An earlier actual failure changes the dependency condition; it does not
    # make an unavailable supplier eligible or authorize a fictitious inquiry.
    code = REPEATED_WAIT if history else WAIT
    return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
        'trigger': 'dependency_change', 'object_refs': [observation.ref],
        'earliest_time': None, 'condition_code': code}}
