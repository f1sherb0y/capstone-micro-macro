"""Query actual own native tender execution without resubmitting a decision."""
from copy import deepcopy

from integration.agent_client import AgentClientError
from integration.bindings.gba_v1_tender_feedback import project_tender_event
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


def query_prior_tender_submissions(application, request, *, project_only):
    """Reconcile missing notices from exact earlier own claims, never replay work."""
    from integration.contractor_tender_request_trigger import read_request_record

    with application.read_guard():
        application._check()
        if application.request_trigger is None or type(project_only) is not bool:
            raise TaskConflict('Prior tender query requires its original trigger and explicit project scope')
        request = application.selector._request(request)
        tick = request.metadata.get('tick')
        if type(tick) is not int or tick != application.assembly.engine.current_tick:
            raise TaskConflict('Prior tender reconciliation requires the current original requesting business time')
        organization_id = request.agent.agent_id
        records = application.request_trigger.records(organization_id=organization_id)
        outcomes = []
        for claim in sorted(records, key=lambda row: row['request_id']):
            original = claim['native_request']
            original_tick = original['metadata'].get('tick')
            if (type(original_tick) is not int or original_tick >= tick
                    or project_only and original['inputs']['project']['project_id'] != request.inputs['project']['project_id']):
                continue
            checked = read_request_record(application=application, organization_id=organization_id,
                request_id=claim['request_id'])
            if checked != claim:
                raise TaskConflict('Prior tender claim changed while querying actual execution')
            outcome = application.host.query_submission(original)
            if outcome['status'] != 'observed':
                raise TaskConflict('Earlier own tender execution remains unknown; retain unresolved work without resubmission')
            outcomes.append(outcome)
        body = {'schema_version':'gba-v1-prior-tender-query.v1','run_id':application.store.run_id,
            'simulation_id':application.assembly.client.simulation_id,'organization_id':organization_id,
            'request_sha256':task_digest(request.model_dump(mode='json')),'as_of_tick':tick,
            'project_only':project_only,'outcomes':outcomes,'resubmitted':False}
        body['record_sha256']=task_digest(body)
        key='gba_prior_tender_query:'+body['request_sha256']
        with application.store._transaction():
            old=application.store._db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
            if old is not None:
                import json
                if json.loads(old[0])!=body:
                    raise TaskConflict('Prior tender query changed its original successful reconciliation evidence')
            else:
                application.store._db.execute('INSERT INTO metadata VALUES (?,?)',(key,canonical(body)))
        return deepcopy(body)


def query_tender_submission(host, raw_request):
    from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1, AgentObservationV1
    from gba_construction_sim.backend.agents.operation_specs import get_operation_contract, validate_operation_inputs

    with host.pipeline.read_guard():
        host._check(bound=True)
        assembly = host.pipeline.assembly
        engine, client = assembly.engine, assembly.client
        with client._lock:
            request = AgentProposalRequestV1.model_validate(raw_request).model_copy(deep=True)
            if ((request.agent.role, request.operation) != ('Contractor', 'consider_tender')
                    or client.organization_roles.get(request.agent.agent_id) != 'Contractor'
                    or request.metadata.get('simulation_id') not in {None, client.simulation_id}
                    or type(request.metadata.get('tick')) is not int
                    or not 0 <= request.metadata['tick'] <= engine.current_tick
                    or request.operation_contract != get_operation_contract('consider_tender', 'Contractor')):
                raise AgentClientError('Tender query needs its original own native request and observed business time')
            validate_operation_inputs(request.operation_contract, request.inputs)
            # get() never creates an identity for an unknown or changed request.
            _, _, _, identity = client._invocation_identity('propose', request)
            proposal = client.tasks.get(identity)
            result = {'status': 'outcome_unknown', 'proposal_identity': identity.as_dict(),
                      'transport_state': proposal['state'], 'native_request_sha256': task_digest(request.model_dump(mode='json')),
                      'resubmitted': False}
            if proposal['state'] != 'output_formed':
                return result
            output = proposal['output']; digest = task_digest(output)
            matches = []
            for event in engine.events.events:
                if (event.event_type not in {'bid_submitted', 'bid_declined'}
                        or event.agent_id != request.agent.agent_id or event.tick != request.metadata['tick']
                        or event.project_id != request.inputs['project']['project_id']):
                    continue
                link = event.data.get('decision_advisor', {}).get('data', {})
                if link.get('proposal_request_id') != request.request_id:
                    continue
                if (link.get('micro_action_id') != 'CONTRACTOR-A02' or link.get('proposal_response_sha256') != digest
                        or link.get('micro_result_sha256') != output.get('factors', {}).get('micro_result_sha256')):
                    raise TaskConflict('Actual tender event changes its original proposal correlation')
                matches.append(event)
            if not matches:
                return result
            if len(matches) != 1:
                raise TaskConflict('Tender query found conflicting actual terminal events for one original request')
            event = matches[0]; raw = event.model_dump(mode='json')
            observation = AgentObservationV1.model_validate(raw)
            # Reuse original proposal/final/event validation. This only admits
            # private correlation evidence; it neither delivers an observation
            # to business consumers nor changes a formal macro/task receipt.
            client._tender_feedback.record(observation)
            correlated, = [r for r in client.tender_feedback(organization_id=request.agent.agent_id)
                            if r['event_id'] == event.event_id]
            if (correlated['proposal_identity'] != identity.as_dict()
                    or correlated['projection'] != project_tender_event(observation, client.organization_roles)[request.agent.agent_id]
                    or client.tasks.get(identity) != proposal):
                raise TaskConflict('Tender query substitutes its original private correlation or proposal')
            result.update(status='observed', effect=correlated['effect'], event_id=event.event_id,
                          source_event_sha256=task_digest(raw), micro_result_sha256=correlated['micro_result_sha256'],
                          feedback_record_sha256=correlated['record_sha256'])
            return deepcopy(result)


def query_tender_source_history(host, original_request, identity, *, current_context):
    """Join own original read witnesses to an independently queried native bid.

    Historical sources are not rebuilt from the current project. This does not
    issue a formal SubmissionExecution, award, agreement or payment receipt.
    """
    with host.pipeline.read_guard():
        host._check(bound=True)
        from src.actions.contracts.common import ActionContext
        current_context = ActionContext.model_validate(current_context)
        if current_context.business_time.offset != host.pipeline.assembly.engine.current_tick:
            raise TaskConflict('Tender source query requires the actual current native business time')
        worker = host.pipeline.worker
        history = worker.read_source_history(identity, current_context=current_context,
            organizations=host.pipeline.assembler.organizations)
        outcome = query_tender_submission(host, original_request)
        if outcome['proposal_identity']['organization_id'] != identity.organization_id:
            raise TaskConflict('Tender source history substitutes the original submitting organization')
        if outcome['status'] != 'observed':
            return {'status': 'unknown', 'reason': 'native_submission_not_observed', 'outcome': outcome}
        saved = worker.get_record(identity)
        proposal = worker.store.get(TaskIdentity(**outcome['proposal_identity']))['output']
        factors = proposal.get('factors', {})
        if (saved is None or outcome['micro_result_sha256'] != saved['result_sha256']
                or factors.get('micro_input_sha256') != identity.input_sha256
                or factors.get('original_audit_sha256') != task_digest(saved['audit'])):
            raise TaskConflict('Native tender query differs from its exact original micro result, input or audit')
        return {'status': history['status'], 'history': history, 'outcome': outcome,
                'formal_effect': 'native_bid_only_no_detailed_submission_or_agreement_receipt'}
