"""Identify original financing requests and transport their unchanged native choice.

This module owns no credit decision, loan, account or project mutation. Native
project generation inserts its current project before arranging finance. The
one unfinished creation supplies correlation missing from the proposal wire.
"""
from copy import deepcopy

from src.coordination.tasks import TaskConflict, task_digest

PROPOSALS = {('Bank', 'consider_financing'), ('Owner', 'select_financing_offer')}
DECISIONS = {('Bank', 'bank_project_financing'), ('Owner', 'owner_financing_selection')}


def _pending_project(assembly):
    engine = assembly.engine
    pending = [p for p in engine.projects.values() if p.flags.get('created_tick') == engine.current_tick
        and p.current_stage.value == 'initiation'
        and not any(e['event_type'] in {'project_financing_selected','project_financing_deferred'} for e in p.event_log)]
    if len(pending) != 1:
        raise TaskConflict('Financing correlation requires one actual unfinished current native project creation')
    return pending[0]


def financing_requirement(assembly, scope):
    """Read the amount used by the frozen native financing call, in HKD.

    This is its requested financing exposure, not the entire project budget or
    an executed payment. The native call supplies no detailed spending schedule.
    """
    project=assembly.engine.projects[scope['project_id']]
    if project.owner_id!=scope['owner_id'] or scope['tick']!=assembly.engine.current_tick:
        raise TaskConflict('Financing amount changes its actual current project scope')
    owner=assembly.engine.agents[project.owner_id]
    ratio=max(0.25,min(0.65,0.65-0.35*owner.financial_capacity))
    return {'requested_amount':project.initial_budget*ratio,'requested_ratio':ratio,
        'initial_budget':project.initial_budget,'currency':'HKD'}


def financing_scope(assembly, request, *, purpose):
    if assembly is None:
        raise TaskConflict('Financing scope requires the original attached engine')
    assembly._validate_components()
    project = _pending_project(assembly)
    engine = assembly.engine
    profile = engine.agents.get(request.agent.agent_id)
    if (profile is None or profile.role != request.agent.role
            or assembly.client.organization_roles.get(profile.agent_id) != profile.role):
        raise TaskConflict('Financing scope substitutes an original participating enterprise')
    scope = {'project_id': project.project_id, 'owner_id': project.owner_id, 'tick': engine.current_tick}
    if request.agent.role == 'Owner' and request.agent.agent_id != project.owner_id:
        raise TaskConflict('Financing request changes the actual project Owner')
    if purpose == 'propose' and (request.agent.role, request.operation) == ('Bank', 'consider_financing'):
        owner = engine.agents[project.owner_id]
        # Verify the scalar inputs against the existing _arrange_project_financing
        # calculation. This determines correlation only, never bank eligibility.
        risk = max(0.0, min(1.0, 0.55 * project.technical_complexity
            + 0.25 * engine.policy.procedural_uncertainty
            + 0.20 * max(0.0, 1.0 - engine.macro_environment.financing_condition_index)))
        expected = {'requested_amount': financing_requirement(assembly,scope)['requested_amount'],
            'borrower_financial_capacity': owner.financial_capacity, 'project_risk': risk,
            'financing_condition_index': engine.macro_environment.financing_condition_index}
        if task_digest(request.inputs) != task_digest(expected):
            raise TaskConflict('Bank request changes its actual native financing scalars')
        if any(e['event_type'] == 'bank_financing_decision' and e['agent_id'] == request.agent.agent_id
               for e in project.event_log):
            raise TaskConflict('Bank request is already executed in the native financing loop')
    elif purpose == 'propose' and (request.agent.role, request.operation) == ('Owner', 'select_financing_offer'):
        from gba_construction_sim.backend.agents.base_agent import AgentDecision
        events = [e for e in project.event_log if e['event_type'] == 'bank_financing_decision'
                  and e['tick'] == engine.current_tick]
        offers = request.inputs.get('offers')
        if not isinstance(offers, list) or len(offers) != len(events):
            raise TaskConflict('Owner financing request changes the actual bank offer set')
        seen = set()
        for profile, decision in offers:
            bank = profile.get('agent_id')
            original_profile = engine.agents.get(bank)
            if (bank in seen or original_profile is None or original_profile.role != 'Bank'
                    or task_digest(profile) != task_digest(original_profile.model_dump(mode='json'))):
                raise TaskConflict('Owner financing request substitutes an actual bank identity')
            seen.add(bank)
            original_events = [e for e in events if e['agent_id'] == bank]
            if len(original_events) != 1:
                raise TaskConflict('Owner financing request lacks one original native bank decision')
            event = original_events[0]
            serialized = AgentDecision(**deepcopy(decision)).to_event_data()
            if (decision.get('factors', {}).get('native_financing_scope') != scope
                    or any(task_digest(event['data'].get(k)) != task_digest(v) for k, v in serialized.items())):
                raise TaskConflict('Owner financing request substitutes an actual native bank decision')
    elif purpose == 'decide' and (request.agent.role, request.decision_type) in DECISIONS:
        if (request.project_id != project.project_id or request.tick != engine.current_tick
                or request.decision_support.get('decision_factors', {}).get('native_financing_scope') != scope):
            raise TaskConflict('Final financing request lost its actual original project scope')
    else:
        raise TaskConflict('Unsupported request for native financing correlation')
    return scope


