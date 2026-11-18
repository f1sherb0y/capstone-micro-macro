"""Send original QS bid questions through the existing native tender session.

Publication proves communication only. Answers, revised bids, admissibility and
scores require their own original decisions and received sources.
"""
from copy import deepcopy

from integration.bindings.gba_v1_tender_clarification import _observed, _publish_once, _saved_claim
from integration.qs_evaluation_outcome_query import original_authorized_round
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def _original(parent, identity, *, organization_id, tick):
    plan, record, saved = original_authorized_round(parent, identity,
        organization_id=organization_id, tick=tick, require_native_result=False)
    payload = saved['result']['payload']
    if (payload.get('choice') != 'clarify' or payload.get('scope') != plan.context.scope.model_dump(mode='json')
            or not payload.get('questions')):
        raise TaskConflict('Bid questions require the original completed scoped QS-A06 clarification')
    sources = {Reference.model_validate(r['ref']).key(): r['projection'] for r in saved['source_reading']}
    questions = []
    seen = set()
    for question in payload['questions']:
        targets = question['target_refs']
        if len(targets) != 1:
            raise TaskConflict('Bid question changes its original explicit evidence target')
        ref = Reference.model_validate(targets[0])
        source = sources.get(ref.key())
        if (ref.kind != 'EvidenceTarget' or ref.key() in seen or source is None
                or source.get('round_ref') != plan.action_input['round_ref']
                or source.get('document_ref') != plan.action_input['procurement_document_ref']
                or question['scope'] != payload['scope']
                or question['question'] != source['question']
                or question['recipient_ids'] != source['recipient_ids']
                or question['blocking_uses'] != source['blocking_uses']
                or question['response_requirement_ref'] != source['response_requirement_ref']):
            raise TaskConflict('Bid question substitutes original wording, recipients, document or round')
        seen.add(ref.key())
        questions.append(deepcopy(question))
    return plan, record, saved, questions


def _channel(parent, plan):
    engine = parent.assembly.engine
    project = engine.projects.get(plan.project_id)
    manager = engine.lifecycle_engine.interaction_sessions
    sessions = [s for s in manager.by_project(plan.project_id) if s.session_type == 'tender_clarification']
    if project is None or project.selected_qs_id != plan.organization_id or len(sessions) != 1:
        raise TaskConflict('QS bid questions require their actually appointed QS and existing native session')
    session = sessions[0]
    openings = [e for e in engine.events.events if e.event_type == 'tender_clarification_session_started'
        and e.project_id == plan.project_id and e.data.get('session_id') == session.session_id]
    if (len(openings) != 1 or session.metadata.get('owner_id') != project.owner_id
            or session.metadata.get('qs_id') != plan.organization_id
            or project.flags.get('interaction_sessions', {}).get('tender_clarification') != session.session_id
            or not {project.owner_id, plan.organization_id, *[b.contractor_id for b in plan.bids]}
                <= set(session.participants)):
        raise TaskConflict('QS bid question channel changes its original native project or participants')
    return manager, session, task_digest(openings[0].model_dump(mode='json'))


def _open_channel(parent, plan, project):
    """Use the original lifecycle's session creator only during a current send.

    Initial independently declared invitations can bypass native shortlisting;
    in that case the original creator has not yet run. Queries never call it.
    """
    lifecycle = parent.assembly.engine.lifecycle_engine
    sessions = [s for s in lifecycle.interaction_sessions.by_project(plan.project_id)
        if s.session_type=='tender_clarification']
    if sessions:
        return _channel(parent, plan)
    contractors = [b.contractor_id for b in plan.bids]
    if (project.selected_qs_id != plan.organization_id or project.current_stage.value!='bid_evaluation'
            or set(contractors)!={b['contractor_id'] for b in project.bids}):
        raise TaskConflict('Bid session creation needs the actual appointed QS and complete submitted bidder set')
    lifecycle._start_interaction_session(project,plan.tick,
        session_type='tender_clarification',participants=[project.owner_id,plan.organization_id,*contractors],
        event_type='tender_clarification_session_started',
        description='Appointed QS opened bid clarification for actually submitted bids',
        messages=[],agent_id=plan.organization_id,
        metadata={'owner_id':project.owner_id,'qs_id':plan.organization_id,
            'contractor_ids':contractors,'session_scope':'submitted_bid_clarification'})
    return _channel(parent, plan)


