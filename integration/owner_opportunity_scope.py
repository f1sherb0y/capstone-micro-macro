"""Correlate real native opportunity evaluation before a formal project exists."""
from copy import deepcopy

from integration.project_financing_native import opportunity_scope
from src.coordination.tasks import TaskConflict,task_digest


def owner_opportunity_scope(assembly,request,*,purpose):
    assembly._validate_components();engine=assembly.engine
    if (request.agent.role!='Owner' or assembly.client.organization_roles.get(request.agent.agent_id)!='Owner'
            or request.agent.agent_id not in engine.agents):
        raise TaskConflict('Opportunity scope changes its original participating Owner')
    if purpose=='propose':
        if request.operation!='evaluate_project_opportunity':raise TaskConflict('Not an original owner opportunity request')
        scope=opportunity_scope(assembly,request)
        if set(request.inputs)!={'opportunity','macro_environment','policy','active_project_count','target_pressure'}:
            raise TaskConflict('Opportunity request changes its original input fields')
        active=sum(p.owner_id==request.agent.agent_id and p.current_stage.value not in {'closed','failed','suspended'}
            for p in engine.projects.values())
        horizon=max(1,min(engine.ticks,int(engine.ticks*.75) or engine.ticks))
        target=max(1,(engine.target_project_count*engine.current_tick+horizon-1)//horizon)
        pressure=max(0.,min(1.,(target-len(engine.projects))/max(engine.target_project_count,1)))
        if (request.inputs['macro_environment']!=engine.macro_environment.model_dump(mode='json')
                or request.inputs['policy']!=engine.policy.model_dump(mode='json')
                or request.inputs['active_project_count']!=active or request.inputs['target_pressure']!=pressure):
            raise TaskConflict('Opportunity request changes its actual environment, policy or current Owner portfolio count')
        return {**scope,'opportunity_sha256':task_digest(request.inputs['opportunity'])}
    if purpose=='decide':
        if request.decision_type!='owner_project_opportunity':raise TaskConflict('Not an original opportunity confirmation')
        scope=request.decision_support.get('decision_factors',{}).get('native_owner_opportunity_scope')
        if (not isinstance(scope,dict) or set(scope)!={'tick','owner_id','candidate_project_id','opportunity_sha256'}
                or scope['tick']!=engine.current_tick or request.tick!=engine.current_tick
                or scope['owner_id']!=request.agent.agent_id or scope['candidate_project_id']!=request.project_id):
            raise TaskConflict('Opportunity confirmation lost its actual original candidate scope')
        return deepcopy(scope)
    raise TaskConflict('Unknown owner opportunity transport purpose')


def original_candidate_snapshot(assembly,request):
    """Rebuild only the original collector summary, without registering a project."""
    from gba_construction_sim.backend.models.project import ConstructionProject,ProjectPerformanceState
    from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
    scope=owner_opportunity_scope(assembly,request,purpose='propose');op=request.inputs['opportunity']
    candidate=ConstructionProject(project_id=scope['candidate_project_id'],name=op['name'],project_type=op['project_type'],
        region=op['region'],owner_id=scope['owner_id'],technical_complexity=op['technical_complexity'],
        initial_budget=op['budget'],performance=ProjectPerformanceState(planned_duration=op['planned_duration']))
    return DecisionRequestCollector._project_snapshot(candidate)
