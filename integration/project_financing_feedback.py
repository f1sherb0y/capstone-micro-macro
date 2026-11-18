"""Own financing feedback and authenticated historical selection sources.

Selection and an indicative approved offer are not disbursement or cash.
"""
from copy import deepcopy

from src.coordination.tasks import TaskConflict, task_digest


def project_financing_event(observation, organization_roles):
    if not observation.committed or not isinstance(organization_roles, dict):
        return {}
    data = observation.data
    recipients = {}
    if observation.event_type == 'bank_financing_decision':
        if organization_roles.get(observation.agent_id) != 'Bank':
            return {}
        fields = ('owner_id', 'requested_amount', 'approved_amount', 'interest_rate', 'conditions',
                  'action_type', 'accepted', 'native_financing_scope', 'proposal_response_sha256',
                  'micro_action_id', 'micro_task_key', 'micro_result_sha256')
        recipients[observation.agent_id] = {k: deepcopy(data[k]) for k in fields if k in data}
    elif observation.event_type in {'project_financing_selected', 'project_financing_deferred'}:
        if organization_roles.get(observation.agent_id) != 'Owner':
            return {}
        fields = ('financing_mode', 'selected_bank_id', 'requested_amount', 'action_type', 'accepted',
                  'native_financing_scope', 'proposal_response_sha256',
                  'micro_action_id', 'micro_task_key', 'micro_result_sha256')
        recipients[observation.agent_id] = {k: deepcopy(data[k]) for k in fields if k in data}
        bank = data.get('selected_bank_id')
        if observation.event_type == 'project_financing_selected' and organization_roles.get(bank) == 'Bank':
            recipients[bank] = {'owner_id': observation.agent_id, 'selected_bank_id': bank,
                'financing_mode': data.get('financing_mode'), 'selected': True,
                'native_financing_scope': deepcopy(data.get('native_financing_scope'))}
    else:
        return {}
    return {org: {'event_type': observation.event_type, 'tick': observation.tick,
        'project_id': observation.project_id, 'agent_id': observation.agent_id, 'committed': True, 'data': own}
        for org, own in recipients.items()}


