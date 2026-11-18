"""Scope native regulatory review/approval requests without changing wire IDs."""
from copy import deepcopy

from src.coordination.tasks import TaskConflict, task_digest

PROPOSALS={'consider_review_assignment':'review_assignment','decide_approval':'design_approval'}
DECISIONS={'government_review_assignment':'review_assignment','government_design_approval':'design_approval',
    'government_completion_approval':'completion_approval'}


def government_scope(assembly, request, *, purpose):
    from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
    assembly._validate_components()
    engine=assembly.engine
    if request.agent.role!='Government' or assembly.client.organization_roles.get(request.agent.agent_id)!='Government':
        raise TaskConflict('Regulatory scope requires the actual original Government organization')
    if purpose=='propose':
        operation=PROPOSALS.get(request.operation);snapshot=request.inputs.get('project',{})
        project_id=snapshot.get('project_id')
    elif purpose=='decide':
        operation=DECISIONS.get(request.decision_type);snapshot=request.project;project_id=request.project_id
    else:
        raise TaskConflict('Unknown regulatory transport purpose')
    project=engine.projects.get(project_id)
    if operation is None or project is None or type(engine.current_tick) is not int:
        raise TaskConflict('Regulatory request changes its actual current project, stage or snapshot')
    stage=project.current_stage.value
    if operation=='review_assignment' and stage=='construction':
        operation='completion_review_assignment'
    elif purpose=='propose' and operation=='design_approval' and stage=='completion':
        operation='completion_approval'
    allowed_stage={'review_assignment':'approval','design_approval':'approval',
        'completion_review_assignment':'construction','completion_approval':'completion'}
    if allowed_stage.get(operation)!=stage:
        raise TaskConflict('Regulatory request substitutes its actual design/completion stage or review purpose')
    # The original proposal carries the full project; its final request uses
    # the original collector's bounded summary. Compare each original shape.
    expected=(project.model_dump(mode='json') if purpose=='propose'
              else DecisionRequestCollector._project_snapshot(project))
    if expected!=snapshot:
        raise TaskConflict('Regulatory request changes its actual current project, stage or snapshot')
    scope={'project_id':project_id,'tick':engine.current_tick,'purpose':operation}
    if purpose=='decide' and (request.tick!=engine.current_tick
            or request.decision_support.get('decision_factors',{}).get('native_government_scope')!=scope):
        raise TaskConflict('Regulatory confirmation lost its original proposal scope')
    return scope


def transport_native_approval(routes,request):
    from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
    from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
    scope=government_scope(routes.assembly,request,purpose='decide')
    rows=[t['output'] for t in routes.assembly.client.tasks.for_organization(
        run_id=routes.assembly.client.run_id,organization_id=request.agent.agent_id)
        if t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_approval'
        and t['state']=='output_formed' and t['output'].get('factors',{}).get('native_government_scope')==scope]
    if len(rows)!=1:raise TaskConflict('Native regulatory confirmation needs one original scoped proposal')
    proposal=rows[0];support=request.decision_support
    if (proposal['factors'].get('decision_source')!='native_macro' or support.get('decision_factors')!=proposal['factors']
            or support.get('accepted')!=proposal['accepted'] or support.get('action_type')!=proposal['action_type']
            or any(task_digest(support.get(k))!=task_digest(v) for k,v in proposal['data'].items())
            or proposal['action_type'] not in request.constraints.allowed_actions):
        raise TaskConflict('Native approval substitutes its original proposal or permitted action')
    response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=request.agent.agent_id,
        action_type=proposal['action_type'],decision=proposal['accepted'],reason=proposal['reason'],
        data={**deepcopy(proposal['data']),'decision_source':'native_macro','source':'original_native_government_approval',
            'native_government_scope':scope,'proposal_response_sha256':task_digest(proposal)})
    ExternalAgentDecisionProvider._validated_action(request,response)
    routes._calls.append({'purpose':'decide','role':'Government','decision_type':request.decision_type,
        'request_id':request.request_id,'decision_source':'native_macro','source':'original_native_government_approval'})
    return response
