"""Pure read-only T1--T8 observations; no model, simulation, or file writes.

The caller establishes the verified run endpoint. Only the project's original
event_log is used, preserving event order even when ticks are equal. These
functions expose chain observations; comparisons must still match endpoints,
apply the frozen project/family units, and disclose missing planned chains.
"""
from math import isfinite
from statistics import mean

RISKS = ('supply_delay_risk', 'safety_risk', 'claim_risk', 'dispute_risk')
QUALITY = ('overall_quality', 'design_quality', 'construction_quality', 'material_quality')
MILESTONES = ('contract_awarded', 'project_completed', 'final_account_settled')
DISRUPTIONS = ('inspection_passed', 'inspection_failed', 'supply_delay', 'safety_issue')


def number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError('Finite explicitly observed number required')
    return float(value)


def ratio(numerator, denominator, *, deviation=False):
    numerator, denominator = number(numerator), number(denominator)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return (numerator - denominator if deviation else numerator) / denominator


def pricing_observation(bid_price, declared_cost_base, *, cost_source_ref=None,
                        semantic_strategy=None):
    """The base must be independently supplied; never invert a markup/price."""
    price, cost = number(bid_price), number(declared_cost_base)
    if cost is not None and not cost_source_ref:
        raise ValueError('An independently located declared cost base is required')
    return {'bid_price': price, 'declared_cost_base': cost, 'cost_source_ref': cost_source_ref,
        'markup_fraction': ratio(price, cost, deviation=True),
        'semantic_strategy': semantic_strategy,
        'semantic_strategy_state': 'explicitly_supplied' if semantic_strategy is not None else 'semantic_review_pending',
        'boundary': 'Declared pricing markup, not realized profit or a ranking of business merit.'}


def original_events(project, end_tick):
    log = project.get('event_log')
    if not isinstance(log, list):
        return None
    seen, events = {}, []
    for event in log:
        if event.get('project_id') != project['project_id']:
            continue
        eid = event.get('event_id')
        if not eid:
            raise ValueError('Cannot deduplicate a project event without an event_id')
        if eid in seen:
            if seen[eid] != event:
                raise ValueError('Conflicting copies of one event_id')
            continue
        tick = event.get('tick')
        if type(tick) is not int or tick > end_tick or (events and tick < events[-1]['tick']):
            raise ValueError('Event order/endpoint disagrees with the declared run')
        seen[eid] = event
        events.append(event)
    return events


def source(event):
    return None if event is None else {key: event[key] for key in ['event_id', 'tick', 'event_type', 'stage']}


def quality(data):
    return {field: number(data.get(field)) for field in QUALITY}


def cost_deviations(data, references):
    cost = number(data.get('actual_cost'))
    return {'actual_cost': cost, 'deviations': {
        name: ratio(cost, value, deviation=True) for name, value in references.items()}}


def progress_gap(data):
    actual, planned = number(data.get('actual_progress')), number(data.get('planned_progress'))
    return None if actual is None or planned is None else 100 * (actual - planned)


