"""Execute the original micro procurement chain when its native request arrives."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Callable

from integration.contractor_bid_actions import PreparedContractorBid
from integration.contractor_bid_pipeline import ContractorBidPipelinePlan, PreparedContractorBidPipeline
from integration.contractor_bid_results import ContractorTenderReadSelection
from integration.contractor_screening_actions import PreparedContractorScreening
from integration.contractor_screening_results import ContractorScreeningResultWorker
from integration.contractor_tender_task_selection import ContractorTenderTaskSelector
from src.coordination.tasks import TaskConflict, canonical, task_digest


@dataclass(frozen=True)
class ContractorTenderRequestWork:
    """Explicit sourced work, not a precomputed bid or a native receipt.

    build_bid receives the saved A01 outcome and may return a source-production
    plan or an already sourced original A02 invocation (including decline).
    select_result must prepare the fresh indicator/source view and return an
    exact task selection; the original selector validates it independently.
    """
    screening: PreparedContractorScreening
    screening_worker: ContractorScreeningResultWorker
    build_bid: Callable
    select_result: Callable
    feedback_source: dict | None = None
    respond_clarification: Callable | None = None
    continue_clarification: Callable | None = None


def read_request_record(*, application, organization_id, request_id):
    """Read one exact original claim, bound to the currently installed host."""
    key = 'tender_request_trigger:' + task_digest([
        application.assembly.client.simulation_id, organization_id, request_id])
    with application.store._lock:
        row = application.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    if row is None:
        raise TaskConflict('Request-driven tender evidence lacks its original trigger')
    record = json.loads(row[0])
    ContractorTenderRequestTrigger._check_record(record)
    if (record['host_sha256'] != application.host.configuration_sha256
            or record['run_id'] != application.store.run_id
            or record['simulation_id'] != application.assembly.client.simulation_id
            or record['organization_id'] != organization_id or record['request_id'] != request_id):
        raise TaskConflict('Request-driven tender evidence changes its original host, run or recipient')
    return deepcopy(record)


class ContractorTenderRequestTrigger:
    """Request-driven A01 -> A02 -> exact selection, using existing workers.

    The outer host holds the engine writer guard. The native proposal adapter
    still reads and validates the completed bid, and the final decision still
    consumes that same proposal. Nothing here advances the core or writes its
    projects, contracts, resources or money. Pending work stays pending.
    """
    VERSION = 'contractor-tender-request-trigger.v9'

    def __init__(self, *, selector, prepare_work, continue_unstarted_actions_on_error=False,
            publish_clarification=None):
        if not isinstance(selector, ContractorTenderTaskSelector) or not callable(prepare_work):
            raise ValueError('Actual persistent selector and explicit sourced work producer required')
        if type(continue_unstarted_actions_on_error) is not bool:
            raise ValueError('Unstarted action continuation requires explicit boolean configuration')
        if publish_clarification is not None and not callable(publish_clarification):
            raise ValueError('Clarification publication requires an explicit original host callback')
        self.selector, self.prepare_work = selector, prepare_work
        self.continue_unstarted_actions_on_error = continue_unstarted_actions_on_error
        self.publish_clarification = publish_clarification
        self._active = set()

    def _execute_stage(self, *, worker, identity, prepared, store, key, record, stage):
        from integration.unstarted_action_continuation import execute_original_stage
        return execute_original_stage(worker=worker,identity=identity,prepared=prepared,
            enabled=self.continue_unstarted_actions_on_error,record=record,stage=stage,
            save_record=lambda value:self._save(store,key,value))

    def __call__(self, request):
        with self.selector.read_guard():
            request = self.selector._request(request)
            host = self.selector.host
            pipeline, store = host.pipeline, self.selector.store
            key = 'tender_request_trigger:' + task_digest([
                pipeline.assembly.client.simulation_id, request.agent.agent_id, request.request_id])
            digest = task_digest(request.model_dump(mode='json'))
            with store._lock:
                prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if prior is not None:
                record = json.loads(prior[0])
                self._check_record(record)
                if (record['request_sha256'] != digest or record['host_sha256'] != host.configuration_sha256
                        or record['organization_id'] != request.agent.agent_id):
                    raise TaskConflict('Native request cannot replace original micro work or its host')
                if record['state'] != 'selected':
                    raise TaskConflict('Original micro request is unresolved; inspect saved work before resuming')
                selected = self.selector.select_current(request)
                if selected.identity.as_dict() != record['bid_identity']:
                    raise TaskConflict('Completed native request changed its original bid selection')
                return
            if key in self._active:
                raise TaskConflict('Tender request preparation cannot recursively trigger itself')
            record = {'schema_version': self.VERSION, 'request_sha256': digest,
                      'native_request': request.model_dump(mode='json'),
                      'run_id': store.run_id, 'simulation_id': pipeline.assembly.client.simulation_id,
                      'organization_id': request.agent.agent_id, 'request_id': request.request_id,
                      'host_sha256': host.configuration_sha256, 'state': 'preparing'}
            record['record_sha256'] = task_digest(record)
            # Persist intent before invoking application code. A crash or failure
            # must not lead to another model call on a repeated native request.
            with store._transaction():
                if store._db.execute('SELECT 1 FROM metadata WHERE key=?', (key,)).fetchone():
                    raise TaskConflict('Another worker already claimed this original tender request')
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(record)))
            self._active.add(key)
            try:
                work = self.prepare_work(request.model_copy(deep=True))
                if (not isinstance(work, ContractorTenderRequestWork)
                        or not callable(work.build_bid) or not callable(work.select_result)
                        or work.respond_clarification is not None and not callable(work.respond_clarification)
                        or work.continue_clarification is not None and not callable(work.continue_clarification)):
                    raise ValueError('Tender producer must supply typed original screening and source work')
                screening, worker = work.screening, work.screening_worker
                if (not isinstance(screening, PreparedContractorScreening)
                        or not isinstance(worker, ContractorScreeningResultWorker)
                        or worker.store is not store or worker.registry is not pipeline.worker.registry
                        or worker.snapshots.store is not store
                        or worker.client_version != pipeline.worker.client_version
                        or worker.model_version != pipeline.worker.model_version
                        or screening.runner.registry is not worker.registry
                        or screening.runner.organizations is not pipeline.assembler.organizations):
                    raise TaskConflict('Screening must use original same-run authority, journal and execution versions')
                grants = pipeline.assembler.organizations.grants(screening.context, 'CONTRACTOR-A01', 'Contractor')
                if grants[0].organization_id != request.agent.agent_id:
                    raise TaskConflict('Native request must not execute another enterprise screening')
                self._check_context(request, screening.context)
                identity = worker.register(screening, request_id='screening:' + request.request_id)
                record['screening_identity'] = identity.as_dict()
                self._save(store, key, record)
                outcome = self._execute_stage(worker=worker, identity=identity, prepared=screening,
                    store=store, key=key, record=record, stage='screening')
                record.update(state='screened', screening_identity=identity.as_dict(),
                              screening_result_sha256=task_digest(outcome['result']))
                self._save(store, key, record)
                if outcome['result']['kind'] != 'completed':
                    raise TaskConflict('Pending screening remains pending; it cannot become a native decline')
                if work.feedback_source is not None:
                    consumed = pipeline.assembly.client.record_tender_feedback_consumption(request=request, identity=identity,
                        worker=worker, source=deepcopy(work.feedback_source),read_guard=self.selector.read_guard)
                    record['feedback_consumption_sha256'] = consumed['record_sha256']
                    self._save(store, key, record)
                if outcome['result']['payload']['choice'] == 'clarify':
                    if self.publish_clarification is not None:
                        record['clarification_request'] = self.publish_clarification(
                            request=request.model_copy(deep=True), identity=identity, prepared=screening)
                        self._save(store, key, record)
                    if work.respond_clarification is not None:
                        if record.get('clarification_request', {}).get('status') != 'observed':
                            raise TaskConflict('QS response requires its exact actually published native question')

                        def register_response(response_id, plan_sha256):
                            values = {'clarification_response_identity': response_id.as_dict(),
                                'clarification_response_plan_sha256': plan_sha256}
                            if (response_id.role != 'QS' or response_id.action_id != 'QS-A05'
                                    or response_id.run_id != store.run_id or response_id.purpose != 'action'
                                    or response_id.request_id != 'clarification-response:' + request.request_id
                                    or any(name in record and record[name] != value for name, value in values.items())):
                                raise TaskConflict('Clarification substitutes its original independent QS response identity')
                            record.update(values)
                            self._save(store, key, record)

                        record['clarification_response'] = work.respond_clarification(
                            request=request.model_copy(deep=True), register_response=register_response)
                        self._save(store, key, record)
                        response = record['clarification_response']
                        if (response.get('schema_version') == 'tender-clarification-review.v1'
                                and response.get('status') == 'waiting_input'):
                            record.update(state='waiting_input', waiting_stage='clarification_response',
                                conditions=deepcopy(response['waiting_conditions']))
                            self._save(store, key, record)
                            raise TaskConflict('QS response requires original finalized publication permission; '
                                'inspect the saved review and original waiting conditions before explicit continuation')
                    if work.continue_clarification is None:
                        raise TaskConflict('Screening clarification must be resolved before exposing a native tender choice')
                    if record.get('clarification_response', {}).get('status') != 'observed':
                        raise TaskConflict('Screening successor requires its actual authorized QS reply')
                    successor, consumption = work.continue_clarification(request=request.model_copy(deep=True),
                        screening=screening, identity=identity, response=deepcopy(record['clarification_response']))
                    if (not isinstance(successor, PreparedContractorScreening)
                            or successor.context == screening.context
                            or any(getattr(successor.context, name) != getattr(screening.context, name) for name in
                                ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))
                            or successor.action_input.package_ref.id != screening.action_input.package_ref.id
                            or successor.action_input.package_ref.version == screening.action_input.package_ref.version
                            or successor.runner.registry is not worker.registry
                            or successor.runner.organizations is not pipeline.assembler.organizations):
                        raise TaskConflict('Clarification successor must preserve identity and use a new sourced package version')
                    screening = successor
                    identity = worker.register(screening, request_id='screening-after-clarification:' + request.request_id)
                    record.update(screening_successor_identity=identity.as_dict(),
                        clarification_consumption_sha256=consumption['record_sha256'])
                    self._save(store, key, record)
                    outcome = self._execute_stage(worker=worker, identity=identity, prepared=screening,
                        store=store, key=key, record=record, stage='screening_successor')
                    record['screening_successor_result_sha256'] = task_digest(outcome['result'])
                    self._save(store, key, record)
                    if outcome['result']['kind'] != 'completed' or outcome['result']['payload']['choice'] == 'clarify':
                        raise TaskConflict('Original successor screening remains unresolved; no native choice is exposed')
                prepared = work.build_bid(request=request.model_copy(deep=True), screening=screening,
                                          outcome=deepcopy(outcome), identity=identity)
                if isinstance(prepared, ContractorBidPipelinePlan):
                    audit = worker.get_record(identity)['audit']
                    result = worker.registry.get('CONTRACTOR-A01').contract.result_adapter.validate_python(outcome['result'])
                    prepared = host.prepare(prepared, screening=screening, screening_result=result, screening_audit=audit)
                invocation = prepared.invocation if isinstance(prepared, PreparedContractorBidPipeline) else prepared
                if not isinstance(invocation, PreparedContractorBid):
                    raise TaskConflict('Bid preparation has not produced an executable original A02 invocation')
                if (invocation.context.actor_id != screening.context.actor_id
                        or invocation.context.scope != screening.context.scope
                        or invocation.context.business_time != screening.context.business_time
                        or invocation.action_input.package_ref != screening.action_input.package_ref
                        or invocation.reading.organization_id != request.agent.agent_id
                        or invocation.runner.registry is not pipeline.worker.registry
                        or invocation.runner.organizations is not pipeline.assembler.organizations):
                    raise TaskConflict('Tender preparation changes original screening identity, package, clock or authority')
                profile = invocation.reading.resolve(invocation.action_input.pricing_profile_ref)
                if profile.choice == 'submit_bid' and not isinstance(prepared, PreparedContractorBidPipeline):
                    raise TaskConflict('Submitted bids require the original sourced A01 handoff and bid pipeline')
                if outcome['result']['payload']['choice'] != 'participate':
                    if profile.choice != 'decline_bid':
                        raise TaskConflict('Nonparticipating screening cannot produce a submitted bid')
                self._check_context(request, invocation.context)
                bid_id = pipeline.worker.register(invocation, request_id='bid:' + request.request_id)
                record['bid_identity'] = bid_id.as_dict()
                self._save(store, key, record)
                bid = self._execute_stage(worker=pipeline.worker, identity=bid_id, prepared=invocation,
                    store=store, key=key, record=record, stage='bid')
                record.update(state='bid_formed', bid_identity=bid_id.as_dict(),
                              bid_result_sha256=task_digest(bid['result']))
                self._save(store, key, record)
                if bid['result']['kind'] != 'completed':
                    raise TaskConflict('Pending A02 result cannot be exposed as a native decision')
                selected = work.select_result(request=request.model_copy(deep=True),
                    identity=bid_id, outcome=deepcopy(bid), invocation=invocation)
                if not isinstance(selected, ContractorTenderReadSelection) or selected.identity != bid_id:
                    raise TaskConflict('Tender source producer must select the exact newly saved original A02 task')
                self.selector.register(request, selected)
                record.update(state='selected')
                self._save(store, key, record)
            except Exception as exc:
                # Keep the completed stage and exact worker identities. An
                # exception is never a business rejection or permission to retry.
                record['last_error_type'] = type(exc).__name__
                self._save(store, key, record)
                raise
            finally:
                self._active.remove(key)

    def _check_context(self, request, context):
        engine = self.selector.host.pipeline.assembly.engine
        if (context.execution_mode == 'offline_fixture' or context.run_id != self.selector.store.run_id
                or context.scope.kind != 'project' or context.scope.ref.id != request.inputs['project']['project_id']
                or request.metadata.get('tick') != engine.current_tick):
            raise TaskConflict('Micro work requires its original same-project current native request and formal sources')

    @staticmethod
    def _save(store, key, record):
        record['record_sha256'] = task_digest({name: value for name, value in record.items() if name != 'record_sha256'})
        with store._transaction():
            prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if prior is None:
                raise TaskConflict('Original tender request claim disappeared')
            original = json.loads(prior[0])
            ContractorTenderRequestTrigger._check_record(original)
            if any(original[name] != record[name] for name in
                   ('run_id', 'simulation_id', 'organization_id', 'request_id', 'request_sha256', 'host_sha256')):
                raise TaskConflict('Tender request claim changed its original identity')
            store._db.execute('UPDATE metadata SET value=? WHERE key=?', (canonical(record), key))

    @staticmethod
    def _check_record(record):
        if (record.get('schema_version') != ContractorTenderRequestTrigger.VERSION
                or record.get('record_sha256') != task_digest(
                    {name: value for name, value in record.items() if name != 'record_sha256'})
                or 'native_request' in record and task_digest(record['native_request']) != record.get('request_sha256')):
            raise TaskConflict('Stored tender request work changed its original evidence')

    def records(self, *, organization_id):
        """Read only records whose actual task identities belong to the recipient."""
        if organization_id not in self.selector.store.organization_ids:
            raise TaskConflict('Unknown tender trigger recipient')
        with self.selector.store._lock:
            rows = self.selector.store._db.execute(
                "SELECT value FROM metadata WHERE key LIKE 'tender_request_trigger:%'").fetchall()
        records = [json.loads(row[0]) for row in rows]
        for record in records:
            self._check_record(record)
            if record['run_id'] != self.selector.store.run_id:
                raise TaskConflict('Stored tender request work belongs to another run')
        return [record for record in records
                if record['organization_id'] == organization_id]
