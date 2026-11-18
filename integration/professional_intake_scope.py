"""Scope original repeated appointment transports using actual provider decisions."""
from src.coordination.tasks import TaskConflict

ROLES = {'Architect', 'Engineer', 'QS'}
PURPOSE_ROLE = {'architect': 'Architect', 'engineer': 'Engineer', 'qs': 'QS'}


def professional_scope(assembly, request, *, purpose):
    engine, client = assembly.engine, assembly.client
    if purpose == 'propose' and request.operation == 'consider_appointment' and request.agent.role in ROLES:
        project_id = request.inputs.get('project', {}).get('project_id')
        scope = {'project_id': project_id, 'tick': engine.current_tick, 'role': request.agent.role}
        project = engine.projects.get(project_id)
        if project is None or project.model_dump(mode='json') != request.inputs.get('project'):
            raise TaskConflict('Professional request changes its actual original project snapshot')
    elif purpose == 'propose' and (request.agent.role, request.operation) == ('Owner', 'select_appointment'):
        role = PURPOSE_ROLE.get(request.inputs.get('purpose'))
        candidates = request.inputs.get('candidates', [])
        scopes = []
        if role is None or not candidates:
            raise TaskConflict('Micro appointment composition needs actual scoped provider decisions for Owner selection')
        for profile, decision in candidates:
            # Candidate tuples transport the original AgentDecision dataclass
            # asdict shape ('factors'); emitted events use 'decision_factors'.
            scope = decision.get('factors', {}).get('native_professional_scope')
            if profile.get('role') != role or not isinstance(scope, dict) or scope.get('role') != role:
                raise TaskConflict('Owner appointment candidate lacks its original professional decision scope')
            proposals = [t for t in client.tasks.for_organization(run_id=client.run_id, organization_id=profile['agent_id'])
                if t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == 'consider_appointment'
                and t['state'] == 'output_formed'
                and t['output'].get('factors', {}).get('native_professional_scope') == scope
                and t['output']['factors'].get('micro_result_sha256') == decision.get('factors', {}).get('micro_result_sha256')]
            if len(proposals) != 1:
                raise TaskConflict('Owner selection substitutes an original formed provider micro proposal')
            scopes.append(scope)
        scope = scopes[0]
        if any(value != scope for value in scopes):
            raise TaskConflict('Owner selection combines decisions from different current projects, roles or times')
    else:
        scope = request.decision_support.get('decision_factors', {}).get('native_professional_scope')
        if (not isinstance(scope, dict) or scope.get('project_id') != request.project_id
                or scope.get('tick') != request.tick):
            raise TaskConflict('Final appointment request lost its original proposal scope')
        expected_role = (PURPOSE_ROLE.get(request.decision_type.removeprefix('owner_select_'))
                         if request.agent.role == 'Owner' else request.agent.role)
        if scope.get('role') != expected_role:
            raise TaskConflict('Final appointment request substitutes its original professional role')
    if (set(scope) != {'project_id', 'tick', 'role'} or type(scope['tick']) is not int
            or scope['tick'] != engine.current_tick or scope['role'] not in ROLES):
        raise TaskConflict('Appointment transport needs one actual current professional scope')
    project = engine.projects.get(scope['project_id'])
    if project is None or project.current_stage.value != 'initiation':
        raise TaskConflict('Appointment transport is outside its current native initiation stage')
    if request.agent.role == 'Owner' and project.owner_id != request.agent.agent_id:
        raise TaskConflict('Appointment selection changes its actual project Owner')
    return dict(scope)


def transport_native_appointment_decision(routes, request):
    """Confirm the same original native proposal; do not choose a second time."""
    from copy import deepcopy
    from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
    from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
    from src.coordination.tasks import task_digest

    scope = professional_scope(routes.assembly,request,purpose='decide')
    owner = request.agent.role == 'Owner'
    action = 'select_appointment' if owner else 'consider_appointment'
    proposals = [t for t in routes.assembly.client.tasks.for_organization(
        run_id=routes.assembly.client.run_id,organization_id=request.agent.agent_id)
        if t['identity']['purpose']=='propose' and t['identity']['action_id']==action and t['state']=='output_formed'
        and t['output'].get('factors',{}).get('native_professional_scope')==scope]
    if len(proposals)!=1:
        raise TaskConflict('Native appointment confirmation needs its one original formed scoped proposal')
    proposal=proposals[0]['output'];support=request.decision_support
    if (proposal['factors'].get('decision_source')!='native_macro'
            or support.get('decision_factors')!=proposal['factors']
            or support.get('accepted')!=proposal['accepted'] or support.get('action_type')!=proposal['action_type']
            or any(task_digest(support.get(k))!=task_digest(v) for k,v in proposal['data'].items())
            or proposal['action_type'] not in request.constraints.allowed_actions):
        raise TaskConflict('Native appointment confirmation substitutes its original proposal or support')
    if owner and (request.choice_contract.output_field!='selected_agent_id' or request.choice_contract.multiple
            or proposal['accepted'] and proposal['data'].get('selected_agent_id') not in {o['id'] for o in request.candidate_options}):
        raise TaskConflict('Native appointment choice changes its original bounded candidates')
    response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=request.agent.agent_id,
        action_type=proposal['action_type'],decision=proposal['accepted'],reason=proposal['reason'],
        data={**deepcopy(proposal['data']), 'decision_source':'native_macro',
            'source':'original_native_appointment_proposal','native_professional_scope':scope,
            'proposal_response_sha256':task_digest(proposal)})
    ExternalAgentDecisionProvider._validated_action(request,response)
    routes._calls.append({'purpose':'decide','role':request.agent.role,'decision_type':request.decision_type,
        'request_id':request.request_id,'decision_source':'native_macro','source':'original_native_appointment_proposal'})
    return response
