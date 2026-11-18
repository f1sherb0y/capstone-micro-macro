"""Authenticate only own actual evaluated bids for later Contractor screening."""
from copy import deepcopy
import hashlib
from pathlib import Path

from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def with_own_evaluation_history(assembly, *, request, memory, read_guard):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    if not callable(read_guard):
        raise TaskConflict('Evaluated-bid feedback requires the original engine writer guard')
    with read_guard():
        assembly._validate_components()
        client,engine=assembly.client,assembly.engine
        org,tick=request.agent.agent_id,request.metadata.get('tick')
        if (request.agent.role!='Contractor' or request.operation!='consider_tender'
                or client.organization_roles.get(org)!='Contractor' or type(tick) is not int
                or tick!=engine.current_tick or client.simulation_id!=engine.simulation_id
                or memory['organization_id']!=org or memory['run_id']!=client.run_id
                or memory['request_sha256']!=task_digest(request.model_dump(mode='json'))
                or memory['context_sha256']!=task_digest({k:v for k,v in memory.items() if k!='context_sha256'})):
            raise TaskConflict('Evaluated-bid feedback changes its actual own current request or source context')
        records,seen=[],set()
        submissions=client._tender_feedback.for_organization(organization_id=org)
        for event in engine.events.events:
            if event.event_type!='bid_evaluation_completed' or event.tick>=tick:
                continue
            if memory['project_only'] and event.project_id!=memory['project_id']:
                continue
            own=[b for b in event.data.get('ranked_bids',[]) if b.get('contractor_id')==org]
            if not own:continue  # A bounded published ranking cannot prove an absent firm's result.
            project=engine.projects.get(event.project_id)
            logged=[] if project is None else [e for e in project.event_log if e['event_id']==event.event_id]
            committee=event.data.get('evaluation_committee',{})
            selected=event.data.get('selected_contractor_id')
            if (len(own)!=1 or len(logged)!=1 or event.event_id in seen
                    or task_digest(logged[0])!=task_digest(event.model_dump(mode='json'))
                    or event.agent_id!=selected or client.organization_roles.get(selected)!='Contractor'
                    or committee.get('owner_id')!=project.owner_id
                    or client.organization_roles.get(committee.get('owner_id'))!='Owner'
                    or client.organization_roles.get(committee.get('qs_id'))!='QS'
                    or event.data.get('owner_decision',{}).get('accepted') is not True):
                raise TaskConflict('Evaluated-bid feedback lost its original native event, parties or selection')
            seen.add(event.event_id)
            bid=own[0]
            origins=[r for r in submissions if r['effect']=='native_bid_submitted'
                and r['projection']['project_id']==event.project_id
                and r['projection']['tick']==bid.get('submitted_tick')]
            if len(origins)!=1:
                raise TaskConflict('Evaluated-bid feedback lacks its own original micro submission')
            origin=origins[0]
            proposal=client.tasks.get(TaskIdentity(**origin['proposal_identity']))
            final=client.tasks.get(TaskIdentity(**origin['final_identity']))
            source_events=[e for e in engine.events.events if e.event_id==origin['event_id']]
            from integration.bindings.gba_v1_tender_feedback import project_tender_event
            if (len(source_events)!=1 or source_events[0].tick>=event.tick
                    or project_tender_event(AgentObservationV1.model_validate(
                        source_events[0].model_dump(mode='json')),client.organization_roles).get(org)!=origin['projection']
                    or not any(task_digest(e)==task_digest(source_events[0].model_dump(mode='json')) for e in project.event_log)
                    or proposal['state']!='output_formed' or final['state']!='output_formed'
                    or final['output']['decision'] is not True or final['output']['action_type']!='submit_bid'
                    or proposal['output']['factors'].get('micro_result_sha256')!=origin['micro_result_sha256']
                    or bid.get('bid_price')!=origin['projection']['data'].get('bid_price')
                    or bid.get('bid_price')!=proposal['output']['data'].get('bid_price')):
                raise TaskConflict('Evaluated-bid feedback substitutes the original submitted bid or completed responses')
            records.append({'event_id':event.event_id,'project_id':event.project_id,'tick':event.tick,
                'contractor_id':org,'owner_id':committee['owner_id'],'qs_id':committee['qs_id'],
                'selection_status':'preferred' if selected==org else 'not_preferred',
                'own_bid_price':bid['bid_price'],'own_evaluation_score':bid.get('evaluation_score'),
                'original_proposal_identity':origin['proposal_identity'],
                'original_final_identity':origin['final_identity'],
                'original_bid_result_sha256':origin['micro_result_sha256'],
                'source_event_sha256':task_digest(event.model_dump(mode='json'))})
        result=deepcopy(memory)
        result['own_evaluated_bids']={'schema_version':'gba-v1-own-evaluated-bids.v1',
            'source':'authorized_own_native_query_not_delivery',
            'records':sorted(records,key=lambda r:(r['tick'],r['project_id'],r['event_id'])),
            'reader_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'limits':'Own observed preferred-bidder status only; not award, contract, actual profit, debt or resource release.'}
        result['context_sha256']=task_digest({k:v for k,v in result.items() if k!='context_sha256'})
        return result