def own_financing_history(assembly, *, organization_id, tick, read_guard,
        include_current=False, decision_task_key=None):
    """Read strictly earlier actual selections, checking the original event/tasks."""
    if not callable(read_guard):
        raise TaskConflict('Financing history requires the original host engine guard')
    if type(include_current) is not bool or (decision_task_key is not None
            and (not isinstance(decision_task_key, str) or not decision_task_key)):
        raise TaskConflict('Financing outcome selection requires explicit current-time policy and original key')
    with read_guard():
        assembly._validate_components()
        engine, client = assembly.engine, assembly.client
        if (type(tick) is not int or tick != engine.current_tick
                or client.organization_roles.get(organization_id) not in {'Owner', 'Bank'}):
            raise TaskConflict('Financing history changes its current native clock or own organization')
        origins = []
        for row in client.inbox.for_organization(run_id=client.run_id, organization_id=organization_id):
            own = row['payload']
            if (own['event_type'] not in {'project_financing_selected', 'project_financing_deferred'} or own['tick'] > tick
                    or own['tick'] == tick and not include_current):
                continue
            if decision_task_key is not None and own['data'].get('micro_task_key') != decision_task_key:
                continue
            project = engine.projects.get(own['project_id'])
            events = [] if project is None else [e for e in project.event_log if e['event_id'] == row['event_id']]
            if len(events) != 1:
                raise TaskConflict('Financing history lost its original native selection event')
            event = events[0]
            global_events=[e.model_dump(mode='json') for e in engine.events.events if e.event_id==row['event_id']]
            def business(value):
                value=deepcopy(value)
                errors=value['data'].pop('agent_observer_errors',[])
                if not isinstance(errors,list) or any(not isinstance(e,str) for e in errors):
                    raise TaskConflict('Financing history has invalid native observer diagnostics')
                return value
            if len(global_events)!=1 or business(global_events[0])!=business(event):
                raise TaskConflict('Financing history lost its unique original global selection event')
            from gba_construction_sim.backend.agents.contracts import AgentObservationV1
            expected = project_financing_event(AgentObservationV1.model_validate(event), client.organization_roles)
            if (event['event_type'] not in {'project_financing_selected', 'project_financing_deferred'} or event['agent_id'] != project.owner_id
                    or organization_id not in expected or task_digest(own) != task_digest(expected[organization_id])):
                raise TaskConflict('Financing history substitutes its original event or recipient projection')
            scope = {'project_id': project.project_id, 'owner_id': project.owner_id, 'tick': event['tick']}
            if event['data'].get('native_financing_scope') != scope:
                raise TaskConflict('Financing history lost its original decision scope')
            owner_tasks = client.tasks.for_organization(run_id=client.run_id, organization_id=project.owner_id)
            proposal = [t for t in owner_tasks if t['identity']['purpose'] == 'propose'
                and t['identity']['action_id'] == 'select_financing_offer' and t['state'] == 'output_formed'
                and t['output'].get('factors', {}).get('native_financing_scope') == scope]
            final = [t for t in owner_tasks if t['identity']['purpose'] == 'decide'
                and t['identity']['action_id'] == 'owner_financing_selection' and t['state'] == 'output_formed'
                and t['output'].get('data', {}).get('native_financing_scope') == scope]
            accepted_banks={e['agent_id'] for e in project.event_log if e['event_type']=='bank_financing_decision'
                and e['tick']==event['tick'] and e['data'].get('accepted') is True}
            # Keep old frozen-runtime failures readable without assigning that
            # failed outcome to new, explicitly accepted equity selections.
            legacy_equity_rejection=(event['event_type']=='project_financing_selected'
                and event['data'].get('financing_mode')=='owner_equity'
                and event['data'].get('selected_bank_id') is None and bool(accepted_banks)
                and event['data'].get('choice_source')=='invalid_llm_choice_rejected')
            if (len(proposal) != 1 or len(final) != 1
                    or final[0]['output']['data'].get('proposal_response_sha256') != task_digest(proposal[0]['output'])
                    or event['data'].get('proposal_response_sha256') != task_digest(proposal[0]['output'])
                    or final[0]['output']['decision'] != proposal[0]['output']['accepted']
                    or event['data'].get('accepted') != (final[0]['output']['decision'] and not legacy_equity_rejection)
                    or event['data'].get('action_type')!=final[0]['output']['action_type']
                    or event['data'].get('action_type')!=proposal[0]['output']['action_type']
                    or final[0]['output']['data'].get('selected_bank_id') != proposal[0]['output']['data'].get('selected_bank_id')
                    or final[0]['output']['data'].get('selected_bank_id') != event['data'].get('selected_bank_id')):
                raise TaskConflict('Financing history lost its formed original proposal or final choice')
            mode=event['data'].get('financing_mode')
            selected=event['data'].get('selected_bank_id')
            deferred=event['event_type']=='project_financing_deferred'
            if (mode not in {'owner_equity','bank_finance','unfinanced'}
                    or (mode in {'owner_equity','unfinanced'})!=(selected is None)
                    or (mode=='unfinanced')!=deferred or deferred and event['data'].get('accepted') is not False
                    or selected is not None and client.organization_roles.get(selected)!='Bank'
                    or selected is not None and selected not in accepted_banks
                    or proposal[0]['output']['data'].get('financing_mode')!=mode
                    or final[0]['output']['data'].get('financing_mode')!=mode):
                raise TaskConflict('Financing history changes its actual equity or bank selection mode')
            micro = {}
            fields = ('micro_action_id', 'micro_task_key', 'micro_result_sha256')
            if any(k in event['data'] for k in fields):
                if (event['data'].get('micro_action_id') != 'OWN-A05'
                        or any(not event['data'].get(k) or event['data'][k] != proposal[0]['output']['factors'].get(k)
                               or event['data'][k] != final[0]['output']['data'].get(k) for k in fields)):
                    raise TaskConflict('Financing history changes its original micro result linkage')
                # The selected Bank's projection deliberately excludes Owner's
                # internal task identity. Only its owning receiver gets it.
                if organization_id == project.owner_id:
                    micro = {k: event['data'][k] for k in fields}
            origins.append({'event_id': row['event_id'], 'project_id': project.project_id, 'tick': event['tick'],
                'recipient_organization_id': organization_id, 'owner_id': project.owner_id,
                'selected_bank_id': selected,'financing_mode':mode,
                'native_accepted':event['data']['accepted'],'native_choice_source':event['data'].get('choice_source'),
                'proposal_response_sha256': task_digest(proposal[0]['output']),
                'final_response_sha256': task_digest(final[0]['output']), **micro})
        if len({row['event_id'] for row in origins}) != len(origins):
            raise TaskConflict('Financing history repeats one actual selection')
        return sorted(origins, key=lambda row: (row['tick'], row['project_id'], row['event_id']))
