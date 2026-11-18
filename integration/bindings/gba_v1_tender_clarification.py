"""Original A01 questions through the existing native clarification channel.

A message proves communication only. Neither opening the channel nor sending
a question resolves a requirement, revises a package or forms a native bid.
"""
from copy import deepcopy
from dataclasses import asdict
import json

from integration.bank_financing_private import checked_result
from src.actions.contracts.common import ActionContext, Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


def _original(application, raw_request):
    from integration.contractor_tender_request_trigger import read_request_record

    application._check()
    request = application.selector._request(raw_request)
    trigger = read_request_record(application=application, organization_id=request.agent.agent_id,
        request_id=request.request_id)
    if trigger['native_request'] != request.model_dump(mode='json') or 'screening_identity' not in trigger:
        raise TaskConflict('Clarification requires its exact received original request and screening')
    identity = TaskIdentity(**trigger['screening_identity'])
    if (identity.organization_id != request.agent.agent_id or identity.action_id != 'CONTRACTOR-A01'
            or identity.purpose != 'action' or identity.request_id != 'screening:' + request.request_id):
        raise TaskConflict('Clarification substitutes its original screening identity')
    worker, _ = application._execution_components(identity.action_id)
    saved = checked_result(worker, identity)
    snapshot = worker.snapshots.get(identity)
    context = ActionContext.model_validate(snapshot['context'])
    grants = application.organizations.grants(context, identity.action_id, identity.role)
    payload = saved['result']['payload']
    requirements = payload.get('requirement_refs')
    if (not grants or grants[0].organization_id != request.agent.agent_id or payload['choice'] != 'clarify'
            or not requirements or payload['package_ref'] != snapshot['action_input']['package_ref']
            or context.scope.kind != 'project' or context.scope.ref.id != request.inputs['project']['project_id']
            or type(request.metadata.get('tick')) is not int
            or context.business_time.offset != request.metadata['tick']
            or trigger.get('screening_result_sha256') != saved['result_sha256']):
        raise TaskConflict('Only the authorized original completed clarification can request answers')
    permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
    permitted &= {ref.key() for ref in context.visible_refs}
    if Reference.model_validate(payload['package_ref']).key() not in permitted:
        raise TaskConflict('Clarification no longer has its original package read permission')
    sources = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved['source_reading']}
    package = sources.get(Reference.model_validate(payload['package_ref']).key())
    if package is None or package.get('clarification_requirement_refs') != requirements:
        raise TaskConflict('Clarification result changes its original unresolved package requirements')
    questions = []
    for reference in requirements:
        ref = Reference.model_validate(reference)
        source = sources.get(ref.key())
        if (ref.kind != 'Requirement' or ref.key() not in permitted or source is None
                or source.get('package_ref') != payload['package_ref']):
            raise TaskConflict('Clarification question exceeds its original source or current read authority')
        questions.append({'requirement_ref': reference, 'description': source['description']})
    if len({Reference.model_validate(q['requirement_ref']).key() for q in questions}) != len(questions):
        raise TaskConflict('Clarification duplicates an original requirement')
    client = application.assembly.client
    _, _, _, proposal_id = client._invocation_identity('propose', request)
    proposal = application.store.get(proposal_id)
    return request, identity, saved, context, questions, proposal


def _channel(application, request):
    engine = application.assembly.engine
    project = engine.projects.get(request.inputs['project']['project_id'])
    if project is None:
        raise TaskConflict('Clarification has no actual original native project')
    manager = engine.lifecycle_engine.interaction_sessions
    sessions = [s for s in manager.by_project(project.project_id) if s.session_type == 'tender_clarification']
    if len(sessions) != 1:
        raise TaskConflict('Clarification requires its existing native session; never create a substitute')
    session = sessions[0]
    qs_id = project.selected_qs_id
    qs = engine.agents.get(qs_id)
    openings = [e for e in engine.events.events if e.event_type == 'tender_clarification_session_started'
        and e.project_id == project.project_id and e.data.get('session_id') == session.session_id]
    if (qs is None or qs.role != 'QS' or len(openings) != 1
            or project.flags.get('interaction_sessions', {}).get('tender_clarification') != session.session_id
            or not {project.owner_id, qs_id, request.agent.agent_id} <= set(session.participants)
            or session.metadata.get('owner_id') != project.owner_id or session.metadata.get('qs_id') != qs_id
            or request.agent.agent_id not in session.metadata.get('contractor_ids', [])):
        raise TaskConflict('Clarification channel changes its actual original project, QS or participants')
    return manager, session, qs_id, task_digest(openings[0].model_dump(mode='json'))


def _binding(application, request, identity, saved, context, questions, session, qs_id, opening_sha256):
    metadata = {'schema_version': 'gba-tender-clarification-question.v1',
        'run_id': application.store.run_id, 'simulation_id': application.assembly.client.simulation_id,
        'request_sha256': task_digest(request.model_dump(mode='json')), 'request_id': request.request_id,
        'micro_identity': identity.as_dict(), 'micro_result_sha256': saved['result_sha256'],
        'micro_record_sha256': saved['record_sha256'], 'package_ref': saved['result']['payload']['package_ref'],
        'questions': questions, 'business_time': context.business_time.model_dump(mode='json'),
        'status': 'requested'}
    content = 'Clarification requested for ' + metadata['package_ref']['id'] + ':\n' + '\n'.join(
        '- ' + q['description'] for q in questions)
    return {'schema_version': 'gba-tender-clarification-send.v1', 'metadata': metadata,
        'session_id': session.session_id, 'opening_event_sha256': opening_sha256,
        'sender_id': request.agent.agent_id, 'recipient_ids': [qs_id], 'tick': request.metadata['tick'],
        'topic': 'tender_clarification', 'content': content}