def extract_project_observations(project, *, end_tick, complete_horizon):
    if type(end_tick) is not int or end_tick < 0 or type(complete_horizon) is not bool:
        raise ValueError('Explicit verified endpoint and boolean completeness required')
    events = original_events(project, end_tick)
    available = events is not None
    events = events or []
    complete = complete_horizon and available
    indexed = list(enumerate(events))
    first_progress = next((i for i, e in indexed if e['event_type'] == 'construction_progress_updated'), None)
    states = [(i, e) for i, e in indexed if e['event_type'] == 'project_state_updated']
    after_progress = [(i, e) for i, e in states if first_progress is not None and i > first_progress]
    construction = [(i, e) for i, e in after_progress if e['stage'] == 'construction']
    milestone_events = {kind: [e for e in events if e['event_type'] == kind] for kind in MILESTONES}
    signed = milestone_events['contract_awarded']
    if len(signed) > 1:
        raise ValueError('Multiple distinct signed contracts require explicit analysis')
    contract = number(signed[0]['data'].get('contract_sum')) if signed else None
    if signed and project.get('contract_sum') is not None and number(project['contract_sum']) != contract:
        raise ValueError('Signed contract event and final project field disagree')
    references = {'initial_budget': number(project.get('initial_budget')),
        'reported_estimated_cost': number(project.get('estimated_cost')), 'signed_contract': contract}
    completed_index = next((i for i, e in indexed if e['event_type'] == 'project_completed'), None)
    before_completion = [(i, e) for i, e in after_progress if completed_index is not None and i < completed_index]
    completion_state = before_completion[-1][1] if before_completion else None
    # Final/default performance is usable only after an actual construction
    # update and a later saved state, at a verified common observation horizon.
    final_valid = bool(complete and after_progress)
    performance = project.get('performance', {})
    final = performance if final_valid else None
    completion = completion_state['data'] if completion_state is not None else None
    risk = {}
    for field in RISKS:
        observed = [(event, number(event['data'].get(field))) for _, event in construction]
        observed = [(event, value) for event, value in observed if value is not None]
        peak = max((value for _, value in observed), default=None)
        peak_event = next((event for event, value in observed if value == peak), None)
        risk[field] = {'construction_peak': peak,
            'first_peak_source': source(peak_event),
            'construction_observation_mean': mean(value for _, value in observed) if observed else None,
            'field_observation_count': len(observed),
            'fixed_horizon_state': number(final.get(field)) if final is not None else None,
            'observation_event_ids': [event['event_id'] for event, _ in observed]}
    raw_counts = {kind: sum(e['event_type'] == kind for e in events) for kind in DISRUPTIONS}
    comparison_exposure = complete and first_progress is not None
    inspections = raw_counts['inspection_passed'] + raw_counts['inspection_failed']
    stage_ticks = {kind: [e['tick'] for e in matches] for kind, matches in milestone_events.items()}
    return {'project_id': project['project_id'], 'reported_stage': project.get('current_stage'),
        'end_tick': end_tick, 'fixed_horizon_complete': complete,
        'original_project_event_log_available': available,
        'original_project_event_count_after_deduplication': len(events),
        'actual_construction_observed': first_progress is not None,
        'construction_update_count': sum(e['event_type'] == 'construction_progress_updated' for e in events),
        'valid_construction_state_count': len(construction),
        'valid_construction_first_tick': construction[0][1]['tick'] if construction else None,
        'valid_construction_last_tick': construction[-1][1]['tick'] if construction else None,
        'valid_construction_span_ticks': construction[-1][1]['tick'] - construction[0][1]['tick'] if construction else None,
        'T2': {'contract_sum': contract, 'initial_budget': references['initial_budget'],
            'contract_to_budget': ratio(contract, references['initial_budget']),
            'signed_contract_source': source(signed[0]) if signed else None},
        'T3': {'references': references,
            'fixed_horizon': cost_deviations(final, references) if final is not None else None,
            'completion': cost_deviations(completion, references) if completion is not None else None,
            'completion_state_source': source(completion_state)},
        'T4': {'fixed_horizon_progress_gap_pp': progress_gap(final) if final is not None else None,
            'completion_progress_gap_pp': progress_gap(completion) if completion is not None else None,
            'milestone_ticks': stage_ticks,
            'reported_delay_days': number(final.get('delay_days')) if final is not None else None,
            'trajectory': [{'source': source(e), 'valid_after_first_construction_update': first_progress is not None and i > first_progress,
                'progress_gap_pp': progress_gap(e['data'])} for i, e in states]},
        'T5': {'fixed_horizon': quality(final) if final is not None else None,
            'completion': quality(completion) if completion is not None else None,
            'completion_state_source': source(completion_state),
            'completion_event_sources': [source(e) for e in milestone_events['project_completed']]},
        'T6': risk,
        'T7': {'occurred_by_planned_endpoint': {
            kind: True if matches else False if complete else None for kind, matches in milestone_events.items()},
            'milestone_event_sources': {kind: [source(e) for e in matches] for kind, matches in milestone_events.items()}},
        'T8': {'raw_observed_counts': raw_counts if available else None,
            'comparative_counts': raw_counts if comparison_exposure else None,
            'inspection_failure_fraction': ratio(raw_counts['inspection_failed'], inspections) if comparison_exposure else None,
            'inspection_count': inspections if comparison_exposure else None,
            'exposure_eligible': comparison_exposure,
            'event_ids_by_type': {kind: [e['event_id'] for e in events if e['event_type'] == kind] for kind in DISRUPTIONS}},
        'missing_reasons': ([] if available else ['missing_original_project_event_log'])
            + ([] if complete else ['fixed_observation_horizon_not_verified_complete'])
            + ([] if first_progress is not None else ['no_substantive_construction_update'])
            + ([] if completion_state is not None else ['no_saved_post_progress_state_before_completion']),
        'boundary': 'Model-internal observations, not calibrated real-project predictions. No default quality/zero exposure is treated as improvement; price is not business utility.'}
