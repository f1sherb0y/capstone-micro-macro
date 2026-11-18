"""Own original A11 proposals as private history, never formal registration.

The account view is derived on read from a retained authorized original result.
The current contract *projection* adds this private history link; the original
contract identity/version, sealed inputs, old readings and native state stay
unchanged. No message, aggregate settlement or requested choice creates it.
"""
from copy import deepcopy

from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_closeout_objects import ContractorFinalAccountView
from src.coordination.tasks import TaskConflict, task_digest


def _one(rows, reference):
    matches = [r['value'] for r in rows if r['ref'] == reference]
    if len(matches) != 1:
        raise TaskConflict('Private final-account history requires its exact original source')
    return matches[0]


def validate_history_plan(plan, prior):
    """Check the explicit source declaration before any original business runs."""
    binding = plan.contractor_final_account_history
    ref = binding.final_account_ref.model_dump(mode='json')
    profile = _one(plan.objects, plan.action_input.get('handover_profile_ref'))
    before = _one(prior.objects, prior.action_input.get('handover_profile_ref'))
    contract = _one(plan.objects, plan.action_input.get('contract_ref'))
    original = _one(prior.objects, prior.action_input.get('contract_ref'))
    if (binding.plan_id not in plan.depends_on
            or plan.context.contract_ref.id != 'CONTRACTOR-A11'
            or prior.context.contract_ref.id != 'CONTRACTOR-A11'
            or plan.organization_id != prior.organization_id or plan.project_id != prior.project_id
            or plan.context.scope != prior.context.scope or plan.tick != prior.tick
            or plan.event_type != prior.event_type or plan.event_type != 'final_account_review_started'
            or profile.get('choice') != 'respond_settlement' or before.get('choice') != 'propose_final_account'
            or profile.get('final_account_ref') != ref
            or plan.action_input.get('contract_ref') != prior.action_input.get('contract_ref')
            or contract != original
            or profile.get('component_refs') != before.get('component_refs')
            or profile.get('disputed_refs') != before.get('disputed_refs')
            or plan.dependency_evidence_ref is None or binding.final_account_ref not in plan.context.visible_refs
            or any(r['ref'] == ref for r in plan.objects + prior.objects)):
        raise TaskConflict('Private final-account history requires an explicit own original proposal and unchanged contract/items')


def bind_history(application, plan, objects, dependencies):
    """Project only a currently readable completed own proposal into A11 history."""
    binding = plan.contractor_final_account_history
    prior = application._by_id[binding.plan_id]
    validate_history_plan(plan, prior)
    # This checks current authority and all retained original source readings.
    # A completed dependency alone is not permission to disclose its result.
    queried = application.query_saved_result(prior.plan_id)
    if queried['status'] != 'saved' or queried['task_state'] != 'output_formed':
        raise TaskConflict('Private final-account history has no original completed proposal')
    saved = queried['record']
    dependency, = [d for d in dependencies if d['plan_id'] == prior.plan_id]
    if (saved['result']['kind'] != 'completed' or saved['result']['payload'].get('choice') != 'propose_final_account'
            or dependency['identity'] != queried['identity']
            or dependency['result_sha256'] != saved['result_sha256']
            or dependency['result'] != saved['result']):
        raise TaskConflict('Private final-account history changes its original result or task')
    reading = [{'ref': r['ref'], 'value': r['projection']} for r in saved['source_reading']]
    profile = _one(reading, prior.action_input['handover_profile_ref'])
    contract = _one(reading, prior.action_input['contract_ref'])
    current = _one(objects, plan.action_input['contract_ref'])
    payload = saved['result']['payload']
    if (contract != _one(prior.objects, prior.action_input['contract_ref']) or current != contract
            or payload['component_refs'] != profile['component_refs']
            or payload['disputed_refs'] != profile['disputed_refs']
            or profile['authority_ref'] not in [r.model_dump(mode='json') for r in prior.context.authorization_refs]):
        raise TaskConflict('Private final-account history substitutes original contract, author or itemized result')
    components = payload['component_refs'] + payload['disputed_refs']
    if (len({task_digest(r) for r in components}) != len(components)
            or {task_digest(r) for r in components} != {task_digest(r) for r in prior.action_input['settlement_components']}):
        raise TaskConflict('Private final-account history omits or repeats original components')
    value = ContractorFinalAccountView.model_validate({
        'ref': binding.final_account_ref.model_dump(mode='json'),
        'contract_ref': deepcopy(prior.action_input['contract_ref']),
        'scope': prior.context.scope.model_dump(mode='json'),
        'available_at': plan.context.business_time.model_dump(mode='json'),
        'effective_window': deepcopy(profile['effective_window']),
        'evidence_refs': [plan.dependency_evidence_ref.model_dump(mode='json')],
        'author_actor_id': prior.context.actor_id, 'author_organization_id': prior.organization_id,
        'author_function_ref': prior.context.function_ref.model_dump(mode='json'),
        'author_authority_ref': deepcopy(profile['authority_ref']),
        'author_action_id': prior.context.contract_ref.id,
        'authored_at': prior.context.business_time.model_dump(mode='json'),
        'business_key': profile['business_key'], 'component_refs': deepcopy(components), 'status': 'proposed',
    }).model_dump(mode='json')
    # Require the successor's real current grant to cover historical authorship
    # as well as this newly derived view; the original worker checks it again.
    grants = application.authority.organizations.grants(plan.context, 'CONTRACTOR-A11', 'Contractor')
    readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in plan.context.visible_refs}
    for ref in (value['ref'], value['author_authority_ref'], value['author_function_ref']):
        if Reference.model_validate(ref).key() not in readable:
            raise TaskConflict('Private final-account history exceeds current own source authority')
    current['final_account_refs'].append(deepcopy(value['ref']))
    objects.append({'ref': deepcopy(value['ref']), 'value': value})
