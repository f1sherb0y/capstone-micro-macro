"""Authenticate current native request/delay lineage, without detailed payment facts."""
from copy import deepcopy
import math

from src.coordination.tasks import TaskConflict, task_digest


def payment_trigger_origin(assembly, *, event, organization_id):
    assembly._validate_components()
    engine, client = assembly.engine, assembly.client
    role = client.organization_roles.get(organization_id)
    project = engine.projects.get(event.project_id)
    if (event.event_type not in {'payment_requested','payment_delayed'} or project is None
            or type(event.tick) is not int or not 1 <= event.tick <= engine.current_tick
            or role not in {'Owner','Contractor','QS'}):
        raise TaskConflict('Payment trigger requires its actual native project, party and recorded clock')
    party = {'Owner':project.owner_id,'Contractor':project.selected_contractor_id,'QS':project.selected_qs_id}[role]
    if party != organization_id:
        raise TaskConflict('Payment trigger is private to its original project recipient')

    def business(value):
        value = deepcopy(value)
        diagnostics = value['data'].pop('agent_observer_errors', [])
        if not isinstance(diagnostics,list) or any(not isinstance(v,str) for v in diagnostics):
            raise TaskConflict('Payment trigger has invalid native observer diagnostics')
        return value

    def logged(original):
        global_rows = [(i,e) for i,e in enumerate(engine.events.events) if e.event_id == original.event_id]
        local_rows = [e for e in project.event_log if e['event_id'] == original.event_id]
        value = business(original.model_dump(mode='json'))
        if (not original.event_id or len(global_rows) != 1 or len(local_rows) != 1
                or value != business(global_rows[0][1].model_dump(mode='json'))
                or value != business(local_rows[0]) or original.project_id != project.project_id):
            raise TaskConflict('Payment trigger lost its exact native event and project log')
        return global_rows[0][0],value

    def authenticate(original):
        position,value=logged(original)
        data = value['data']
        amount = data.get('payment_amount')
        actor = data.get('contractor_id' if original.event_type == 'payment_requested' else 'owner_id')
        if (data.get('owner_id') != project.owner_id
                or data.get('contractor_id') != project.selected_contractor_id
                or client.organization_roles.get(data.get('owner_id')) != 'Owner'
                or client.organization_roles.get(data.get('contractor_id')) != 'Contractor'
                or original.agent_id != actor or type(amount) not in {int,float}
                or not math.isfinite(amount) or amount < 0):
            raise TaskConflict('Payment trigger changes its actual native parties, actor or request amount')
        return position, value

    index, value = authenticate(event)
    if event.event_type == 'payment_requested':
        request = event
    else:
        matches = [e for e in engine.events.events[:index]
            if e.event_type == 'payment_requested' and e.project_id == event.project_id and e.tick == event.tick
            and all(e.data.get(k) == event.data.get(k) for k in ('owner_id','contractor_id','payment_amount'))]
        if len(matches) != 1:
            raise TaskConflict('Payment delay needs exactly one earlier actual request for this native occurrence')
        request, = matches
    request_index, request_value = authenticate(request)
    status = request.data.get('payment_status')
    progress = request.data.get('certified_progress')
    if (status not in {'approved','delayed'}
            or event.event_type == 'payment_delayed' and status != 'delayed'
            or type(progress) not in {int,float} or not math.isfinite(progress) or not 0 <= progress <= 1):
        raise TaskConflict('Payment trigger has inconsistent actual request status or aggregate progress')
    # Keep actual earlier business transitions in this project's payment origin.
    # An initial contract/selection alone supplies no runtime execution event.
    signatures=[];selections=[]
    for prior in engine.events.events[:request_index]:
        if prior.project_id!=project.project_id or prior.event_type not in {'contract_awarded','supplier_selected'}:
            continue
        _, original=logged(prior)
        data=original['data']
        if prior.tick>request.tick or data.get('contractor_id')!=project.selected_contractor_id:
            raise TaskConflict('Payment lineage changes its original earlier contractor or clock')
        row={'event_id':prior.event_id,'tick':prior.tick,'source_event_sha256':task_digest(original)}
        if prior.event_type=='contract_awarded':
            contracts=[c for c in project.contracts if c.get('contractor_id')==project.selected_contractor_id
                and c.get('signed_tick')==prior.tick]
            if (len(contracts)!=1 or prior.agent_id!=project.selected_contractor_id
                    or data.get('owner_id')!=project.owner_id
                    or data.get('contract_sum')!=contracts[0].get('contract_sum')
                    or data.get('contract_duration')!=contracts[0].get('contract_duration')):
                raise TaskConflict('Payment lineage lost its actual native signed contract')
            row['contract_sha256']=task_digest(contracts[0]);signatures.append(row)
        else:
            supplier=data.get('supplier_id')
            if (prior.agent_id!=supplier or client.organization_roles.get(supplier)!='Supplier'
                    or supplier not in project.selected_supplier_ids):
                raise TaskConflict('Payment lineage lost its actual native supplier selection')
            row['supplier_id']=supplier;selections.append(row)
    if len(signatures)>1:
        raise TaskConflict('Payment lineage needs one original native signature for this scope')
    return {'request_event_id':request.event_id, 'request_source_event_sha256':task_digest(request_value),
        'delay_event_id':event.event_id if event.event_type == 'payment_delayed' else None,
        'trigger_source_event_sha256':task_digest(value),'native_request_status':status,
        'earlier_native_signature':signatures[0] if signatures else None,
        'earlier_native_supplier_selections':selections,
        'boundary':'One actual aggregate request occurrence. A delay is not another payment; '
            'approved is not an independent QS certificate, transfer, received cash or cleared debt.'}
