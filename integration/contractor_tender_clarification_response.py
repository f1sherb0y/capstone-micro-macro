"""Original QS-A05 publication decisions answering explicit quantity questions.

The saved professional decision and actual message are distinct evidence. A
published response does not revise a Contractor package or complete its bid.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Annotated, Literal

from pydantic import Field

from integration.action_versions import prepared_action_execution_versions
from integration.bank_financing_private import evidence_binding
from integration.bindings.gba_v1_tender_clarification import (
    _channel, _observed, _original, _publish_once, _saved_claim,
)
from integration.contractor_tender_snapshot_sources import TenderSnapshotObject
from integration.qs_procurement_actions import QSProcurementActionAssembler
from integration.qs_procurement_results import QSProcurementResultWorker
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, ref_type
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class TenderClarificationResponsePlan(StrictRecord):
    answer_kind: Literal['quantity_and_measurement']
    requirement_refs: Annotated[list[ref_type('Requirement')], Field(min_length=1)]
    context: ActionContext
    action_input: dict
    objects: Annotated[list[TenderSnapshotObject], Field(min_length=1)]
    question_evidence_ref: ref_type('Evidence')


def _declared_plan(application, request):
    from integration.contractor_tender_request_sources import TenderRequestSourcesSettings
    config = TenderRequestSourcesSettings.model_validate(application.settings.request_work_settings)
    matches = [p for p in config.requests if p.request_sha256 == task_digest(request.model_dump(mode='json'))
        or p.request_binding == 'current_native_request' and (p.organization_id, p.project_id, p.tick)
            == (request.agent.agent_id, request.inputs['project']['project_id'], request.metadata.get('tick'))]
    if len(matches) != 1 or matches[0].clarification_response is None:
        raise TaskConflict('Clarification response lacks its exact declared independent QS source plan')
    return matches[0].clarification_response.model_copy(deep=True)


def _question_binding(question):
    return {'question_message_sha256': question['message_sha256'],
        'question_micro_identity': question['micro_identity'], 'request_sha256': question['request_sha256']}


class _QSSources:
    def __init__(self, application, request, plan):
        self.application, self.request, self.plan = application, request.model_copy(deep=True), plan.model_copy(deep=True)
        self.plan_sha256 = task_digest(plan.model_dump(mode='json'))

    def project(self, *, context, organization_id, grants):
        app = self.application
        app._check()
        request, _, _, original, _, proposal = _original(app, self.request)
        _, _, qs_id, _ = _channel(app, request)
        current = app.organizations.grants(context, 'QS-A05', 'QS')
        if (task_digest(self.plan.model_dump(mode='json')) != self.plan_sha256
                or context != self.plan.context or context.contract_ref.id != 'QS-A05'
                or context.execution_mode != 'rule' or context.scope != original.scope
                or context.business_time != original.business_time or context.run_id != app.store.run_id
                or app.assembly.engine.current_tick != request.metadata['tick'] or proposal['state'] != 'processing'
                or not current or grants != current or current[0].organization_id != organization_id
                or organization_id != qs_id or context.actor_id != app.organizations.get(qs_id).actor_id):
            raise TaskConflict('QS response sources change the actual question, selected QS, authority or current request')
        question = app.query_clarification_request(request)
        if (question['status'] != 'observed' or self.plan.requirement_refs != [
                Reference.model_validate(q['requirement_ref']) for q in question['message']['metadata']['questions']]):
            raise TaskConflict('QS response requires the exact actual question and its declared requirement set')
        objects = [row.model_dump(mode='json') for row in self.plan.objects]
        evidence_binding(objects, self.plan.question_evidence_ref.model_dump(mode='json'), _question_binding(question))
        return {'run_id': context.run_id, 'macro_version': app.host.pipeline.assembler.macro_version,
            'state_version': task_digest([self.plan_sha256, _question_binding(question)]),
            'read_token': context.read_token, 'business_time': context.business_time.model_dump(mode='json'),
            'organization_id': organization_id, 'objects': objects}


def _saved_review(application, raw_request):
    from integration.contractor_tender_request_trigger import read_request_record
    request, _, _, original, _, _ = _original(application, raw_request)
    plan = _declared_plan(application, request)
    _, _, qs_id, _ = _channel(application, request)
    trigger = read_request_record(application=application, organization_id=request.agent.agent_id, request_id=request.request_id)
    if 'clarification_response_identity' not in trigger:
        raise TaskConflict('Original clarification has no registered QS response; querying never executes missing work')
    identity = TaskIdentity(**trigger['clarification_response_identity'])
    if (identity.organization_id != qs_id or identity.action_id != 'QS-A05' or identity.role != 'QS'
            or identity.purpose != 'action' or identity.request_id != 'clarification-response:' + request.request_id
            or trigger.get('clarification_response_plan_sha256') != task_digest(plan.model_dump(mode='json'))):
        raise TaskConflict('QS response changes its original task, sources or actual selected professional')
    snapshots = application.host.pipeline.worker.snapshots
    snapshot = snapshots.get(identity)
    context = ActionContext.model_validate(snapshot['context'])
    if (context != plan.context or context.scope != original.scope or context.business_time != original.business_time
            or context.execution_mode != 'rule' or snapshot['action_input'] != plan.action_input):
        raise TaskConflict('QS response substitutes its original invocation or source question scope')
    grants = application.organizations.grants(context, 'QS-A05', 'QS')
    pipeline = application.host.pipeline
    runner = ActionRunner(application.registry, organizations=application.organizations,
        methods=pipeline.assembler.methods, policy_version=pipeline.assembler.policy_version,
        model_version=pipeline.worker.model_version)
    versions = prepared_action_execution_versions(SimpleNamespace(context=context, runner=runner),
        client_version=pipeline.worker.client_version, model_version=pipeline.worker.model_version)
    if not grants or grants[0].organization_id != qs_id or versions != identity.versions:
        raise TaskConflict('QS response no longer has its original seven execution versions and current read rights')
    with application.store._lock:
        row = application.store._db.execute('SELECT record FROM qs_procurement_results WHERE task_key=?',
            (identity.key,)).fetchone()
    if row is None:
        raise TaskConflict('QS response lacks its original durable result; no automatic action replay')
    saved = json.loads(row[0])
    QSProcurementResultWorker.validate_saved_record(identity, saved, registry=application.registry, snapshots=snapshots)
    task = application.store.get(identity)
    result = saved['result']
    if result['kind'] == 'completed':
        finalized = (task['state'] == 'output_formed' and task['output'] == result
            and task['output_sha256'] == saved['result_sha256'] and not task['conditions'])
    elif result['kind'] in {'needs_information', 'unsupported', 'deferred'}:
        condition = {'kind': QSProcurementResultWorker.WAIT_KIND,
            'result_kind': result['kind'], 'result_sha256': saved['result_sha256']}
        if result['kind'] == 'needs_information':
            condition.update(missing_fields=result['missing_fields'], requested_refs=result['requested_refs'])
        elif result['kind'] == 'unsupported':
            condition['capability_ref'] = result['capability_ref']
        else:
            condition['resume_condition'] = result['resume_condition']
        finalized = (task['state'] == 'waiting_input' and task['conditions'] == [condition]
            and task['output'] is None and task['output_sha256'] is None)
    else:
        finalized = False
    if not finalized:
        raise TaskConflict('QS review requires its original finalized result or exact unresolved conditions; no recovery by query')
    if task_digest(saved['source_reading']) != saved['source_reading_sha256']:
        raise TaskConflict('QS review changed its original professional source digest')
    sources = {Reference.model_validate(r['ref']).key(): r['projection'] for r in saved['source_reading']}
    if len(sources) != len(saved['source_reading']):
        raise TaskConflict('QS review duplicates an original source reference')
    permitted = {ref.key() for g in grants for ref in g.readable_refs} & {r.key() for r in context.visible_refs}
    if not set(sources) <= permitted:
        raise TaskConflict('QS response has lost current read authority for its original professional sources')
    question = application.query_clarification_request(request)
    if question['status'] != 'observed':
        raise TaskConflict('Original question message is unknown; preserve unresolved QS response')
    if sources[plan.question_evidence_ref.key()].get('content_hash') != task_digest(_question_binding(question)):
        raise TaskConflict('QS response did not consume its exact original native question')
    return request, identity, saved, sources, question, plan


def _saved_response(application, raw_request):
    review = _saved_review(application, raw_request)
    saved = review[2]
    if saved['result']['kind'] != 'completed' or saved['result']['payload']['choice'] != 'publish_authorized':
        raise TaskConflict('QS response requires original finalized publication permission; gaps and requests stay unresolved')
    return review


def query_clarification_review(application, raw_request):
    """Inspect the original private QS review without publishing or resolving it.

    A completed request for publication remains a business wait even though its
    original action task is complete. This query is for the configured host;
    it does not disclose an unpublished document through the native channel.
    """
    with application.read_guard():
        request, identity, saved, _, question, plan = _saved_review(application, raw_request)
        task = application.store.get(identity)
        result = saved['result']
        authorized = result['kind'] == 'completed' and result['payload']['choice'] == 'publish_authorized'
        conditions = [] if authorized else [{
            'kind': 'tender_clarification_review',
            'condition_code': ('original_publication_authority' if result['kind'] == 'completed'
                and result['payload']['choice'] == 'request_publication'
                else 'authorized_qs_quantity_and_measurement_reply'),
            'result_kind': result['kind'], 'result_sha256': saved['result_sha256'],
            'requirement_refs': [r.model_dump(mode='json') for r in plan.requirement_refs],
            'question_message_sha256': question['message_sha256'],
            'original_task_conditions': deepcopy(task['conditions']),
        }]
        review = {'schema_version': 'tender-clarification-review.v1',
            'run_id': application.store.run_id,
            'simulation_id': application.assembly.client.simulation_id,
            'request_id': request.request_id, 'request_sha256': task_digest(request.model_dump(mode='json')),
            'status': 'publication_authorized' if authorized else 'waiting_input',
            'micro_identity': identity.as_dict(), 'micro_record_sha256': saved['record_sha256'],
            'micro_result_sha256': saved['result_sha256'], 'original_result': deepcopy(result),
            'original_task_state': task['state'], 'waiting_conditions': conditions,
            'question_message_sha256': question['message_sha256'],
            'requirements_resolved': False, 'resubmitted': False}
        review['review_sha256'] = task_digest(review)
        return review


def _response_binding(application, raw_request):
    request, identity, saved, sources, question, plan = _saved_response(application, raw_request)
    manager, session, qs_id, opening_sha = _channel(application, request)
    payload = saved['result']['payload']
    document = sources[Reference.model_validate(payload['document_ref']).key()]
    draft = document['draft']
    quantity = sources[Reference.model_validate(draft['quantity_schedule_ref']).key()]
    rule = sources[Reference.model_validate(draft['measurement_rule_ref']).key()]
    if draft['open_questions'] or any(line['quantity']['state'] != 'known' for line in quantity['lines']):
        raise TaskConflict('Unresolved or provisional quantities cannot answer a declared known-quantity question')
    details = {'document_ref': payload['document_ref'], 'publication_basis_ref': payload['publication_basis_ref'],
        'quantity_schedule_ref': quantity['ref'], 'measurement_rule_ref': rule['ref'],
        'supported_units': rule['supported_units'], 'lines': quantity['lines']}
    metadata = {'schema_version': 'gba-tender-clarification-response.v1',
        'run_id': application.store.run_id, 'simulation_id': application.assembly.client.simulation_id,
        'request_id': request.request_id, 'request_sha256': task_digest(request.model_dump(mode='json')),
        'micro_identity': identity.as_dict(), 'micro_result_sha256': saved['result_sha256'],
        'micro_record_sha256': saved['record_sha256'], **_question_binding(question),
        'requirement_refs': [r.model_dump(mode='json') for r in plan.requirement_refs],
        'answer_kind': plan.answer_kind, 'published_source': details, 'status': 'professional_response'}
    content = 'Authorized procurement quantity and measurement response: ' + json.dumps(details, ensure_ascii=False, sort_keys=True)
    binding = {'schema_version': 'gba-tender-clarification-response-send.v1', 'metadata': metadata,
        'session_id': session.session_id, 'opening_event_sha256': opening_sha,
        'sender_id': qs_id, 'recipient_ids': [request.agent.agent_id], 'tick': request.metadata['tick'],
        'topic': 'tender_clarification_response', 'content': content}
    return manager, session, binding


def respond_to_clarification(application, raw_request, *, register_response):
    """Run original QS publication once and communicate its actual authorized facts."""
    with application.read_guard():
        request, _, _, _, _, proposal = _original(application, raw_request)
        if proposal['state'] != 'processing' or application.assembly.engine.current_tick != request.metadata['tick']:
            raise TaskConflict('QS response execution requires the original still-open current native request')
        plan = _declared_plan(application, request)
        provider = _QSSources(application, request, plan)
        pipeline = application.host.pipeline
        assembler = QSProcurementActionAssembler(registry=application.registry, organizations=application.organizations,
            provider=provider, macro_version=pipeline.assembler.macro_version, source_mode='formal',
            methods=pipeline.assembler.methods, policy_version=pipeline.assembler.policy_version,
            model_version=pipeline.worker.model_version)
        prepared = assembler.build(plan.context, **plan.action_input)

        def validate(row, invocation):
            if invocation is not prepared or row != application.store.get(TaskIdentity(**row['identity'])):
                return False
            projection = assembler._views.assemble(prepared.context, 'QS-A05', 'QS')
            actual = {r.ref.key(): r.value.model_dump(mode='json') for r in projection.objects}
            return all(actual.get(Reference.model_validate(r['ref']).key()) == r['projection']
                for r in prepared.reading.evidence())

        def validate_wait(row, result, conditions):
            typed = application.registry.get('QS-A05').contract.result_adapter.validate_python(result)
            return (validate(row, prepared) and typed.kind in {'needs_information', 'unsupported', 'deferred'}
                and len(conditions) == 1 and conditions[0].get('kind') == QSProcurementResultWorker.WAIT_KIND
                and conditions[0].get('result_kind') == typed.kind
                and conditions[0].get('result_sha256') == task_digest(typed.model_dump(mode='json')))

        worker = QSProcurementResultWorker(store=application.store, snapshots=pipeline.worker.snapshots,
            registry=application.registry, client_version=pipeline.worker.client_version,
            model_version=pipeline.worker.model_version, validate_invocation=validate, validate_wait=validate_wait)
        identity = worker.register(prepared, request_id='clarification-response:' + request.request_id)
        register_response(identity, task_digest(plan.model_dump(mode='json')))
        worker.execute(identity, prepared)
        review = query_clarification_review(application, request)
        if review['status'] == 'waiting_input':
            return review
        manager, session, binding = _response_binding(application, request)
        return _publish_once(application, manager, session, binding, effect='clarification_response_published')


def query_clarification_response(application, raw_request):
    """Read saved original QS evidence and the exact own reply; never run QS work."""
    with application.read_guard():
        manager, session, binding = _response_binding(application, raw_request)
        with application.store._lock:
            claim = _saved_claim(application, binding)
        return deepcopy(_observed(application, manager, session, binding, claim,
            effect='clarification_response_published'))
