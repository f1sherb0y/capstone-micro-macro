"""Authenticate completed original tender work without replaying preparation."""
from integration.bank_financing_private import checked_result
from integration.contractor_tender_request_sources import TenderRequestSourcesSettings, select_saved_bid
from src.actions.contracts.common import ActionContext
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def recover_request_work(*, application, request, settings, record):
    """Recover only when all required original actions have saved completed results.

    Primary source production, methods, action processors and model calls are
    never invoked here. The original independent indicators may be projected
    into their preauthorized technical read points after result reconciliation.
    """
    with application.read_guard():
        application._check()
        if not application.settings.allow_saved_recovery:
            raise TaskConflict('Tender recovery requires explicit original saved-result authorization')
        request = application.selector._request(request)
        config = TenderRequestSourcesSettings.model_validate(settings)
        plans = [p for p in config.requests if p.request_sha256 == task_digest(request.model_dump(mode='json'))
                 or p.request_binding == 'current_native_request'
                 and (p.organization_id, p.project_id, p.tick) == (request.agent.agent_id,
                     request.inputs['project']['project_id'], request.metadata.get('tick'))]
        if len(plans) != 1:
            raise TaskConflict('Tender recovery lacks its exact original independent source plan')
        plan = plans[0]
        if (request.metadata.get('tick') != application.assembly.engine.current_tick
                or (plan.organization_id, plan.project_id, plan.tick) != (request.agent.agent_id,
                    request.inputs['project']['project_id'], application.assembly.engine.current_tick)
                or record['native_request'] != request.model_dump(mode='json')
                or record['state'] not in {'preparing', 'screened', 'bid_formed', 'selected'}):
            raise TaskConflict('Tender recovery changes its original current request or workflow')
        workers = {'screening': application.screening_worker, 'bid': application.host.pipeline.worker}
        if 'screening_successor_identity' in record:
            if plan.clarification_continuation is None:
                raise TaskConflict('Tender recovery lacks its declared original clarification successor')
            workers['screening_successor'] = application.screening_worker
        originals = {}
        # Read every required result before changing any technical state.
        for stage, worker in workers.items():
            if stage + '_identity' not in record:
                raise TaskConflict('Interrupted tender has no registered original stage; no processor replay is allowed')
            identity = TaskIdentity(**record[stage + '_identity'])
            if (identity.organization_id != plan.organization_id or identity.purpose != 'action'
                    or identity.request_id != ('screening-after-clarification' if stage=='screening_successor' else stage)
                        + ':' + request.request_id):
                raise TaskConflict('Tender recovery substitutes its original stage identity')
            snapshot = worker.snapshots.get(identity)
            saved = worker.get_record(identity)
            if saved is None or saved['result'].get('kind') != 'completed':
                raise TaskConflict('Interrupted tender has no saved completed result; no processor replay is allowed')
            if record.get(stage + '_result_sha256') not in {None, saved['result_sha256']}:
                raise TaskConflict('Tender recovery changes an original saved stage result')
            task = application.store.get(identity)
            if task['state'] not in {'processing', 'output_formed'}:
                raise TaskConflict('Tender recovery retains unresolved waiting, failure or submission state')
            originals[stage] = (identity, snapshot, saved, task)
        screening = originals['screening'][2]['result']['payload']['choice']
        effective_stage = 'screening'
        if screening == 'clarify' and 'screening_successor' in originals:
            from integration.contractor_tender_clarification_continuation import effective_screening
            # This is a read of original QS permission, the exact actually
            # published reply, immutable source consumption and saved A01.
            # It cannot create a missing response, package or successor.
            effective_identity, effective_sha256 = effective_screening(application, record)
            successor = originals['screening_successor']
            if successor[0].as_dict()!=effective_identity or successor[2]['result_sha256']!=effective_sha256:
                raise TaskConflict('Tender recovery substitutes its original consumed clarification successor')
            screening = successor[2]['result']['payload']['choice']
            effective_stage = 'screening_successor'
        elif 'screening_successor' in originals:
            raise TaskConflict('Tender recovery cannot attach a successor to a nonclarifying original result')
        if screening not in {'participate', 'decline'}:
            raise TaskConflict('Original screening clarification must remain unresolved')
        bid_context = (plan.bid_plan.bid_context if screening == 'participate' and plan.bid_plan is not None
                       else plan.decline.context if screening == 'decline' and plan.decline is not None else None)
        contexts = {'screening': plan.screening_context, 'bid': bid_context}
        if effective_stage=='screening_successor':
            contexts['screening_successor']=plan.clarification_continuation.screening_context
        prepared_by_stage = {}
        for stage, worker in workers.items():
            identity, snapshot, saved, task = originals[stage]
            context = ActionContext.model_validate(snapshot['context'])
            if context != contexts[stage]:
                raise TaskConflict('Tender recovery changes its original plan or business context')
            assembler = application.screening_assembler if stage != 'bid' else application.host.pipeline.assembler
            inputs = snapshot['action_input']
            arguments = inputs if stage != 'bid' else {k: inputs[k] for k in
                ('pricing_profile_ref', 'capacity_ref', 'cost_refs', 'allowed_method_refs')}
            prepared = assembler.build(context, **arguments)
            if (prepared.action_input.model_dump(mode='json') != inputs
                    or worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity):
                raise TaskConflict('Tender recovery changes original inputs or execution versions')
            prepared.reading.recheck()
            if application.validate_recovery(task, saved, snapshot) is not True:
                raise TaskConflict('Tender recovery lacks its original currently authorized sources')
            prepared_by_stage[stage] = prepared
        if effective_stage=='screening_successor':
            expected=plan.clarification_continuation.screening_inputs.model_dump(mode='json')
            if originals[effective_stage][1]['action_input']!=expected:
                raise TaskConflict('Tender recovery changes declared successor inputs or package version')
        if (originals['bid'][2]['result']['payload']['choice'] not in {'submit_bid', 'decline_bid'}
                or screening == 'decline' and originals['bid'][2]['result']['payload']['choice'] != 'decline_bid'):
            raise TaskConflict('Tender recovery changes its original participation/bid branch')
        for stage, worker in workers.items():
            identity, _, saved, task = originals[stage]
            if task['state'] == 'processing':
                worker._finalize(identity, saved, recovered=True)
            checked_result(worker, identity)
        return select_saved_bid(application=application, request=request, plan=plan,
            identity=originals['bid'][0], invocation=prepared_by_stage['bid'])
