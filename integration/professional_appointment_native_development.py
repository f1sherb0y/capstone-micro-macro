"""Explicit synthetic A03 sources, frozen before native appointments exist."""
from copy import deepcopy

from integration.contractor_tender_development import _write, ref, known


def appointment_plans(*, professional_plans, grants, incompatible_first_roles=()):
    plans = []
    first_tick=min(p['tick'] for p in professional_plans)
    for before in professional_plans:
        org, role = before['organization_id'], before['role']
        tag = before['context']['operation_id'] + '-confirmation'
        context = deepcopy(before['context'])
        context.update(operation_id=tag, contract_ref=ref('ActionContract', role.upper() + '-A03'),
            task_ref=ref('DecisionTask', tag), read_token=tag + '-read', candidate_set_ref=ref('CandidateSet', tag))
        grant = grants[org]
        grant['action_ids'].append(role.upper() + '-A03')
        grant['action_ids'] = sorted(set(grant['action_ids']))
        objects = deepcopy(before['objects'])
        rows = {r['ref']['kind']: r['value'] for r in objects}
        request = rows['ServiceRequest']
        terms = rows['ServiceTerms']
        basis = grant['basis_refs'][0]
        native, acceptance_evidence = ref('Evidence', tag + '-received-native'), ref('Evidence', tag + '-accepted-a02')

        def put(reference, **value):
            objects.append({'ref': reference, 'value': {'ref': reference, **value}})

        for evidence in (native, acceptance_evidence):
            put(evidence, source_kind='synthetic', basis_kind='observed',
                locator='professional-appointment-development:actual-reception:' + tag,
                content_hash=None, effective_window=terms['effective_window'])
        function = context['function_ref']
        acceptance_ref = ref('RecordedDecision', tag + '-acceptance')
        appointment_ref = ref('Appointment', tag)
        put(acceptance_ref, evidence_refs=[acceptance_evidence], action_id=role.upper() + '-A02',
            actor_id=context['actor_id'], organization_id=org, function_ref=function, authority_ref=grant['ref'],
            scope=terms['scope'], request_ref=request['ref'], accepted_terms_ref=terms['ref'],
            terms_digest=None, choice='accept', decided_at=context['business_time'], received_at=context['business_time'])
        appointment = {'evidence_refs': [native, acceptance_evidence, basis], 'scope': terms['scope'],
            'request_ref': request['ref'], 'terms_ref': terms['ref'], 'terms_digest': None,
            'acceptance_ref': acceptance_ref, 'relation': terms['relation'],
            'capacity_ref': before['action_input']['capacity_ref'], 'function_refs': [function],
            'function_authority_refs': [grant['ref']], 'reservation_ref': None, 'amendment_target_refs': [],
            'compatibility': 'review', 'received_at': context['business_time'],
            'effective_window': terms['effective_window'], 'status': 'selected', 'service_relationship_ref': None}
        if role in incompatible_first_roles and before['tick']==first_tick:
            # An independent initial detailed compatibility declaration. The
            # native appointment remains selected; this is neither a withdrawal
            # nor an A03 result fabricated before its original processor runs.
            detail=ref('Evidence',tag+'-independent-detail-incompatibility')
            from src.coordination.tasks import task_digest
            put(detail,source_kind='synthetic',basis_kind='assumed',
                locator='initial-detailed-appointment-incompatibility-not-native-withdrawal',
                content_hash=task_digest({'scope':terms['scope'],'provider_id':org,
                    'compatibility':'decline_incompatible','initial_source':True}),effective_window=terms['effective_window'])
            appointment['compatibility']='decline_incompatible'
            appointment['evidence_refs'].append(detail)
            if role!='Architect':
                target=ref('EvidenceTarget',tag+'-compatible-terms-question')
                response=ref('ResponseRequirement',tag+'-compatible-terms-response')
                put(response,evidence_refs=[detail],request_ref=request['ref'],scope=terms['scope'],recipient_ids=[request['client_id']])
                put(target,evidence_refs=[detail],request_ref=request['ref'],scope=terms['scope'],
                    question='Please provide compatible detailed terms for the selected appointment.',
                    recipient_ids=[request['client_id']],blocking_uses=[],response_requirement_ref=response)
                appointment['amendment_target_refs']=[target]
        for name in ('provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
                     'payer_id', 'payer_organization_id', 'client_authority_ref', 'payer_authority_ref'):
            appointment[name] = deepcopy(request[name])
        action_input = {'scope': terms['scope'], 'appointment_ref': appointment_ref,
            'accepted_terms_ref': terms['ref'], 'function_refs': [function]}
        if role == 'Architect':
            action_input['existing_reservation_ref'] = None
        elif role == 'Engineer':
            appointment.update(capability_ref=before['action_input']['capability_ref'], independence_check_ref=None)
            action_input.update(independence_check_ref=None, reservation_ref=None)
        else:
            calendar = deepcopy(rows['ResourceCalendar'])
            calendar['ref'] = ref('ResourceCalendar', tag + '-calendar')
            for resource in calendar['resources']:
                resource.update(personnel_ids=known([org + '-synthetic-person']), suitable=known(True))
            objects.append({'ref': calendar['ref'], 'value': calendar})
            check = deepcopy(rows['ConflictCheck'])
            check.update(ref=ref('ConflictCheck', tag + '-conflict'), author_actor_id=context['actor_id'],
                author_function_ref=function, authority_ref=grant['ref'])
            objects.append({'ref': check['ref'], 'value': check})
            appointment.update(capacity_ref=calendar['ref'], capability_ref=before['action_input']['capability_ref'],
                conflict_check_ref=check['ref'], task_refs=[], existing_allocation_refs=[], prior_plan_ref=None)
            action_input.update(task_refs=[], capacity_ref=calendar['ref'], work_profile_ref=terms['work_profile_ref'],
                existing_allocation_refs=[])
        put(appointment_ref, **appointment)
        put(context['candidate_set_ref'], operation_id=tag, scope=terms['scope'], as_of=context['business_time'],
            candidates=[{'ref': appointment_ref, 'permitted_choices': ['confirm', 'request_amendment']
                + (['decline_incompatible'] if role == 'Architect' else [])}],
            search_profile_ref=ref('Profile', tag + '-received-only'))
        objects[-1]['value'].pop('ref')
        context['visible_refs'] = [r['ref'] for r in objects]
        if role == 'QS':
            old_refs = [before['action_input']['capacity_ref'], before['action_input']['conflict_check_ref']]
            context['visible_refs'] = [r for r in context['visible_refs'] if r not in old_refs]
        grant['readable_refs'].extend(context['visible_refs'])
        plans.append({'organization_id': org, 'role': role, 'project_id': before['project_id'], 'tick': before['tick'],
            'context': context, 'action_input': action_input, 'objects': objects,
            'native_evidence_ref': native, 'acceptance_evidence_ref': acceptance_evidence})
    return plans


