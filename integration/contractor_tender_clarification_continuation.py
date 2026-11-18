"""Consume an actual authorized QS reply in an explicit new micro package version.

This records private source provenance, never a formal tender amendment ledger.
The original clarify result and package remain immutable.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

from integration.bindings.gba_v1_tender_clarification import _channel, _observed, _saved_claim, _original
from integration.contractor_tender_clarification_response import _response_binding, _saved_response
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


def _key(reader, context):
    return 'contractor_clarification_consumption:' + task_digest([
        reader.settings.snapshot_sha256, context.model_dump(mode='json')])


def response_consumption(reader, context, snapshot):
    """Read source provenance and recheck the exact actual native reply, without replay."""
    expected_ref = snapshot.get('clarification_evidence_ref')
    if expected_ref is None:
        return None
    store = reader.assembly.client.tasks
    with store._lock:
        row = store._db.execute('SELECT value FROM metadata WHERE key=?', (_key(reader, context),)).fetchone()
    if row is None:
        raise TaskConflict('Revised package source requires actual authorized reply consumption before reading')
    body = json.loads(row[0])
    expected = {'context_sha256': task_digest(context.model_dump(mode='json')),
        'base_snapshot_sha256': task_digest(snapshot), 'source_file_sha256': reader.settings.snapshot_sha256,
        'organization_id': snapshot['projection']['organization_id'], 'run_id': context.run_id,
        'schema_version': 'contractor-clarification-consumption.v1'}
    if (any(body.get(k) != v for k, v in expected.items())
            or body.get('record_sha256') != task_digest({k:v for k,v in body.items() if k!='record_sha256'})
            or body['evidence']['ref'] != expected_ref):
        raise TaskConflict('Clarification consumption changed its original source, recipient or read point')
    from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
    request = AgentProposalRequestV1.model_validate(body['native_request'])
    proxy = SimpleNamespace(assembly=reader.assembly, store=store)
    manager, session, qs_id, opening_sha = _channel(proxy, request)
    binding = body['response_binding']
    if (request.agent.agent_id != expected['organization_id'] or request.inputs['project']['project_id'] != context.scope.ref.id
            or request.metadata['tick'] != context.business_time.offset
            or binding['opening_event_sha256'] != opening_sha or binding['sender_id'] != qs_id
            or binding['recipient_ids'] != [request.agent.agent_id]):
        raise TaskConflict('Clarification consumption substitutes its original actual question recipient or professional')
    claim = _saved_claim(proxy, binding)
    observed = _observed(proxy, manager, session, binding, claim, effect='clarification_response_published')
    if observed['status'] != 'observed' or observed['message_sha256'] != body['response_message_sha256']:
        raise TaskConflict('Clarification response is unknown; revised source stays unavailable')
    identity = TaskIdentity(**binding['metadata']['micro_identity'])
    with store._lock:
        row = store._db.execute('SELECT record FROM qs_procurement_results WHERE task_key=?', (identity.key,)).fetchone()
    saved = None if row is None else json.loads(row[0])
    if (saved is None or identity.organization_id != qs_id or identity.action_id != 'QS-A05' or identity.role != 'QS'
            or saved['record_sha256'] != body['qs_record_sha256']
            or saved['record_sha256'] != task_digest({k:v for k,v in saved.items() if k!='record_sha256'})
            or saved['result_sha256'] != task_digest(saved['result'])
            or saved['source_reading_sha256'] != task_digest(saved['source_reading'])
            or saved['identity'] != identity.as_dict() or store.get(identity)['state'] != 'output_formed'
            or store.get(identity)['output'] != saved['result']
            or saved['result']['kind'] != 'completed' or saved['result']['payload']['choice'] != 'publish_authorized'):
        raise TaskConflict('Clarification consumption lacks the original finalized professional permission')
    qs_context = ActionContext.model_validate(json.loads(store._db.execute(
        'SELECT record FROM invocation_snapshots WHERE task_key=?', (identity.key,)).fetchone()[0])['context'])
    reader.organizations.grants(qs_context, 'QS-A05', 'QS')
    EvidenceRecord.model_validate(body['evidence'])
    return deepcopy(body)


def publish_response_consumption(*, application, request, plan, screening, identity, response):
    """Authorize only the declared quantity question; all other terms stay identical."""
    application._check()
    _, original_id, _, _, _, proposal = _original(application, request)
    if (identity != original_id or proposal['state'] != 'processing'
            or request.metadata['tick'] != application.assembly.engine.current_tick):
        raise TaskConflict('Clarification consumption needs the original still-open current native request')
    request, qs_id, qs_saved, _, question, _ = _saved_response(application, request)
    actual = application.query_clarification_response(request)
    if (actual != response or actual['status'] != 'observed'
            or actual['message']['metadata']['answer_kind'] != 'quantity_and_measurement'
            or actual['message']['metadata']['requirement_refs'] != [q['requirement_ref'] for q in question['message']['metadata']['questions']]
            or identity.as_dict() != question['micro_identity']):
        raise TaskConflict('Revised package needs its exact actually observed original QS quantity response')
    continuation = plan.clarification_continuation
    reader = application.host.pipeline.assembler.provider.provider
    contexts = [continuation.screening_publication.source_context, continuation.screening_context]
    old_context = plan.screening_publication.source_context
    old_snapshot = reader._snapshots[task_digest(old_context.model_dump(mode='json'))]
    old = reader._resolved_snapshot(old_context, old_snapshot)['projection']['objects']
    old_terms, = [r['value'] for r in old if r['ref'] == plan.screening_publication.terms_ref.model_dump(mode='json')]
    new_snapshot = reader._snapshots[task_digest(contexts[0].model_dump(mode='json'))]
    new = reader._resolved_snapshot(contexts[0], new_snapshot)['projection']['objects']
    new_terms, = [r['value'] for r in new if r['ref'] == continuation.screening_publication.terms_ref.model_dump(mode='json')]
    before, after = deepcopy(old_terms), deepcopy(new_terms)
    for field in ('ref','package_ref','invitation_ref'):
        previous, current = before.pop(field), after.pop(field)
        if (previous['kind'],previous['id']) != (current['kind'],current['id']) or previous['version']==current['version']:
            raise TaskConflict('Clarification revision requires explicit new versions of the same package, terms and invitation')
    answered = actual['message']['metadata']['requirement_refs']
    if before.pop('clarification_requirement_refs') != answered or after.pop('clarification_requirement_refs'):
        raise TaskConflict('Clarification revision cannot remove unrelated or unanswered requirements')
    new_evidence = continuation.response_evidence_ref.model_dump(mode='json')
    if after.pop('terms_evidence_refs') != [*before.pop('terms_evidence_refs'),new_evidence]:
        raise TaskConflict('Clarification revision must explicitly read the actual response evidence')
    # The quantity question changes no price, scope, resources, deadline or
    # business permission. Only the resource Requirement reference advances
    # with its unchanged definition to the new package version.
    for old_demand, new_demand in zip(before['resource_demands']['value'], after['resource_demands']['value']):
        old_ref, new_ref = old_demand['requirement_ref'], new_demand['requirement_ref']
        old_row, = [r['value'] for r in old if r['ref']==old_ref]
        new_row, = [r['value'] for r in new if r['ref']==new_ref]
        if (old_ref['kind'],old_ref['id']) != (new_ref['kind'],new_ref['id']) or old_ref['version']==new_ref['version']:
            raise TaskConflict('Clarification revision changes its original resource requirement identity')
        for key in ('ref','package_ref'): old_row= {k:v for k,v in old_row.items() if k!=key};new_row={k:v for k,v in new_row.items() if k!=key}
        if old_row != new_row: raise TaskConflict('Quantity response cannot change original resource demand definitions')
        new_demand['requirement_ref'] = old_ref
    if before != after:
        raise TaskConflict('Quantity clarification cannot change unrelated original tender terms')
    manager, session, binding = _response_binding(application, request)
    evidence = EvidenceRecord(ref=continuation.response_evidence_ref, source_kind='synthetic',basis_kind='observed',
        locator='native-clarification-response:'+actual['message_sha256'], content_hash=task_digest({
            'response_message_sha256':actual['message_sha256'],'qs_record_sha256':qs_saved['record_sha256'],
            'original_screening_identity':identity.as_dict(),'previous_package_ref':screening.action_input.package_ref.model_dump(mode='json'),
            'next_package_ref':continuation.screening_inputs.package_ref.model_dump(mode='json')}),
        effective_window=screening.reading.resolve(screening.action_input.package_ref).participation_window.value)
    records=[]
    for context in contexts:
        snapshot=reader._snapshots[task_digest(context.model_dump(mode='json'))]
        grants=application.organizations.grants(context,'CONTRACTOR-A01','Contractor')
        permitted={r.key() for g in grants for r in g.readable_refs}&{r.key() for r in context.visible_refs}
        if (snapshot.get('clarification_evidence_ref')!=new_evidence or evidence.ref.key() not in permitted
                or task_digest(context.model_dump(mode='json')) in reader._served_contexts
                or any(r['ref']==new_evidence for r in snapshot['projection']['objects'])):
            raise TaskConflict('Clarification source needs a preauthorized unread context and new evidence reference')
        body={'schema_version':'contractor-clarification-consumption.v1','run_id':context.run_id,
            'organization_id':request.agent.agent_id,'context_sha256':task_digest(context.model_dump(mode='json')),
            'base_snapshot_sha256':task_digest(snapshot),'source_file_sha256':reader.settings.snapshot_sha256,
            'native_request':request.model_dump(mode='json'),'original_screening_identity':identity.as_dict(),
            'qs_record_sha256':qs_saved['record_sha256'],'response_message_sha256':actual['message_sha256'],
            'response_binding':binding,'evidence':evidence.model_dump(mode='json'),
            'previous_package_ref':screening.action_input.package_ref.model_dump(mode='json'),
            'next_package_ref':continuation.screening_inputs.package_ref.model_dump(mode='json')}
        body['record_sha256']=task_digest(body);records.append((context,body))
    with application.store._transaction():
        for context,body in records:
            if application.store._db.execute('SELECT 1 FROM metadata WHERE key=?',(_key(reader,context),)).fetchone():
                raise TaskConflict('Original clarification consumption cannot be replaced or repeated')
            application.store._db.execute('INSERT INTO metadata VALUES (?,?)',(_key(reader,context),canonical(body)))
    return deepcopy(records[0][1])


def effective_screening(application, trigger):
    """Authenticate the later screening without discarding the original clarify result."""
    if 'screening_successor_identity' not in trigger:
        return trigger['screening_identity'], trigger['screening_result_sha256']
    from integration.contractor_tender_request_sources import TenderRequestSourcesSettings
    request=application.selector._request(trigger['native_request'])
    plans=[p for p in TenderRequestSourcesSettings.model_validate(application.settings.request_work_settings).requests
        if p.request_sha256==task_digest(request.model_dump(mode='json')) or p.request_binding=='current_native_request'
        and (p.organization_id,p.project_id,p.tick)==(request.agent.agent_id,request.inputs['project']['project_id'],request.metadata['tick'])]
    if len(plans)!=1 or plans[0].clarification_continuation is None:
        raise TaskConflict('Screening successor lacks its original declared clarification continuation')
    continuation=plans[0].clarification_continuation
    reader=application.host.pipeline.assembler.provider.provider
    context=continuation.screening_publication.source_context
    snapshot=reader._snapshots[task_digest(context.model_dump(mode='json'))]
    body=response_consumption(reader,context,snapshot)
    identity=TaskIdentity(**trigger['screening_successor_identity'])
    saved=application.screening_worker.get_record(identity)
    invocation=application.screening_worker.snapshots.get(identity)
    response=application.query_clarification_response(request)
    if (body['record_sha256']!=trigger.get('clarification_consumption_sha256')
            or body['original_screening_identity']!=trigger['screening_identity']
            or invocation['context']!=continuation.screening_context.model_dump(mode='json')
            or invocation['action_input']!=continuation.screening_inputs.model_dump(mode='json')
            or identity.request_id!='screening-after-clarification:'+request.request_id
            or identity.organization_id!=request.agent.agent_id
            or saved is None or saved['result']['kind']!='completed'
            or application.store.get(identity)['state']!='output_formed'
            or application.store.get(identity)['output']!=saved['result']
            or saved['result_sha256']!=trigger.get('screening_successor_result_sha256')
            or response['status']!='observed' or response['message_sha256']!=body['response_message_sha256']
            or not any(r['ref']==body['evidence']['ref'] and r['projection']==body['evidence'] for r in saved['source_reading'])):
        raise TaskConflict('Screening successor lost its original reply, source evidence or completed result')
    return identity.as_dict(),saved['result_sha256']
