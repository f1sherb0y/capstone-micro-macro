"""Original Owner/Contractor positions through the existing native final-account room.

The native message is a communication receipt, never a settlement, cash
execution, revised contract or discharge of obligations. No room is created.
"""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

from integration.bank_financing_private import checked_result
from integration.bindings.gba_v1_tender_clarification import _observed, _publish_once, _saved_claim
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


TOPIC = 'micro_owner_final_account_position'
QUESTION_TOPIC = 'micro_qs_final_account_question'
CONTRACTOR_TOPIC = 'micro_contractor_final_account_position'


def _channel(assembly, project_id):
    engine = assembly.engine
    project = engine.projects.get(project_id)
    if project is None:
        raise TaskConflict('Final-account communication requires its original native project')
    manager = engine.lifecycle_engine.interaction_sessions
    rooms = [s for s in manager.by_project(project_id) if s.session_type == 'final_account_dispute']
    if len(rooms) != 1:
        raise TaskConflict('Final-account communication requires its existing native dispute room')
    room = rooms[0]
    openings = [e for e in engine.events.events if e.project_id == project_id
        and e.event_type == 'final_account_dispute_session_started' and e.data.get('session_id') == room.session_id]
    parties = {project.owner_id, project.selected_contractor_id, project.selected_qs_id} - {None}
    if (len(openings) != 1 or openings[0].tick > engine.current_tick
            or project.flags.get('interaction_sessions', {}).get('final_account_dispute') != room.session_id
            or not parties <= set(room.participants)
            or any(room.metadata.get(k) != v for k, v in (
                ('owner_id', project.owner_id), ('contractor_id', project.selected_contractor_id),
                ('qs_id', project.selected_qs_id)))):
        raise TaskConflict('Final-account room lost its actual opening, parties or native project binding')
    logged = [e for e in project.event_log if e['event_id'] == openings[0].event_id]
    if len(logged) != 1 or task_digest(logged[0]) != task_digest(openings[0].model_dump(mode='json')):
        raise TaskConflict('Final-account room opening lost its exact original project event')
    return project, manager, room, task_digest(logged[0])


def _binding(application, plan_id):
    application.check()
    plan = application._by_id[plan_id]
    if plan.final_account_disclosure is None:
        raise TaskConflict('Final-account publication requires explicit choice-and-note disclosure')
    original = application.query_saved_result(plan_id)
    if original['status'] != 'saved' or original['task_state'] != 'output_formed':
        raise TaskConflict('Final-account publication requires its original formed private position result')
    record = application._record(plan)
    identity = TaskIdentity(**record['identity'])
    saved = checked_result(application._actions[plan_id][1], identity)
    project, manager, room, opening = _channel(application.assembly, plan.project_id)
    payload = saved['result']['payload']
    recipients = list(plan.final_account_disclosure.recipient_ids)
    client = application.assembly.client
    if identity.action_id == 'OWN-A06':
        sender, role, choices = project.owner_id, 'Owner', {'dispute', 'negotiate'}
        roles = {project.selected_contractor_id: 'Contractor', project.selected_qs_id: 'QS'}
        schema, transport_schema, topic = 'gba-final-account-position.v1', 'gba-final-account-position-send.v1', TOPIC
        if plan.final_account_owner_reception is not None:
            _check_quoted_recipients(room, application._record(plan)['observed']['data']['received_qs_question']['messages'], recipients)
    elif identity.action_id == 'CONTRACTOR-A11':
        sender, role, choices = project.selected_contractor_id, 'Contractor', {'propose_final_account', 'respond_settlement'}
        roles = {project.owner_id: 'Owner', project.selected_qs_id: 'QS'}
        schema, transport_schema, topic = ('gba-contractor-final-account-position.v1',
            'gba-contractor-final-account-position-send.v1', CONTRACTOR_TOPIC)
        procedures = [r['projection'] for r in saved['source_reading'] if r['ref']['kind'] == 'HandoverProcedure']
        contracts = [r['projection'] for r in saved['source_reading'] if r['ref']['kind'] == 'Contract']
        if (len(procedures) != 1 or not set(recipients) <= set(procedures[0]['recipient_ids'])
                or len(contracts) != 1 or contracts[0]['client_id'] != project.owner_id
                or contracts[0]['contractor_id'] != sender):
            raise TaskConflict('Contractor position disclosure exceeds its original closeout procedure recipients')
        if plan.final_account_position_reception is not None:
            _check_quoted_recipients(room, record['observed']['data']['received_owner_position']['messages'], recipients)
    else:
        raise TaskConflict('Final-account position requires the original Owner-A06 or Contractor-A11 result')
    if (identity.organization_id != sender or client.organization_roles.get(sender) != role
            or payload['choice'] not in choices
            or any(r not in roles or client.organization_roles.get(r) != roles[r] for r in recipients)
            or not set(recipients) <= set(room.participants)):
        raise TaskConflict('Final-account position changes its original sender, choice or explicit actual recipients')
    # Native recipients receive only the expressly disclosed position. Private
    # account/obligation refs, source readings and full task identity stay local.
    marker = task_digest([client.simulation_id, plan.plan_id, identity.key, saved['result_sha256']])
    metadata = {'schema_version': schema,
        'request_sha256': marker, 'micro_identity': {'disclosure_id': marker},
        'position': payload['choice'], 'boundary': 'communication_only_not_payment_or_settlement'}
    binding = {'schema_version': transport_schema, 'metadata': metadata,
        'session_id': room.session_id, 'opening_event_sha256': opening, 'sender_id': sender,
        'recipient_ids': recipients, 'tick': plan.tick, 'topic': topic,
        'content': payload['choice'] + ': ' + payload['note']}
    transport = SimpleNamespace(assembly=application.assembly, store=client.tasks)
    return plan, transport, manager, room, binding