def opportunity_scope(assembly, request):
    """Match the exact candidate identity used by native opportunity evaluation."""
    if assembly is None:
        raise TaskConflict('Opportunity scope requires the original attached engine')
    assembly._validate_components()
    tick = assembly.engine.current_tick
    opportunity = request.inputs.get('opportunity', {})
    environment = request.inputs.get('macro_environment', {})
    if environment.get('current_tick') != tick or type(tick) is not int or tick < 1:
        raise TaskConflict('Opportunity request changes the actual current native clock')
    try:
        identity = (f"OPPORTUNITY-{tick}-{request.agent.agent_id}-{opportunity['region']}-"
                    f"{opportunity['project_type']}-{int(opportunity['budget'])}")
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskConflict('Opportunity scope lacks its original native candidate identity') from exc
    return {'tick': tick, 'owner_id': request.agent.agent_id, 'candidate_project_id': identity}


def transport_native_financing_decision(routes, request):
    """Explicit source: the one formed native proposal, with no second choice."""
    from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
    from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider

    scope = financing_scope(routes.assembly, request, purpose='decide')
    operation = 'consider_financing' if request.agent.role == 'Bank' else 'select_financing_offer'
    proposals = [t for t in routes.assembly.client.tasks.for_organization(
        run_id=routes.assembly.client.run_id, organization_id=request.agent.agent_id)
        if t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == operation
        and t['state'] == 'output_formed' and t['output'].get('factors', {}).get('native_financing_scope') == scope]
    if len(proposals) != 1:
        raise TaskConflict('Native financing final transport needs its one original formed proposal')
    proposal = proposals[0]['output']
    support = request.decision_support
    if (proposal['factors'].get('decision_source') != 'native_macro'
            or support.get('decision_factors') != proposal['factors']
            or support.get('action_type') != proposal['action_type']
            or support.get('accepted') != proposal['accepted']
            or any(task_digest(support.get(k)) != task_digest(v) for k, v in proposal['data'].items())
            or proposal['action_type'] not in request.constraints.allowed_actions):
        raise TaskConflict('Final financing support substitutes its original native proposal')
    if request.agent.role == 'Owner':
        selected = proposal['data'].get('selected_bank_id')
        if (request.choice_contract.output_field != 'selected_bank_id' or request.choice_contract.multiple
                or selected is not None and selected not in {o['id'] for o in request.candidate_options}):
            raise TaskConflict('Owner financing choice leaves its original accepted bank candidates')
    response = AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
        action_type=proposal['action_type'], decision=proposal['accepted'], reason=proposal['reason'],
        data={**deepcopy(proposal['data']), 'decision_source': 'native_macro',
            'source': 'original_native_financing_proposal', 'native_financing_scope': scope,
            'proposal_response_sha256': task_digest(proposal)})
    ExternalAgentDecisionProvider._validated_action(request, response)
    routes._calls.append({'purpose': 'decide', 'role': request.agent.role, 'decision_type': request.decision_type,
        'request_id': request.request_id, 'decision_source': 'native_macro', 'source': 'original_native_financing_proposal'})
    return response
