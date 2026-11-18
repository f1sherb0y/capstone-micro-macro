"""Authenticate native selection deferral after every bid was independently excluded."""
from copy import deepcopy

from integration.qs_evaluation_outcome_query import original_authorized_round, matching_native_events
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def no_valid_round_is_authorized(parent, plan, result):
    if result['kind']!='completed' or result['payload'].get('choice')!='no_valid_bid':
        return False
    rows = result['payload']['evaluations']
    refs = [b.bid_ref.model_dump(mode='json') for b in plan.bids]
    component = getattr(parent,'admissibility',None)
    return (component is not None and len(rows)==len(refs)>0
        and len({task_digest(r['bid_ref']) for r in rows})==len(refs)
        and all(r['bid_ref'] in refs and r['status']=='exclusion_recommended'
            and not r['unresolved_questions'] for r in rows)
        and all(component.plan(plan,{'project_id':plan.project_id,'tick':plan.tick,
            'contractor_id':b.contractor_id}) is not None for b in plan.bids))


def decide_no_valid_selection(parent, request):
    """Retain the original Owner's negative proposal after all original exclusions.

    The generic native final provider can approve an action without a candidate.
    This bounded adapter path preserves the actual empty-selection semantics;
    it neither selects a contractor nor exposes private QS task identities.
    """
    if (request.agent.role,request.decision_type)!=('Owner','owner_preferred_bidder_selection'):
        return None
    plans = [p for p in parent.plans if (p.project_id,p.tick)==(request.project_id,request.tick)]
    if not plans:return None
    if len(plans)!=1:raise TaskConflict('Empty selection has ambiguous original QS rounds')
    plan = plans[0]
    record = parent._record(plan)
    if record is None:return None
    with parent.bindings.read_guard():
        parent._check()
        identity,result = parent._result(plan,record)
        if result['payload']['choice']!='no_valid_bid':return None
        original_authorized_round(parent,identity,organization_id=plan.organization_id,tick=request.tick)
        project = parent.assembly.engine.projects.get(request.project_id)
        support = request.decision_support
        if (request.tick!=parent.assembly.engine.current_tick or project is None
                or request.agent.agent_id!=project.owner_id or project.selected_qs_id!=plan.organization_id
                or request.project.get('project_id')!=project.project_id
                or request.project.get('owner_id')!=project.owner_id
                or request.project.get('selected_qs_id')!=plan.organization_id
                or request.project.get('stage')!='bid_evaluation'
                or request.project.get('bid_count')!=len(plan.bids)
                or project.current_stage.value!='bid_evaluation' or request.candidate_options
                or request.choice_contract.output_field!='selected_contractor_id'
                or support.get('accepted') is not False or support.get('action_type')!='select_preferred_bidder'
                or support.get('selected_contractor_id') is not None
                or support['action_type'] not in request.constraints.allowed_actions
                or {b['contractor_id'] for b in project.bids}!={b.contractor_id for b in plan.bids}):
            raise TaskConflict('Empty native selection must retain its actual current negative Owner proposal and original bid set')
        exclusions = parent.admissibility.read_original_final_exclusions(plan,tick=request.tick)
        if len(exclusions)!=len(plan.bids) or {r['contractor_id'] for r in exclusions}!={b.contractor_id for b in plan.bids}:
            raise TaskConflict('Empty native selection requires every original finalized independent exclusion')
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
        return AgentDecisionResponseV1(request_id=request.request_id,agent_id=request.agent.agent_id,
            action_type=support['action_type'],decision=False,reason=support['reason'],
            data={'decision_source':'native_no_valid_bid_selection',
                'native_proposal_sha256':task_digest(support)})


def validate_no_valid_deferral(parent, plan, event):
    project = parent.assembly.engine.projects.get(plan.project_id)
    record = parent._record(plan)
    if project is None or record is None:
        raise TaskConflict('No-valid-bid deferral lacks its original project or completed round')
    identity, result = parent._result(plan,record)
    if (not no_valid_round_is_authorized(parent,plan,result)
            or event.event_type!='bid_evaluation_deferred' or event.project_id!=plan.project_id
            or event.tick!=plan.tick or event.agent_id!=project.owner_id
            or event.data.get('owner_decision',{}).get('accepted') is not False
            or 'ranked_bids' in event.data or 'selected_contractor_id' in event.data):
        raise TaskConflict('No-valid-bid outcome must retain the original unselected native deferral')
    return identity


def read_no_valid_evaluation(parent, event, *, organization_id, project_id, tick, evaluation_task_key=None):
    plans = [p for p in parent.plans if (p.organization_id,p.project_id,p.tick)==
        (organization_id,project_id,event.tick)]
    if not plans:
        return None
    if len(plans)!=1:
        raise TaskConflict('Deferred evaluation has ambiguous original review plans')
    plan = plans[0]
    record = parent._record(plan)
    if record is None:
        return None
    identity = TaskIdentity(**record['identity'])
    if evaluation_task_key is not None and identity.key!=evaluation_task_key:
        return None
    _,_,saved = original_authorized_round(parent,identity,organization_id=organization_id,tick=tick)
    if saved['result']['payload'].get('choice')!='no_valid_bid':
        return None
    validate_no_valid_deferral(parent,plan,event)
    matching = matching_native_events(parent,plan)
    if len(matching)!=1 or matching[0]!=event.model_dump(mode='json'):
        raise TaskConflict('No-valid-bid outcome requires the exact original project and global event')
    exclusions = parent.admissibility.read_outcomes(plan,event,tick=tick)
    expected = {b.contractor_id for b in plan.bids}
    if len(exclusions)!=len(expected) or {r['contractor_id'] for r in exclusions}!=expected:
        raise TaskConflict('No-valid-bid outcome lacks a finalized original exclusion for every submitted bid')
    return {'event_id':event.event_id,'project_id':project_id,'tick':event.tick,
        'owner_id':parent.assembly.engine.projects[project_id].owner_id,'qs_id':organization_id,
        'native_status':'selection_deferred_no_valid_bids','preferred_contractor_id':None,
        'source_event_sha256':task_digest(event.model_dump(mode='json')),
        'micro_identity':identity.as_dict(),'micro_result_sha256':saved['result_sha256'],
        'published_opinions':[],'authorized_exclusions':deepcopy(exclusions),
        'owner_decision':deepcopy(event.data['owner_decision']),
        'limits':'Native selection remains deferred. This is neither a terminal buyer refusal nor delivery of private bidder notices.'}
