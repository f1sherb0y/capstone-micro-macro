"""Read actual earlier suspensions visible to the original contract party."""
from copy import deepcopy
import hashlib

from src.coordination.tasks import TaskConflict, task_digest


def read_own_construction_suspensions(assembly, *, organization_id, tick, read_guard):
    """A private native query; no inspection, fault attribution or debt effect."""
    if not callable(read_guard):
        raise TaskConflict('Suspension reading requires the original engine writer guard')
    with read_guard():
        assembly._validate_components()
        engine, client = assembly.engine, assembly.client
        agent = engine.agents.get(organization_id)
        if (client.organization_roles.get(organization_id) != 'Contractor' or agent is None
                or agent.role != 'Contractor' or agent.agent_id != organization_id
                or client.simulation_id != engine.simulation_id or client.tasks.run_id != client.run_id
                or type(tick) is not int or tick != engine.current_tick):
            raise TaskConflict('Suspension query changes the original own party, run or current clock')
        history, seen = [], set()
        for event in engine.events.events:
            if event.event_type != 'project_suspended' or event.tick >= tick:
                continue
            project = engine.projects.get(event.project_id)
            if project is None:
                raise TaskConflict('Suspension event lost its actual native project')
            if project.selected_contractor_id != organization_id:
                continue
            original = event.model_dump(mode='json')
            logged = [r for r in project.event_log if r['event_id'] == event.event_id]
            contracts = [r for r in project.contracts if r.get('contractor_id') == organization_id
                and type(r.get('signed_tick')) is int and r['signed_tick'] <= event.tick]
            engagements = [r for r in project.engagements if r.agent_id == organization_id and r.role == 'Contractor'
                and r.project_id == event.project_id and r.contractual_obligation
                and r.joined_at_tick <= event.tick
                and (r.released_at_tick is None or r.released_at_tick > event.tick)]
            # This native event contains no author/party/metric fields. Require
            # the actual dated main contract and engagement; never manufacture
            # a micro decision or identify a responsible Supplier from it.
            if (len(logged) != 1 or task_digest(logged[0]) != task_digest(original)
                    or event.event_id in seen or len(contracts) != 1 or len(engagements) != 1
                    or event.agent_id is not None or event.data != {}
                    or event.description != 'Serious safety or quality issue'
                    or client.organization_roles.get(project.owner_id) != 'Owner'):
                raise TaskConflict('Suspension history lost its exact native event or original contract-party evidence')
            seen.add(event.event_id)
            history.append({'event_id':event.event_id,'project_id':event.project_id,'tick':event.tick,
                'owner_id':project.owner_id,'contractor_id':organization_id,
                'source_event_sha256':task_digest(original),'signed_tick':contracts[0]['signed_tick'],
                'contract_sha256':task_digest(contracts[0]),'engagement_id':engagements[0].engagement_id,
                'outcome':'native_project_suspended','reason':'Serious safety or quality issue'})
        from integration.bootstrap import enable_gba_imports
        root = enable_gba_imports()/'gba_construction_sim/backend'
        record = {'schema_version':'gba-v1-own-construction-suspensions.v1','run_id':client.run_id,
            'simulation_id':engine.simulation_id,'organization_id':organization_id,'as_of_tick':tick,
            'source':'authorized_own_native_construction_suspension_query',
            'suspensions':sorted(history,key=lambda r:(r['tick'],r['project_id'],r['event_id'])),
            'source_hashes':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in (
                'simulation/project_lifecycle_engine.py','simulation/event_system.py','models/event.py','models/engagement.py')},
            'limits':['Actual aggregate suspension only, not detailed inspection, work measurement or cause attribution.',
                'No responsibility is assigned to an Owner, Supplier or other party; no cash, debt or resource release is inferred.',
                'Only current own main-contract projects with a dated contract and engagement covering the original event are included.',
                'Empty history is no authenticated earlier event, not zero defects or cleared obligations.',
                'Private authorized query, not an external delivery receipt.']}
        record['record_sha256'] = task_digest(record)
        return deepcopy(record)
