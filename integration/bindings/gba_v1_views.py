"""Read actual GBA v1 own-enterprise occupancy without inventing role objects."""
from copy import deepcopy
import hashlib

from src.coordination.tasks import task_digest


MACRO_VERSION = 'gba-public-2026-08-21'


def read_enterprise_resources(engine, client, *, organization_id, read_guard):
    """The host guard must also serialize engine advancement and other writers.

    This is an original macro-source record, not a ContinuationState or capacity
    verification. Resource totals use GBA's normalized enterprise scale; project
    engagement allocations cannot become time-window ResourceCommitments without
    separately sourced unit/window/authority information. No private competitor
    fields, project-wide snapshots, memory or inferred monetary balances escape.
    """
    if not callable(read_guard):
        raise ValueError('Actual host read guard shared with engine writers is required')
    with read_guard():
        if (client.simulation_id != engine.simulation_id
                or client.tasks.run_id != client.run_id
                or organization_id not in client.organization_roles):
            raise ValueError('Enterprise resource read belongs to another simulation, run or recipient')
        agent = engine.agents.get(organization_id)
        if (agent is None or agent.agent_id != organization_id
                or agent.role != client.organization_roles[organization_id]):
            raise ValueError('Actual macro enterprise identity or role differs from the bound client')
        engagements = []
        for project in sorted(engine.projects.values(),key=lambda row:row.project_id):
            for engagement in project.engagements:
                if engagement.agent_id != organization_id:
                    continue
                engagements.append({
                    'engagement_id':engagement.engagement_id,'project_id':project.project_id,
                    'role':engagement.role,'status':engagement.status.value,
                    'resource_allocation':engagement.resource_allocation,
                    'contractual_obligation':engagement.contractual_obligation,
                    'can_be_recalled':engagement.can_be_recalled,
                    'joined_at_tick':engagement.joined_at_tick,
                    'released_at_tick':engagement.released_at_tick,
                })
        if len({row['engagement_id'] for row in engagements}) != len(engagements):
            raise ValueError('Actual enterprise engagement identities are duplicated')
        engagements.sort(key=lambda row:(row['project_id'],row['engagement_id']))
        facts = {'agent_id':agent.agent_id,'role':agent.role,
                 'total_resource_capacity':agent.total_resource_capacity,
                 'occupied_resource':agent.occupied_resource,
                 'available_resource':agent.available_resource(),'engagements':engagements}
        # This digest distinguishes changes within a single tick. Tick numbers
        # alone are not immutable read versions or a receipt confirmation.
        record = {'schema_version':'gba-v1-enterprise-resources.v1','macro_version':MACRO_VERSION,
            'run_id':client.run_id,'simulation_id':engine.simulation_id,'organization_id':organization_id,
            'observed_tick':engine.current_tick,'facts':deepcopy(facts),
            'facts_sha256':task_digest(facts),
            'resource_unit':'normalized_enterprise_capacity',
            'source_kind':'macro_execution',
            'source_symbols':{
                'resource_totals':'gba_construction_sim.backend.models.agent.EnterpriseAgentProfile',
                'available_resource':'gba_construction_sim.backend.models.agent.EnterpriseAgentProfile.available_resource',
                'engagements':'gba_construction_sim.backend.models.project.ConstructionProject.engagements',
                'business_tick':'gba_construction_sim.backend.simulation.simulation_engine.SimulationEngine.current_tick'},
            'limitations':[
                'Simulation facts, not real-world enterprise qualifications or performance.',
                'Normalized scalar resources; no physical unit conversion, future calendar or exact rational capacity claim.',
                'Project-role engagements are actual allocations, not per-order resource commitments.',
                'No AssetRight, material inventory, debt, production/shipment execution or continuation authority is supplied.',
                'No newer action submission, receipt query or core effect is bound.']}
        record['source_hashes'] = enterprise_resource_source_hashes()
        record['record_sha256'] = task_digest(record)
        return record


def enterprise_resource_source_hashes():
    """Hash the actual bundled definitions without importing or running GBA."""
    from integration.bootstrap import enable_gba_imports

    root = enable_gba_imports()
    symbols = ['models/agent.py','models/project.py','models/engagement.py','simulation/simulation_engine.py']
    result = {}
    for symbol in symbols:
        path = root / 'gba_construction_sim/backend' / symbol
        if not path.is_file():
            raise ValueError('Actual macro resource source definition missing: '+symbol)
        result['gba_construction_sim/backend/'+symbol] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
