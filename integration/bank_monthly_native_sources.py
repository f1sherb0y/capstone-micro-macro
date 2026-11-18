"""Own native monthly strategy outcomes and future-only private quote bounds."""
from copy import deepcopy
from decimal import Decimal

from integration.bank_financing_private import checked_result, evidence_binding
from integration.bank_monthly_risk import result_operation, result_judgment
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def monthly_bank_scope(assembly, request, *, purpose):
    assembly._validate_components()
    engine, org = assembly.engine, request.agent.agent_id
    if (request.agent.role != 'Bank' or assembly.client.organization_roles.get(org) != 'Bank'
            or org not in engine.agents or engine.agents[org].role != 'Bank'):
        raise TaskConflict('Monthly strategy requires the original own Bank')
    scope = {'organization_id': org, 'tick': engine.current_tick}
    environment = engine.macro_environment.model_dump(mode='json')
    if purpose == 'propose':
        if (request.operation != 'decide_monthly_operation' or set(request.inputs) != {'macro_environment'}
                or request.inputs['macro_environment'] != environment):
            raise TaskConflict('Monthly Bank strategy changes its current original environment')
    elif purpose == 'decide':
        if (request.decision_type != 'monthly_enterprise_operation' or request.tick != scope['tick']
                or request.project_id is not None or request.project not in (None, {}) or request.environment != environment
                or request.decision_support.get('decision_factors', {}).get('native_bank_monthly_scope') != scope):
            raise TaskConflict('Monthly Bank final changes its original scope or proposal')
    else:
        raise TaskConflict('Unknown monthly Bank transport purpose')
    return scope