def _key(binding):
    prefixes = {'gba-tender-clarification-send.v1': 'gba_tender_clarification_request:',
        'gba-tender-clarification-response-send.v1': 'gba_tender_clarification_response:',
        'gba-final-account-position-send.v1': 'gba_final_account_position:',
        'gba-contractor-final-account-position-send.v1': 'gba_contractor_final_account_position:',
        'gba-final-account-question-send.v1': 'gba_final_account_question:',
        'gba-qs-bid-question-send.v1': 'gba_qs_bid_question:'}
    identity = binding['metadata']['micro_identity']
    if binding['schema_version']=='gba-qs-bid-question-send.v1':
        identity = [identity,binding['metadata']['publication_key']]
    return prefixes[binding['schema_version']] + task_digest(identity)


def _saved_claim(application, binding):
    row = application.store._db.execute('SELECT value FROM metadata WHERE key=?', (_key(binding),)).fetchone()
    if row is None:
        return None
    claim = json.loads(row[0])
    if (not isinstance(claim, dict) or set(claim) != {'binding', 'phase', 'message', 'record_sha256'}
            or claim['binding'] != binding or claim['phase'] not in {'sending', 'published'}
            or claim['record_sha256'] != task_digest({k: v for k, v in claim.items() if k != 'record_sha256'})
            or (claim['phase'] == 'sending') != (claim['message'] is None)):
        raise TaskConflict('Original clarification send evidence changed; never resend unknown work')
    return claim


def _observed(application, manager, session, binding, claim, *, effect='clarification_requested'):
    result = {'status': 'outcome_unknown', 'effect': None, 'request_sha256': binding['metadata']['request_sha256'],
        'micro_identity': deepcopy(binding['metadata']['micro_identity']),
        'macro_current_tick': application.assembly.engine.current_tick, 'request_tick': binding['tick'],
        'requirements_resolved': False, 'resubmitted': False}
    if claim is None:
        return result
    messages = []
    for message in session.messages:
        raw = asdict(message)
        if (raw['metadata'] == binding['metadata'] and all(raw[name] == binding[name]
                for name in ('session_id', 'sender_id', 'recipient_ids', 'tick', 'topic', 'content'))):
            if not any(envelope.payload is message and envelope.message_type == 'InteractionMessage'
                    and envelope.project_id == session.project_id and envelope.session_id == session.session_id
                    and envelope.tick == binding['tick'] for envelope in manager.message_bus.peek()):
                raise TaskConflict('Clarification lacks its actual native bus publication')
            messages.append(raw)
    if not messages:
        return result  # The bounded session may no longer retain the message.
    if len(messages) != 1 or claim['message'] is not None and claim['message'] != messages[0]:
        raise TaskConflict('Clarification query found conflicting original messages')
    result.update(status='observed', effect=effect, message=messages[0],
        message_sha256=task_digest(messages[0]), send_claim_sha256=claim['record_sha256'])
    return result


def _publish_once(application, manager, session, binding, *, effect):
    """Shared technical send intent; the caller authenticates the actual sender."""
    with application.store._transaction():
        prior = _saved_claim(application, binding)
        if prior is None:
            claim = {'binding': binding, 'phase': 'sending', 'message': None}
            claim['record_sha256'] = task_digest(claim)
            application.store._db.execute('INSERT INTO metadata VALUES (?,?)', (_key(binding), canonical(claim)))
    if prior is not None:
        return deepcopy(_observed(application, manager, session, binding, prior, effect=effect))
    message = manager.append_message(session, **{name: binding[name] for name in
        ('tick', 'sender_id', 'recipient_ids', 'topic', 'content')}, metadata=deepcopy(binding['metadata']))
    with application.store._transaction():
        if _saved_claim(application, binding) != claim:
            raise TaskConflict('Original clarification claim changed during native publication')
        claim.update(phase='published', message=asdict(message))
        claim['record_sha256'] = task_digest({k: v for k, v in claim.items() if k != 'record_sha256'})
        application.store._db.execute('UPDATE metadata SET value=? WHERE key=?', (canonical(claim), _key(binding)))
    return deepcopy(_observed(application, manager, session, binding, claim, effect=effect))


def query_clarification_request(application, raw_request):
    """Query the exact own question, including uncertain sends; never send or answer."""
    with application.read_guard():
        request, identity, saved, context, questions, _ = _original(application, raw_request)
        manager, session, qs_id, opening_sha = _channel(application, request)
        binding = _binding(application, request, identity, saved, context, questions, session, qs_id, opening_sha)
        with application.store._lock:
            claim = _saved_claim(application, binding)
        return deepcopy(_observed(application, manager, session, binding, claim))


def publish_clarification_request(application, raw_request, identity, prepared):
    """Send once inside the original waiting native call, using completed original A01."""
    with application.read_guard():
        if not application.settings.publish_native_clarification_requests:
            raise TaskConflict('Native clarification questions require explicit original configuration')
        request, original, saved, context, questions, proposal = _original(application, raw_request)
        if (identity != original or proposal['state'] != 'processing'
                or request.metadata.get('tick') != application.assembly.engine.current_tick
                or application.validate_invocation(application.store.get(original), prepared) is not True):
            raise TaskConflict('Clarification publishing requires its original still-waiting current invocation')
        manager, session, qs_id, opening_sha = _channel(application, request)
        binding = _binding(application, request, original, saved, context, questions, session, qs_id, opening_sha)
        # A failure after append_message is uncertain. The helper's durable intent
        # prohibits replay; an explicit query can inspect the actual native bus.
        return _publish_once(application, manager, session, binding, effect='clarification_requested')