def _binding(parent, identity, plan, record, saved, questions):
    manager, session, opening = _channel(parent, plan)
    recipients = []
    for question in questions:
        for actor_id in question['recipient_ids']:
            matches = [org for org in session.participants
                if org in parent.assembly.client.organization_roles
                and parent.bindings.organizations.get(org).actor_id == actor_id]
            if len(matches) != 1:
                raise TaskConflict('Bid question recipient lacks its exact registered native organization')
            if matches[0] not in recipients:
                recipients.append(matches[0])
    # Each question must retain its own permitted recipients. A multi-question
    # publication is allowed only when the original recipient sets coincide.
    if any(set(q['recipient_ids']) != set(questions[0]['recipient_ids']) for q in questions):
        raise TaskConflict('Different bid question audiences require separate original publication decisions')
    binding = {'schema_version': 'gba-qs-bid-question-send.v1',
        'session_id': session.session_id, 'opening_event_sha256': opening,
        'sender_id': plan.organization_id, 'recipient_ids': recipients, 'tick': plan.tick,
        'topic': 'bid_clarification',
        'content': '\n'.join(q['question'] for q in questions),
        'metadata': {'schema_version': 'gba-qs-bid-question.v1',
            'run_id': identity.run_id, 'simulation_id': parent.assembly.client.simulation_id,
            'project_id': plan.project_id, 'micro_identity': identity.as_dict(),
            'request_sha256': task_digest(record['native_request']),
            'publication_key': task_digest([q['target_refs'] for q in questions]),
            'micro_result_sha256': saved['result_sha256'],
            'round_ref': deepcopy(plan.action_input['round_ref']),
            'document_ref': deepcopy(plan.action_input['procurement_document_ref']),
            'questions': deepcopy(questions)}}
    return manager, session, binding


def _bindings(parent, identity, plan, record, saved, questions):
    audiences = {}
    for question in questions:
        audiences.setdefault(tuple(sorted(question['recipient_ids'])), []).append(question)
    return [_binding(parent, identity, plan, record, saved, rows) for rows in audiences.values()]


def query_bid_clarification_review(parent, identity, *, organization_id, tick):
    """Read an original private question decision and any actual send; never send."""
    identity = identity if isinstance(identity, TaskIdentity) else TaskIdentity(**identity)
    with parent.bindings.read_guard():
        plan, record, saved, questions = _original(parent, identity,
            organization_id=organization_id, tick=tick)
        publications = []
        for manager, session, binding in _bindings(parent, identity, plan, record, saved, questions):
            with parent.worker.store._lock:
                claim = _saved_claim(parent, binding)
            publications.append(_observed(parent, manager, session, binding, claim,
                effect='bid_clarification_questions_published'))
        result = {'schema_version': 'qs-bid-clarification-review.v1',
            'status': 'waiting_input', 'organization_id': organization_id,
            'queried_at_tick': tick, 'original_decision_identity': identity.as_dict(),
            'micro_result_sha256': saved['result_sha256'], 'questions': questions,
            'publications': publications, 'answers_received': False,
            'native_evaluation_complete': False,
            'condition_code': 'original_bidder_answers_and_authorized_new_evaluation',
            'limits': 'An actual question is not an answer, revised bid, admissibility finding, score or award.'}
        result['query_sha256'] = task_digest(result)
        return deepcopy(result)


def publish_bid_clarification_questions(parent, identity, request):
    """Publish once inside the original pending evaluation call, with explicit opt-in."""
    identity = identity if isinstance(identity, TaskIdentity) else TaskIdentity(**identity)
    with parent.bindings.read_guard():
        if not parent.settings.publish_native_bid_questions:
            raise TaskConflict('Native QS bid question publication requires explicit initial configuration')
        plan, project, scope = parent._current(request)
        plan_, record, saved, questions = _original(parent, identity,
            organization_id=plan.organization_id, tick=parent.assembly.engine.current_tick)
        _, _, _, proposal_id = parent.assembly.client._invocation_identity('propose', request)
        proposal = parent.worker.store.get(proposal_id)
        if (plan_ != plan or record['native_request'] != request.model_dump(mode='json')
                or proposal['state'] != 'processing' or parent.assembly.engine.current_tick != plan.tick):
            raise TaskConflict('Bid question publication lost its exact current native request or pending call')
        _open_channel(parent, plan, project)
        return [_publish_once(parent, manager, session, binding,
            effect='bid_clarification_questions_published')
            for manager, session, binding in _bindings(parent, identity, plan, record, saved, questions)]