def selected_strategy(saved):
    sources = {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
    space, = [v for v in sources.values() if v.get('ref', {}).get('kind') == 'LendingStrategySpace']
    payload = saved['result']['payload']
    if payload['choice'] == 'revise_strategy':
        selected = payload['strategy_ref']
    elif payload['choice'] == 'retain_strategy' and space['current_strategy_ref']['state'] == 'known':
        selected = space['current_strategy_ref']['value']
    else:
        raise TaskConflict('Unresolved monthly strategy cannot become a native business decision')
    strategy = sources[task_digest(selected)]
    if (strategy['lender_id'] != saved['identity']['organization_id'] or strategy['modifies_existing_terms']
            or strategy['originating_action_id'] != 'BANK-A01' or strategy['maximum_new_commitment']['state'] != 'known'):
        raise TaskConflict('Monthly strategy cannot revise existing terms or invent a future credit bound')
    return selected, strategy


def prior_monthly_strategies(app, *, organization_id, tick):
    """Authorized own-event query; missing notifications do not imply execution."""
    with app.parent.read_guard():
        app.check_components()
        engine, client = app.assembly.engine, app.assembly.client
        if client.organization_roles.get(organization_id) != 'Bank' or type(tick) is not int or engine.current_tick != tick:
            raise TaskConflict('Bank monthly history changes its own recipient or current clock')
        tasks = client.tasks.for_organization(run_id=client.run_id, organization_id=organization_id)
        records = app._records()
        origins = []
        for event in engine.events.events:
            raw = event.model_dump(mode='json')
            if (event.event_type != 'agent_operation' or event.agent_id != organization_id or event.tick >= tick
                    or event.project_id is not None or event.data.get('operation') not in {'review_credit_pipeline', 'adjust_credit_terms', 'monitor_borrower_risk'}):
                continue
            scope = {'organization_id': organization_id, 'tick': event.tick}
            parents = [r for r in records if r['scope'] == scope]
            if not parents:
                continue  # An original native rule operation is not micro work.
            proposals = [t['output'] for t in tasks if t['identity']['purpose'] == 'propose'
                and t['identity']['action_id'] == 'decide_monthly_operation' and t['state'] == 'output_formed'
                and t['output'].get('factors', {}).get('native_bank_monthly_scope') == scope]
            finals = [t['output'] for t in tasks if t['identity']['purpose'] == 'decide'
                and t['identity']['action_id'] == 'monthly_enterprise_operation' and t['state'] == 'output_formed'
                and t['output'].get('data', {}).get('native_bank_monthly_scope') == scope]
            if len(parents) != 1 or len(proposals) != 1 or len(finals) != 1:
                raise TaskConflict('Bank monthly outcome lost its original workflow, proposal or final')
            parent, proposal, final = parents[0], proposals[0], finals[0]
            identity = TaskIdentity(**parent['identity'])
            saved = checked_result(app.worker, identity)
            snapshot = app.worker.snapshots.get(identity)
            selected, strategy = selected_strategy(saved)
            action = result_operation(saved)
            factors, data = proposal['factors'], event.data
            native = [r['projection'] for r in saved['source_reading'] if r['ref'] == parent['native_evidence_ref']]
            if (parent['state'] != 'formed' or proposal['action_type'] != action or final['action_type'] != action
                    or proposal['accepted'] is not True or final['decision'] is not True
                    or identity.organization_id != organization_id or factors.get('micro_action_id') != 'BANK-A01'
                    or factors.get('micro_task_key') != identity.key or factors.get('micro_result_sha256') != saved['result_sha256']
                    or parent['result_sha256'] != saved['result_sha256'] or snapshot['context'] != parent['context']
                    or snapshot['action_input'] != parent['action_input']
                    or parent['proposal_response_sha256'] != task_digest(proposal)
                    or final['data'] != {**factors, 'proposal_response_sha256': task_digest(proposal)}
                    or len(native) != 1 or native[0]['content_hash'] != task_digest(parent['observed'])
                    or parent['observed']['native_request_sha256'] != task_digest(parent['native_request'])
                    or data.get('operation') != action or data.get('decision_accepted') is not True
                    or data.get('decision_source') != 'llm_agent'
                    or any(data.get(k) != proposal['data'][k] for k in ('label', 'description'))
                    or data.get('decision_utility') != round(proposal['utility'], 4)
                    or data.get('decision_probability') != round(proposal['probability'], 4)):
                raise TaskConflict('Bank monthly history substitutes its exact deciding result or actual native outcome')
            origins.append({'event_id': event.event_id, 'tick': event.tick, 'organization_id': organization_id,
                'native_bank_monthly_scope': scope, 'identity': identity.as_dict(), 'micro_task_key': identity.key,
                'micro_result_sha256': saved['result_sha256'], 'source_event_sha256': task_digest(raw),
                'proposal_response_sha256': task_digest(proposal), 'final_response_sha256': task_digest(final),
                'selected_strategy_ref': selected, 'selected_strategy_sha256': task_digest(strategy),
                'maximum_new_commitment': deepcopy(strategy['maximum_new_commitment']['value']),
                'strategy_effective_window': deepcopy(strategy['effective_window']),
                'boundary': 'Future private quotation bound; not a loan, cash transfer or occupied commitment.'})
            if result_judgment(saved) is not None:
                origins[-1]['operation']=action
        if len({r['event_id'] for r in origins}) != len(origins) or len({r['tick'] for r in origins}) != len(origins):
            raise TaskConflict('Bank monthly history repeats an original operation')
        expected = [r for r in records if r['scope']['organization_id'] == organization_id and r['scope']['tick'] < tick]
        if {r['scope']['tick'] for r in expected} != {r['tick'] for r in origins}:
            raise TaskConflict('Earlier Bank monthly result has no confirmed native outcome; query remains unresolved')
        return sorted(origins, key=lambda r: (r['tick'], r['event_id']))


def quote_from_monthly(app, plan, objects):
    history = prior_monthly_strategies(app, organization_id=plan.organization_id, tick=plan.tick)
    policy, = [r['value'] for r in objects if r['ref']['kind'] == 'QuoteAuthorityPolicy']
    if plan.monthly_strategy_evidence_ref is None:
        raise TaskConflict('Monthly strategy requires its declared private quotation handoff source')
    original = deepcopy(policy)
    ceiling = policy['maximum_principal']
    if ceiling['state'] != 'known' or policy['lender_id'] != plan.organization_id:
        raise TaskConflict('Monthly strategy requires original known private amount authority')
    maximum = ceiling['value']
    observed = {'prior_own_monthly_strategy': history, 'independent_quote_policy_sha256': task_digest(original),
                'independent_maximum_principal': deepcopy(maximum)}
    if history:
        latest = history[-1]
        cap, window = latest['maximum_new_commitment'], latest['strategy_effective_window']
        now = plan.steps['BANK-A04'].context.business_time.model_dump(mode='json')
        from src.actions.contracts.common import TimeWindow, TimePoint
        if (not TimeWindow.model_validate(window).contains(TimePoint.model_validate(now))
                or cap['currency'] != maximum['currency'] or Decimal(cap['value']) < 0):
            raise TaskConflict('Monthly strategy cannot change currency, validity or nonnegative quotation bounds')
        observed['applied_strategy'] = latest
        maximum = {**maximum, 'value': format(min(Decimal(cap['value']), Decimal(maximum['value'])), 'f'),
                   'basis_ref': plan.monthly_strategy_evidence_ref.model_dump(mode='json')}
    evidence_binding(objects, plan.monthly_strategy_evidence_ref.model_dump(mode='json'), observed)
    policy['maximum_principal']['value'] = maximum
    return observed