def _receipt(result):
    return {k: deepcopy(v) for k, v in result.items() if k not in {
        'requirements_resolved', 'resubmitted', 'macro_current_tick'}} | {
        'boundary': 'Native communication only; no settlement, payment, revised terms or obligation release.'}


def query_final_account_position(application, plan_id):
    """Read retained native publication only; absence never authorizes resend."""
    with application.authority.read_guard():
        _, transport, manager, room, binding = _binding(application, plan_id)
        with transport.store._lock:
            claim = _saved_claim(transport, binding)
        return _receipt(_observed(transport, manager, room, binding, claim, effect='final_account_position_communicated'))


def publish_final_account_position(application, plan_id):
    """Publish once in the current actual review, reusing durable native transport."""
    with application.authority.read_guard():
        plan, transport, manager, room, binding = _binding(application, plan_id)
        project = application.assembly.engine.projects[plan.project_id]
        if application.assembly.engine.current_tick != plan.tick or project.current_stage.value != 'final_account':
            raise TaskConflict('Final-account publication cannot start from a historical or closed review')
        return _receipt(_publish_once(transport, manager, room, binding, effect='final_account_position_communicated'))


def read_final_account_positions(assembly, *, organization_id, project_id, tick, read_guard):
    """Read original native messages addressed to this actual Contractor or QS."""
    return _read_messages(assembly, organization_id=organization_id, project_id=project_id,
        tick=tick, read_guard=read_guard, topic=TOPIC)


def read_final_account_questions(assembly, *, organization_id, project_id, tick, read_guard):
    """Read actual addressed QS questions as this native project's Owner."""
    return _read_messages(assembly, organization_id=organization_id, project_id=project_id,
        tick=tick, read_guard=read_guard, topic=QUESTION_TOPIC)


def read_contractor_final_account_positions(assembly, *, organization_id, project_id, tick, read_guard):
    """Read only actual addressed Contractor choice/note, without its private items."""
    return _read_messages(assembly, organization_id=organization_id, project_id=project_id,
        tick=tick, read_guard=read_guard, topic=CONTRACTOR_TOPIC)


def _read_messages(assembly, *, organization_id, project_id, tick, read_guard, topic):
    with read_guard():
        assembly._validate_components()
        project, manager, room, _ = _channel(assembly, project_id)
        role = assembly.client.organization_roles.get(organization_id)
        if topic == TOPIC:
            allowed_roles = {'Contractor': project.selected_contractor_id, 'QS': project.selected_qs_id}
            sender, schema = project.owner_id, 'gba-final-account-position.v1'
        elif topic == QUESTION_TOPIC:
            allowed_roles = {'Owner': project.owner_id}
            sender, schema = project.selected_qs_id, 'gba-final-account-question.v1'
        elif topic == CONTRACTOR_TOPIC:
            allowed_roles = {'Owner': project.owner_id, 'QS': project.selected_qs_id}
            sender, schema = project.selected_contractor_id, 'gba-contractor-final-account-position.v1'
        else:
            raise TaskConflict('Unsupported native final-account communication topic')
        if (type(tick) is not int or tick != assembly.engine.current_tick
                or role not in allowed_roles or organization_id != allowed_roles[role]):
            raise TaskConflict('Final-account reception requires its current actual native recipient')
        result = []
        for message in room.messages:
            if message.topic != topic or organization_id not in message.recipient_ids or message.tick > tick:
                continue
            raw = asdict(message)
            if (message.sender_id != sender or message.metadata.get('schema_version') != schema
                    or not any(e.payload is message and e.message_type == 'InteractionMessage'
                        and e.project_id == project_id and e.session_id == room.session_id
                        and e.tick == message.tick for e in manager.message_bus.peek())):
                raise TaskConflict('Final-account reception lost its actual original native message/bus publication')
            # Other recipients, private task IDs and sender source records are
            # not part of the receiver's projection.
            result.append({k: deepcopy(raw[k]) for k in ('message_id', 'tick', 'sender_id', 'topic', 'content')})
        return {'project_id': project_id, 'organization_id': organization_id, 'as_of_tick': tick,
            'messages': result, 'boundary': 'Received communication only; not evidence supplied, agreed settlement or cash.'}


