"""Read T1 and a run-ID-free commercial choice from the actual A02 snapshot.

Option enumeration may price every candidate. The first pricing calculation
is not necessarily the selected one. Bind the chosen profile to the persisted
option snapshot, and reconstruct cost only from its saved quantity/rate data.
"""
from decimal import Decimal
from src.coordination.tasks import task_digest


def exact(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a declared amount')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Nonfinite declared amount')
    return result


def decimal_text(value):
    return format(exact(value).normalize(), 'f')


def checked_record(record):
    if record.get('record_sha256') != task_digest({k: v for k, v in record.items() if k != 'record_sha256'}):
        raise ValueError('Saved record digest changed')


def extract_pricing_worker(worker, option_record, *, snapshot_locator):
    checked_record(worker)
    checked_record(option_record)
    identity, selection = worker['identity'], option_record['selection']
    if identity['action_id'] != 'CONTRACTOR-A02':
        raise ValueError('Only the saved actual Contractor A02 choice is a pricing observation')
    for field in ['run_id', 'organization_id', 'action_id', 'input_sha256', 'context_sha256']:
        if identity[field] != selection[field]:
            raise ValueError('Option snapshot does not belong to this exact worker invocation')
    snapshot = option_record['snapshot']
    if task_digest(snapshot['source_reading']) != snapshot['source_reading_sha256']:
        raise ValueError('Original pricing source-reading digest changed')
    result = worker['result']
    if task_digest(result) != worker['result_sha256']:
        raise ValueError('Original worker result digest changed')
    execution = worker.get('audit', {}).get('decision', {}).get('execution', {})
    option_id = execution.get('selected_option_id')
    observation = {'organization_id': identity['organization_id'], 'selected_option_id': option_id,
        'result_sha256': worker['result_sha256'], 'snapshot_record_sha256': option_record['record_sha256'],
        'snapshot_locator': snapshot_locator, 'choice': result.get('payload', {}).get('choice'),
        'canonical_commercial_choice': None, 'declared_cost_base': None, 'bid_price': None,
        'markup_fraction': None, 'semantic_strategy': None,
        'semantic_strategy_state': 'structured_choice_only_author_interpretation_separate'}
    if result['kind'] != 'completed' or option_id is None:
        return {**observation, 'state': 'selected_profile_or_completed_business_result_unavailable'}
    options = [o for o in snapshot['options'] if o['option_id'] == option_id]
    if len(options) != 1:
        raise ValueError('Selected option is not unique in its actual saved snapshot')
    action_input = options[0]['action_input']
    def projection(ref):
        rows = [r['projection'] for r in snapshot['source_reading'] if r['ref'] == ref]
        if len(rows) != 1:
            raise ValueError('Selected source is missing or ambiguous in the saved reading')
        return rows[0]
    profile_ref = action_input['pricing_profile_ref']
    profile = projection(profile_ref)
    if profile['choice'] != observation['choice']:
        raise ValueError('Selected pricing profile and actual business choice disagree')
    markup = exact(profile['markup_fraction'])
    allowance = profile['commercial_allowance']
    currency = profile['currency']
    if allowance['currency'] != currency:
        raise ValueError('Pricing observation cannot invent currency conversion')
    observation.update(selected_profile_ref=profile_ref,
        profile_declared_reason=profile.get('decline_reason'),
        canonical_commercial_choice={'choice': profile['choice'], 'profile_markup_fraction': decimal_text(markup),
            'commercial_allowance': decimal_text(allowance['value']), 'currency': currency})
    if profile['choice'] != 'submit_bid':
        return {**observation, 'state': 'observed_decline_no_offered_bid_or_markup'}
    bid = result['payload']['bid']
    if bid['price']['currency'] != currency:
        raise ValueError('Actual bid currency differs from its selected profile')
    observation['bid_price'] = decimal_text(bid['price']['value'])
    if bid['cost_basis_refs'] != action_input['cost_refs']:
        raise ValueError('Actual bid changed its selected declared cost references')
    subtotal, cost_sources = Decimal(0), []
    for cost_ref in action_input['cost_refs']:
        cost = projection(cost_ref)
        quantity = projection(cost['quantity_basis_ref'])
        if cost['quantity_basis_ref'] not in action_input['quantity_refs']:
            raise ValueError('Declared cost leaves the selected quantity scope')
        lines = [line for line in quantity['lines'] if line['local_key'] == cost['quantity_line_key']]
        if len(lines) != 1:
            raise ValueError('Original quantity line is missing or ambiguous')
        amount, rate = lines[0]['quantity'], cost['unit_rate']
        if amount['state'] != 'known' or rate['state'] != 'known':
            return {**observation, 'state': 'independent_declared_cost_not_readable_markup_not_inferred'}
        amount, rate = amount['value'], rate['value']
        if amount['unit'] != cost['quantity_unit'] or rate['currency'] != currency:
            raise ValueError('Declared quantity/rate would require an unprovided unit or FX conversion')
        subtotal += exact(amount['value']) * exact(rate['value'])
        cost_sources.append({'cost_ref': cost_ref, 'quantity_basis_ref': cost['quantity_basis_ref'],
            'quantity_line_key': cost['quantity_line_key'], 'quantity': amount, 'unit_rate': rate})
    if not cost_sources:
        return {**observation, 'state': 'no_independent_declared_cost_sources'}
    price = exact(observation['bid_price'])
    if subtotal * (1 + markup) + exact(allowance['value']) != price:
        raise ValueError('Actual bid does not equal the selected declared cost/markup/allowance formula')
    selected_method_indices = []
    for index, method in enumerate(worker['audit'].get('method_calls', [])):
        if method['method_ref']['id'] != 'micro.contractor.declared_bid_price':
            continue
        if profile_ref not in method['input'].get('source_refs', []):
            continue
        if method['result']['kind'] != 'ok':
            continue
        report = method['result']['value']
        if (exact(report['internal_cost_subtotal']['value']) != subtotal
                or exact(report['offered_price']['value']) != price):
            raise ValueError('Selected pricing audit disagrees with saved quantity/rate data or actual bid')
        selected_method_indices.append(index)
    if not selected_method_indices:
        raise ValueError('Saved actual pricing calculation does not identify the selected profile')
    return {**observation, 'state': 'declared_cost_and_selected_actual_bid_linked', 'currency': currency,
        'declared_cost_base': decimal_text(subtotal),
        'markup_fraction': float((price - subtotal) / subtotal) if subtotal > 0 else None,
        'declared_cost_sources': cost_sources, 'selected_pricing_method_indices': selected_method_indices,
        'cost_source_ref': snapshot_locator + '#/snapshot/source_reading',
        'boundary': 'Markup reconstructed from independent declared quantity/rate inputs and actual bid, not realized profit. Canonical choice excludes run-specific option/profile IDs.'}
