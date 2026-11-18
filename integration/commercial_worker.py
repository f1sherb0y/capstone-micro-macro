"""Consume exact commercial invocations once and retain typed outcome evidence."""
from copy import deepcopy
import json

from integration.commercial_actions import CommercialActionAssembler, PreparedCommercialAction
from integration.commercial_successors import commercial_execution_versions
from src.actions.contracts.common import ActionContext
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


class CommercialTaskWorker:
    """Persist results before lifecycle finalization; never auto-replay a crash.

    validate_invocation(task, prepared) must check the actual host read point.
    validate_wait(task, result, conditions) must approve current wait registration.
    validate_recovery(task, record, snapshot) must approve finalizing a recovered
    result against actual current host authority; it never reruns the action.
    Completed results only form local output. Missing information and unsupported
    capabilities remain explicit manual waits until the host supplies a supported
    continuation; no scheduling condition is invented for them.
    """
    SCHEMA = 'commercial-worker-result.v1'

    def __init__(self, *, assembler, journal, snapshots, client_version, model_version,
                 validate_invocation, validate_wait, validate_recovery=None):
        if (not isinstance(assembler,CommercialActionAssembler)
                or not isinstance(snapshots,InvocationSnapshotStore)
                or snapshots.store is not journal.store
                or not callable(validate_invocation) or not callable(validate_wait)):
            raise ValueError('Worker requires shared snapshot/journal stores, assembler and explicit host checks')
        self.assembler, self.journal, self.snapshots = assembler, journal, snapshots
        self.store = journal.store
        self.client_version, self.model_version = client_version, model_version
        self.validate_invocation, self.validate_wait = validate_invocation, validate_wait
        if validate_recovery is not None and not callable(validate_recovery):
            raise ValueError('Recovery validation must be an explicit host callback')
        self.validate_recovery = validate_recovery
        with self.store._transaction():
            self.store._db.execute('CREATE TABLE IF NOT EXISTS commercial_action_results (task_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def register(self, prepared, *, request_id, purpose):
        """Persist an exact root invocation without executing or submitting it."""
        if not isinstance(prepared,PreparedCommercialAction):
            raise TaskConflict('Root registration requires an assembled commercial invocation')
        context = prepared.context
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id not in {'CONTRACTOR-A12','SUPPLIER-A12'}:
            raise TaskConflict('Root registration supports only the explicit commercial contracts')
        if prepared.runner.organizations is not self.assembler.organizations:
            raise TaskConflict('Root invocation belongs to another host organization registry')
        action_input = prepared.action_input.model_dump(mode='json')
        raw_context = context.model_dump(mode='json')
        if task_digest(action_input) != prepared.input_sha256 or task_digest(raw_context) != prepared.context_sha256:
            raise TaskConflict('Root invocation changed after assembly')
        registration = prepared.runner.registry.get(context.contract_ref.id)
        identity = TaskIdentity(run_id=context.run_id,organization_id=prepared.reading.organization_id,
            role=registration.role,action_id=registration.action_id,request_id=request_id,purpose=purpose,
            input_sha256=prepared.input_sha256,context_sha256=prepared.context_sha256,
            versions=commercial_execution_versions(prepared,client_version=self.client_version,model_version=self.model_version))
        registration.contract.validate_input(action_input)
        prepared.reading.check_method_context(context,identity.action_id)
        prepared.reading.recheck()
        self.snapshots.ensure(identity,action_input=action_input,context=raw_context)
        return identity

    def _validate_result(self, identity, record):
        snapshot = self.snapshots.get(identity)
        context = ActionContext.model_validate(snapshot['context'])
        registration = self.assembler.registry.get(identity.action_id)
        contract = registration.contract
        contract_digest = task_digest({'ref':context.contract_ref.model_dump(mode='json'),
            'source_sha256':contract.source_sha256,'input_schema':contract.input_model.model_json_schema(),
            'payload_schema':contract.payload_adapter.json_schema()})
        if identity.role != registration.role or identity.versions['contract'] != contract_digest:
            raise TaskConflict('Saved result requires its original contract version; no silent migration')
        action_input = contract.validate_input(snapshot['action_input'])
        result = contract.result_adapter.validate_python(record['result'])
        if result.model_dump(mode='json') != record['result']:
            raise TaskConflict('Saved result transport is not the original typed output')
        if result.kind == 'completed':
            contract.validate_decision(action_input,result.payload)
        audit = record['audit']
        expected = {'schema_version':'action-audit.v1','run_id':identity.run_id,'action_id':identity.action_id,
            'operation_id':context.operation_id,'input_schema_id':f'role-contract.v1:{identity.action_id}:input',
            'input_version':context.contract_ref.version,'input_sha256':identity.input_sha256,
            'result_kind':result.kind,'result_sha256':record['result_sha256']}
        if any(audit.get(key) != value for key,value in expected.items()):
            raise TaskConflict('Saved audit differs from original invocation or typed result')
        if (audit.get('authorization_refs') != [list(ref.key()) for ref in context.authorization_refs]
                or not isinstance(audit.get('reading'),dict)
                or audit['reading'].get('read_token') != context.read_token
                or audit.get('stages',{}).get('authorization') != 'accepted'):
            raise TaskConflict('Saved audit changes original authorization or read point')

    def _saved(self, identity):
        with self.store._lock:
            self.store.get(identity)
            saved = self.store._db.execute('SELECT record FROM commercial_action_results WHERE task_key=?',(identity.key,)).fetchone()
            if saved is None: return None
            record = json.loads(saved[0])
            fields = {'schema_version','identity','attempt_revision','result','result_sha256','audit','record_sha256'}
            if (not isinstance(record,dict) or set(record) != fields
                    or record['schema_version'] != self.SCHEMA or record['identity'] != identity.as_dict()
                    or type(record['attempt_revision']) is not int or record['attempt_revision'] < 1
                    or not isinstance(record['result'],dict) or not isinstance(record['audit'],dict)
                    or task_digest(record['result']) != record['result_sha256']
                    or task_digest({k:v for k,v in record.items() if k != 'record_sha256'}) != record['record_sha256']):
                raise TaskConflict('Saved commercial result identity, schema or evidence changed')
            self._validate_result(identity,record)
            return deepcopy(record)

    def _finalize(self, identity, record, *, recovered=False):
        row = self.store.get(identity)
        result = record['result']
        if row['state'] != 'processing':
            if row['output'] is not None and row['output'] != result:
                raise TaskConflict('Finalized task output differs from its persisted action result')
            if row['revision'] < record['attempt_revision']:
                raise TaskConflict('Task lifecycle precedes its persisted execution attempt')
            return {'task':row,'result':deepcopy(result)}
        if row['revision'] != record['attempt_revision']:
            raise TaskConflict('Processing task changed after its result was persisted')
        if recovered and (self.validate_recovery is None
                or self.validate_recovery(deepcopy(row),deepcopy(record),self.snapshots.get(identity)) is not True):
            raise TaskConflict('Recovered result needs current host validation before lifecycle finalization')
        kind = result.get('kind')
        if kind == 'completed':
            row = self.store.finish(identity,row['revision'],output=result)
        elif kind == 'technical_error':
            row = self.store.fail(identity,row['revision'],error_code=result['error'].get('code','recorded_technical_error'))
        elif kind == 'deferred':
            conditions = [result['resume_condition']]
            row = self.journal.register(identity,row['revision'],conditions=conditions,
                validate_wait=lambda task,waits:self.validate_wait(task,deepcopy(result),deepcopy(waits)))
        elif kind in {'needs_information','unsupported'}:
            # These are explicit local lifecycle requests, not ResumeCondition
            # profiles. They are not entered into the automatic resume journal.
            condition = {'kind':'information_request' if kind == 'needs_information' else 'unsupported_capability',
                         'result_sha256':record['result_sha256']}
            if kind == 'needs_information':
                condition.update(missing_fields=result['missing_fields'],requested_refs=result['requested_refs'])
            else: condition['capability_ref'] = result['capability_ref']
            if self.validate_wait(deepcopy(row),deepcopy(result),[deepcopy(condition)]) is not True:
                raise TaskConflict('Current manual wait facts must be explicitly validated')
            row = self.store.wait_for_input(identity,row['revision'],conditions=[condition])
        else:
            raise TaskConflict('Saved result has no supported typed lifecycle outcome')
        return {'task':row,'result':deepcopy(result)}

    def run(self, identity):
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id not in {'CONTRACTOR-A12','SUPPLIER-A12'}:
            raise TaskConflict('Worker supports only its explicit commercial actions')
        row = self.store.get(identity)
        if self.store.continuation(identity) is not None:
            raise TaskConflict('Original continued task cannot be executed again')
        saved = self._saved(identity)
        if saved is not None:
            # A crash after result persistence resumes finalization only.
            return self._finalize(identity,saved,recovered=True)
        if row['state'] == 'processing':
            raise TaskConflict('Interrupted processing has no saved result; diagnose it before any replay')
        if row['state'] != 'waiting_input' or row['conditions']:
            raise TaskConflict('Only a new ready invocation may execute; waits/failures are not automatic retries')
        snapshot = self.snapshots.get(identity)
        context = ActionContext.model_validate(snapshot['context'])
        profile_ref = snapshot['action_input'].get('continuation_profile_ref')
        prepared = self.assembler.build(context,profile_ref=profile_ref)
        registration = prepared.runner.registry.get(identity.action_id)
        if (registration.role != identity.role or prepared.reading.organization_id != identity.organization_id
                or prepared.input_sha256 != identity.input_sha256 or prepared.context_sha256 != identity.context_sha256
                or commercial_execution_versions(prepared,client_version=self.client_version,model_version=self.model_version) != identity.versions):
            raise TaskConflict('Current assembly differs from the original invocation or execution versions')
        if self.validate_invocation(deepcopy(row),prepared) is not True:
            raise TaskConflict('Actual current host facts and authorization must be explicitly validated')
        prepared.reading.recheck()
        prepared.runner.prepare_decision(context=prepared.context,
            action_input=prepared.action_input, reading=prepared.reading)
        if (self.store.get(identity) != row or self._saved(identity) is not None
                or prepared.input_sha256 != identity.input_sha256 or prepared.context_sha256 != identity.context_sha256
                or commercial_execution_versions(prepared, client_version=self.client_version,
                    model_version=self.model_version) != identity.versions):
            raise TaskConflict('Commercial option preparation changed its original ready task or execution versions')
        prepared.reading.recheck()
        started = self.store.start(identity,row['revision'])
        try:
            result = prepared.execute().model_dump(mode='json')
        except Exception:
            self.store.fail(identity,started['revision'],error_code='commercial_worker_execution_exception')
            raise
        if not prepared.runner.audit_records:
            raise TaskConflict('Executed action has no audit evidence; retain interrupted processing')
        record = {'schema_version':self.SCHEMA,'identity':identity.as_dict(),
                  'attempt_revision':started['revision'],'result':result,'result_sha256':task_digest(result),
                  'audit':prepared.runner.audit_records[-1].as_dict()}
        record['record_sha256'] = task_digest(record)
        self._validate_result(identity,record)
        with self.store._transaction():
            current = self.store._read(identity)
            self.store._check_not_continued(identity)
            if current != started:
                raise TaskConflict('Execution task changed before its result could be persisted')
            self.store._db.execute('INSERT INTO commercial_action_results VALUES (?,?)',(identity.key,canonical(record)))
        return self._finalize(identity,record)