def receive_owner_position_for_question(application, plan):
    """Project actual addressed communication into an explicitly authorized QS question.

    This reads the native recipient view only. It never opens the sender's
    private result or treats a disputed communication as determined facts.
    """
    reception = plan.final_account_question_reception
    project = application.assembly.engine.projects[plan.project_id]
    question, = [r['value'] for r in plan.objects
        if r['ref'] == reception.question_ref.model_dump(mode='json')]
    if (application.assembly.client.organization_roles.get(plan.organization_id) != 'QS'
            or question.get('recipient_ids') != [project.owner_id]):
        raise TaskConflict('Received Owner-position question must belong to the actual QS and address that Owner only')
    received = read_final_account_positions(application.assembly, organization_id=plan.organization_id,
        project_id=plan.project_id, tick=application.assembly.engine.current_tick,
        read_guard=application.authority.read_guard)
    messages = _select_received(received, reception.message_tick, index=reception.message_index)
    return {'project_id': plan.project_id, 'organization_id': plan.organization_id,
        'message_tick': reception.message_tick, 'messages': messages,
        'boundary': received['boundary']}


def _select_received(received, tick, *, index=None):
    """An explicit native message ordinal stays stable when later rounds append."""
    messages = [m for m in received['messages'] if m['tick'] == tick]
    if index is not None:
        messages = messages[index:index + 1]
    if len(messages) != 1:
        raise TaskConflict('Final-account reception requires one actual addressed message at its declared tick and ordinal')
    return messages


def receive_qs_question_for_owner(application, plan):
    """Read the Owner's actual addressed question; never the QS private result."""
    if application.assembly.client.organization_roles.get(plan.organization_id) != 'Owner':
        raise TaskConflict('QS-question payment discussion belongs to the actual Owner only')
    reception = plan.final_account_owner_reception
    received = read_final_account_questions(application.assembly, organization_id=plan.organization_id,
        project_id=plan.project_id, tick=application.assembly.engine.current_tick,
        read_guard=application.authority.read_guard)
    return {'project_id': plan.project_id, 'organization_id': plan.organization_id,
        'message_tick': reception.message_tick, 'messages': _select_received(received, reception.message_tick),
        'boundary': received['boundary']}


def receive_owner_position(application, plan):
    """Use the recipient's native communication, never the sender's private ledger."""
    if plan.final_account_position_reception is None:
        return receive_owner_position_for_question(application, plan)
    if application.assembly.client.organization_roles.get(plan.organization_id) != 'Contractor':
        raise TaskConflict('Owner-position closeout reception belongs to the actual Contractor only')
    project=application.assembly.engine.projects[plan.project_id]
    contracts=[r['value'] for r in plan.objects if r['ref']==plan.action_input['contract_ref']]
    if (len(contracts)!=1 or contracts[0]['client_id']!=project.owner_id
            or contracts[0]['contractor_id']!=plan.organization_id):
        raise TaskConflict('Owner-position reception changes the original Contractor contract parties')
    reception = plan.final_account_position_reception
    received = read_final_account_positions(application.assembly, organization_id=plan.organization_id,
        project_id=plan.project_id, tick=application.assembly.engine.current_tick,
        read_guard=application.authority.read_guard)
    messages = [m for m in received['messages'] if m['tick'] == reception.message_tick]
    if len(messages) != 1:
        raise TaskConflict('Contractor closeout requires one actual addressed Owner position at its declared tick')
    return {'project_id': plan.project_id, 'organization_id': plan.organization_id,
        'message_tick': reception.message_tick, 'messages': messages, 'boundary': received['boundary']}


