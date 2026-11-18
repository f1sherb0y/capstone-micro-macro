"""Reconcile original completed approval work; never execute missing stages."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest


def validate_saved_stage(app,row,saved,snapshot):
    with app.parent.read_guard():
        app.parent._check()
        if not app.settings.allow_saved_recovery:
            raise TaskConflict('Original saved-result recovery must be explicitly configured')
        identity=TaskIdentity(**row['identity'])
        bound=app._bound.get(identity.context_sha256)
        if bound is None:raise TaskConflict('Saved approval recovery needs its original current source binding')
        plan,request,stage,key=bound
        current,scope,_=app._current(request)
        records=[r for r in app._records() if r['key']==key]
        if len(records)!=1:raise TaskConflict('Saved approval recovery lost its original workflow')
        record=records[0]
        workers={name:worker for name,_,worker in app._stages(plan)}
        worker=workers.get(stage)
        if (current!=plan or worker is None or record.get(stage+'_identity')!=identity.as_dict()
                or record['scope']!=scope or record['native_request']!=request.model_dump(mode='json')
                or snapshot!=worker.snapshots.get(identity)
                or snapshot['context']!=app._stage_context(plan,stage).model_dump(mode='json')
                or snapshot['action_input']!=app._stage_input(plan,stage)
                or identity.request_id!=key+':'+identity.action_id
                or saved!=worker.get_record(identity) or saved['result'].get('kind')!='completed'):
            raise TaskConflict('Saved approval recovery substitutes its original request, invocation or result')
        objects,observed=app._sources(plan,request,stage,record)
        if (task_digest(objects)!=record.get(stage+'_source_sha256')
                or observed!=record.get(stage+'_observed')):
            raise TaskConflict('Saved approval recovery changes original currently authorized sources')
        return True


def recover_saved_proposal(app,request):
    """Recover all stages from durable originals, or retain unresolved state."""
    with app.parent.read_guard():
        plan,scope,_=app._current(request)
        if not app.settings.allow_saved_recovery:
            raise TaskConflict('Approval recovery requires explicit allow_saved_recovery configuration')
        key=app.PREFIX+task_digest([app.assembly.client.simulation_id,plan.organization_id,scope,request.request_id])
        rows=[r for r in app._records() if r['key']==key]
        if len(rows)!=1:raise TaskConflict('Approval recovery requires its existing original workflow')
        record=rows[0]
        if (record['scope']!=scope or record['native_request']!=request.model_dump(mode='json')
                or record['state'] not in {'preparing','formed'}):
            raise TaskConflict('Approval recovery changes the original pending request or scope')
        saved=None;prepared=None
        for stage,assembler,worker in app._stages(plan):
            if stage+'_identity' not in record:
                raise TaskConflict('Original approval stage was not registered; explicit continuation required')
            context=app._stage_context(plan,stage)
            app._bound[task_digest(context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True),stage,key)
            objects,observed=app._sources(plan,request,stage,record)
            if (task_digest(objects)!=record.get(stage+'_source_sha256')
                    or observed!=record.get(stage+'_observed')):
                raise TaskConflict('Approval recovery cannot replace original source evidence')
            identity=TaskIdentity(**record[stage+'_identity'])
            prepared=assembler.build(context,**deepcopy(app._stage_input(plan,stage)))
            if (worker._prepared_identity(prepared,request_id=key+':'+context.contract_ref.id,purpose='action').as_dict()!=identity.as_dict()
                    or worker.snapshots.get(identity)['action_input']!=app._stage_input(plan,stage)
                    or worker.snapshots.get(identity)['context']!=context.model_dump(mode='json')):
                raise TaskConflict('Approval recovery requires the original input, context and all execution versions')
            saved=worker.get_record(identity)
            if saved is None or saved['result'].get('kind')!='completed':
                raise TaskConflict('Interrupted approval has no saved completed result; no processor replay is allowed')
            known_sha=record.get(stage+'_result_sha256')
            if known_sha is not None and known_sha!=saved['result_sha256']:
                raise TaskConflict('Approval recovery conflicts with its original recorded result')
            task=worker.store.get(identity)
            if task['state']=='processing':
                # The original worker validates attempt revision, invocation,
                # audit and source evidence. This path never calls execute().
                worker._finalize(identity,saved,recovered=True)
            elif task['state']!='output_formed':
                raise TaskConflict('Approval stage has unresolved wait/failure/submission state; explicit diagnosis required')
            checked_result(worker,identity)
            if known_sha is None:
                record[stage+'_result_sha256']=saved['result_sha256'];record=app.parent._save(key,record)
        response=app._proposal_response(plan,request,scope,record,saved,prepared)
        digest=task_digest(response.model_dump(mode='json'))
        if record.get('proposal_response_sha256') not in {None,digest}:
            raise TaskConflict('Recovered approval differs from its original formed proposal')
        if record['state']!='formed' or record.get('proposal_response_sha256') is None:
            record.update(state='formed',proposal_response_sha256=digest)
            app.parent._save(key,record)
        return response
