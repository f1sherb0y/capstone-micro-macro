"""Read the actual earlier native award for current supply processing."""
from src.coordination.tasks import TaskConflict, task_digest


def signed_contract_for_supply(assembly, *, scope, organization_id):
    """No detailed agreement, financial position or physical reserve is inferred."""
    assembly._validate_components()
    engine = assembly.engine
    project = engine.projects.get(scope['project_id'])
    role = assembly.client.organization_roles.get(organization_id)
    if (project is None or scope['tick'] != engine.current_tick
            or role not in {'Contractor', 'Supplier'}
            or role == 'Contractor' and organization_id != scope['contractor_id']
            or project.selected_contractor_id != scope['contractor_id']
            or project.current_stage.value != 'contract_award'
            or not project.flags.get('contract_signed')):
        raise TaskConflict('Supply handoff requires its current signed-project party and time')
    contracts = [c for c in project.contracts if c.get('contractor_id') == scope['contractor_id']]
    awards = [e for e in project.event_log if e['event_type'] == 'contract_awarded'
              and e['agent_id'] == scope['contractor_id']]
    if len(contracts) != 1 or len(awards) != 1:
        raise TaskConflict('Supply handoff needs one actual native award, not an initial contract declaration')
    contract, event = contracts[0], awards[0]
    data = event['data']
    global_events = [e.model_dump(mode='json') for e in engine.events.events if e.event_id == event['event_id']]
    if (global_events != [event] or event.get('project_id') != project.project_id
            or type(contract.get('signed_tick')) is not int
            or contract['signed_tick'] != event['tick'] or event['tick'] >= scope['tick']
            or data.get('owner_id') != project.owner_id
            or data.get('contractor_id') != scope['contractor_id']
            or data.get('contract_sum') != contract.get('contract_sum')
            or contract.get('contract_sum') != project.contract_sum
            or data.get('contract_duration') != contract.get('contract_duration')
            or contract.get('contract_duration') != project.performance.planned_duration):
        raise TaskConflict('Supply handoff changes the original native signature, event or contract terms')
    return {'source': 'actual_earlier_native_contract_awarded', 'project_id': project.project_id,
            'owner_id': project.owner_id, 'contractor_id': scope['contractor_id'],
            'receiving_organization_id': organization_id, 'read_tick': scope['tick'],
            'signed_tick': contract['signed_tick'], 'contract_sum': contract['contract_sum'],
            'amount_unit': 'native_contract_sum_unit', 'currency': None,
            'contract_duration': contract['contract_duration'], 'contract_sha256': task_digest(contract),
            'event_id': event['event_id'], 'source_event_sha256': task_digest(event)}