def receive_contractor_position_for_question(application, plan):
    """Bind actual Contractor communication into the original QS evidence question."""
    if application.assembly.client.organization_roles.get(plan.organization_id) != 'QS':
        raise TaskConflict('Contractor-position evidence question belongs to the actual QS only')
    reception = plan.final_account_question_reception
    received = read_contractor_final_account_positions(application.assembly, organization_id=plan.organization_id,
        project_id=plan.project_id, tick=application.assembly.engine.current_tick,
        read_guard=application.authority.read_guard)
    messages = _select_received(received, reception.contractor_message_tick, index=reception.contractor_message_index)
    project,_,room,_=_channel(application.assembly,plan.project_id)
    _check_quoted_recipients(room,messages,[project.owner_id])
    return {'project_id': plan.project_id, 'organization_id': plan.organization_id,
        'message_tick': reception.contractor_message_tick, 'messages': messages, 'boundary': received['boundary']}


def _check_quoted_recipients(room, messages, recipients):
    """Quoting a received position must not widen its actual audience."""
    for projected in messages:
        originals=[m for m in room.messages if m.message_id==projected['message_id']]
        if len(originals)!=1 or not set(recipients)<=set(originals[0].recipient_ids)|{originals[0].sender_id}:
            raise TaskConflict('Final-account quoting exceeds the original native communication audience')


def _question_binding(application, plan_id):
    application.check()
    plan = application._by_id[plan_id]
    if plan.final_account_question_reception is None or not plan.final_account_question_reception.publish_question_text:
        raise TaskConflict('Native QS question requires explicit original question-text disclosure')
    original = application.query_saved_result(plan_id)
    if original['status'] != 'saved' or original['task_state'] != 'output_formed':
        raise TaskConflict('Native QS question requires its completed original QS result')
    identity = TaskIdentity(**application._record(plan)['identity'])
    saved = checked_result(application._actions[plan_id][1], identity)
    payload = saved['result']['payload']
    project, manager, room, opening = _channel(application.assembly, plan.project_id)
    questions = payload.get('questions', [])
    if (identity.action_id != 'QS-A09' or identity.organization_id != project.selected_qs_id
            or application.assembly.client.organization_roles.get(identity.organization_id) != 'QS'
            or payload['choice'] != 'request_evidence' or len(questions) != 1
            or questions[0]['recipient_ids'] != [project.owner_id]
            or questions[0]['target_refs'] != [plan.final_account_question_reception.question_ref.model_dump(mode='json')]
            or not {project.owner_id, identity.organization_id} <= set(room.participants)):
        raise TaskConflict('Native QS question changes its original action, recipient, target or actual project parties')
    marker = task_digest([application.assembly.client.simulation_id, plan_id, identity.key, saved['result_sha256']])
    metadata = {'schema_version': 'gba-final-account-question.v1', 'request_sha256': marker,
        'micro_identity': {'disclosure_id': marker}, 'boundary': 'question_only_not_supplied_evidence_or_settlement'}
    binding = {'schema_version': 'gba-final-account-question-send.v1', 'metadata': metadata,
        'session_id': room.session_id, 'opening_event_sha256': opening, 'sender_id': identity.organization_id,
        'recipient_ids': [project.owner_id], 'tick': plan.tick, 'topic': QUESTION_TOPIC,
        'content': questions[0]['question']}
    return plan, SimpleNamespace(assembly=application.assembly, store=application.assembly.client.tasks), manager, room, binding


def query_final_account_question(application, plan_id):
    """Query original native publication; absence never authorizes resend."""
    with application.authority.read_guard():
        _, transport, manager, room, binding = _question_binding(application, plan_id)
        with transport.store._lock:
            claim = _saved_claim(transport, binding)
        return _receipt(_observed(transport, manager, room, binding, claim, effect='final_account_question_communicated'))


def publish_final_account_question(application, plan_id):
    """Publish original QS question text once in the actual current review room."""
    with application.authority.read_guard():
        plan, transport, manager, room, binding = _question_binding(application, plan_id)
        project = application.assembly.engine.projects[plan.project_id]
        if application.assembly.engine.current_tick != plan.tick or project.current_stage.value != 'final_account':
            raise TaskConflict('Final-account question cannot start from a historical or closed review')
        return _receipt(_publish_once(transport, manager, room, binding, effect='final_account_question_communicated'))