def write_appointment_sources(directory, *, run_id, plans, grants):
    from integration.professional_appointment_native import COMPONENTS, ProfessionalAppointmentPlan
    from src.actions.contracts.common import Reference
    for plan in plans:
        for row in plan['objects']:
            if row['ref']['kind'] == 'Authorization':
                row['value'] = deepcopy(grants[row['value']['organization_id']])
        ProfessionalAppointmentPlan.model_validate(plan)
        schemas = COMPONENTS[plan['role']][0].SOURCE_SCHEMAS()
        for row in plan['objects']:
            value = deepcopy(row['value'])
            if row['ref']['kind'] == 'Evidence' and value['content_hash'] is None:
                value['content_hash'] = '0' * 64  # Schema validation only, never written as observed evidence.
            if row['ref']['kind'] in {'Appointment', 'RecordedDecision'}:
                value['terms_digest'] = '0' * 64
            # Original QS intake has a less detailed calendar/check schema.
            # These retained old versions are checked by A02's own closed schema.
            if plan['role'] == 'QS' and row['ref']['kind'] == 'ResourceCalendar' and row['ref'] != plan['action_input']['capacity_ref']:
                from src.actions.contracts.service_objects import ServiceResourceCalendarView
                ServiceResourceCalendarView.model_validate(value)
            elif plan['role'] == 'QS' and row['ref']['kind'] == 'ConflictCheck' and 'author_actor_id' not in value:
                from src.actions.contracts.qs_objects import QSConflictCheckView
                QSConflictCheckView.model_validate(value)
            else:
                schemas.validate_projection(Reference.model_validate(row['ref']), value)
    return {'version': '1', **_write(directory, 'professional-appointment-input.json',
        {'schema_version': 'professional-appointment-input.v1', 'run_id': run_id, 'plans': plans})}
