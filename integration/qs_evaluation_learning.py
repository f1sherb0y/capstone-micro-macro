"""Consume own actual evaluations through original QS-A12 private recording.

The native monthly request triggers the private step. Its subsequent native
business decision remains native, and no cost outcome or applied learning is
inferred from a bid score or preferred-bidder selection.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from integration.bank_financing_private import checked_result, evidence_binding
from integration.qs_learning_actions import QSLearningActionAssembler
from integration.qs_learning_results import QSLearningResultWorker
from src.actions.contracts.common import ActionContext, StrictRecord, TextId, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class QSEvaluationLearningSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest
    allow_saved_recovery: bool = False


class QSEvaluationLearningPlan(StrictRecord):
    organization_id: TextId
    tick: int = Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    history_evidence_ref: ref_type('Evidence')
    feedback_ref: ref_type('Feedback')

    @model_validator(mode='after')
    def private_record_only(self):
        c, a = self.context, self.action_input
        rows = {task_digest(r['ref']): r['value'] for r in self.objects}
        if (c.contract_ref.id != 'QS-A12' or c.execution_mode == 'offline_fixture'
                or c.actor_id != self.organization_id
                or c.scope.kind != 'project' or c.business_time.offset != self.tick
                or a.get('scope') != c.scope.model_dump(mode='json')
                or a.get('forecast_refs') != [] or a.get('outcome_refs') != []
                or a.get('comparability_result_ref') is not None or a.get('learning_profile_ref') is not None
                or a.get('feedback_refs') != [self.feedback_ref.model_dump(mode='json')]
                or any(task_digest(ref.model_dump(mode='json')) not in rows
                       for ref in [c.scope.ref, *c.scope.coverage_refs])
                or len(rows) != len(self.objects)):
            raise ValueError('Evaluation recording requires its exact original QS-A12 scope and no invented cost comparison')
        strategy = rows.get(task_digest(a['strategy_ref']))
        decision = None if strategy is None else rows.get(task_digest(strategy['decision_profile_ref']))
        state = None if strategy is None else rows.get(task_digest(strategy['learning_state_ref']))
        if (decision is None or state is None or decision['choice'] != 'record_feedback'
                or decision['feedback_refs'] != a['feedback_refs'] or strategy['judgments']
                or any(decision.get(name) is not None for name in (
                    'forecast_ref', 'outcome_ref', 'comparability_result_ref', 'error_result_ref',
                    'assessment_ref', 'training_profile_ref', 'learning_profile_ref'))
                or state['forecast_refs'] or state['outcome_refs'] or state['applied_error_pair_keys']
                or state['applied_feedback_refs'] or state['execution_refs']
                or state['learning_profile_ref'] is not None
                or state['received_feedback_refs'] != a['feedback_refs']
                or any(row.get('organization_id') != self.organization_id for row in (strategy, decision, state))):
            raise ValueError('Evaluation recording cannot apply judgment, training or an unreceived cost outcome')
        return self


def read_own_completed_evaluations(parent, *, organization_id, project_id, tick,
        include_current=False, evaluation_task_key=None):
    """Query exact native events and original QS proposal/final/worker records."""
    with parent.bindings.read_guard():
        parent._check()
        engine, client = parent.assembly.engine, parent.assembly.client
        if (client.organization_roles.get(organization_id) != 'QS' or type(tick) is not int
                or tick != engine.current_tick or client.simulation_id != engine.simulation_id):
            raise TaskConflict('QS evaluation history changes its own current organization, run or clock')
        tasks = client.tasks.for_organization(run_id=client.run_id, organization_id=organization_id)
        history, seen = [], set()
        for event in engine.events.events:
            if (event.event_type=='bid_evaluation_deferred' and event.project_id==project_id
                    and event.tick<=tick and (event.tick<tick or include_current)):
                from integration.qs_no_valid_outcome import read_no_valid_evaluation
                deferred = read_no_valid_evaluation(parent,event,organization_id=organization_id,
                    project_id=project_id,tick=tick,evaluation_task_key=evaluation_task_key)
                if deferred is not None:
                    if event.event_id in seen:raise TaskConflict('QS history duplicates an original deferral')
                    seen.add(event.event_id)
                    history.append(deferred)
                continue
            if (event.event_type != 'bid_evaluation_completed' or event.project_id != project_id
                    or event.tick > tick or event.tick == tick and not include_current
                    or event.data.get('evaluation_committee', {}).get('qs_id') != organization_id):
                continue
            project = engine.projects.get(project_id)
            logged = [] if project is None else [e for e in project.event_log if e['event_id'] == event.event_id]
            selected = event.data.get('selected_contractor_id')
            if (len(logged) != 1 or task_digest(logged[0]) != task_digest(event.model_dump(mode='json'))
                    or event.event_id in seen or event.agent_id != selected
                    or client.organization_roles.get(selected) != 'Contractor'
                    or event.data['evaluation_committee'].get('owner_id') != project.owner_id
                    or event.data.get('owner_decision', {}).get('accepted') is not True):
                raise TaskConflict('QS history lost its original event, receiving committee or actual selection')
            seen.add(event.event_id)
            plans = [p for p in parent.plans if (p.organization_id, p.project_id, p.tick) ==
                     (organization_id, project_id, event.tick)]
            if len(plans) != 1:
                raise TaskConflict('QS actual event lacks its original independently supplied evaluation plan')
            record = parent._record(plans[0])
            if record is None:
                raise TaskConflict('QS actual event lacks its original micro round')
            identity, _ = parent._result(plans[0], record)
            if evaluation_task_key is not None and identity.key != evaluation_task_key:
                continue
            from integration.qs_evaluation_outcome_query import original_authorized_round, matching_native_events
            _, _, saved = original_authorized_round(parent, identity, organization_id=organization_id, tick=tick)
            matched = matching_native_events(parent, plans[0])
            if len(matched)!=1 or matched[0]['event_id']!=event.event_id:
                raise TaskConflict('QS history lost its matching original native evaluation')
            opinions = []
            for bid in event.data.get('ranked_bids', []):
                scope = {'tick': event.tick, 'project_id': project_id, 'contractor_id': bid['contractor_id']}
                proposals = [t for t in tasks if t['identity']['purpose'] == 'propose'
                    and t['identity']['action_id'] == 'evaluate_bid' and t['state'] == 'output_formed'
                    and t['output'].get('factors', {}).get('native_evaluation_scope') == scope]
                finals = [t for t in tasks if t['identity']['purpose'] == 'decide'
                    and t['identity']['action_id'] == 'qs_bid_evaluation' and t['state'] == 'output_formed'
                    and t['output'].get('data', {}).get('native_evaluation_scope') == scope]
                opinion = bid.get('qs_decision', {})
                if (len(proposals) != 1 or len(finals) != 1 or opinion.get('accepted') is not True
                        or opinion.get('native_evaluation_scope') != scope
                        or opinion.get('micro_task_key') != identity.key
                        or opinion.get('micro_result_sha256') != saved['result_sha256']
                        or proposals[0]['output']['factors'].get('micro_result_sha256') != saved['result_sha256']
                        or finals[0]['output'].get('decision') is not True
                        or finals[0]['output']['data'].get('micro_task_key') != identity.key
                        or finals[0]['output']['data'].get('micro_result_sha256') != saved['result_sha256']
                        or bid.get('evaluation_score') != proposals[0]['output']['data'].get('evaluation_score')
                        or bid.get('evaluation_score') != finals[0]['output']['data'].get('evaluation_score')):
                    raise TaskConflict('QS history substitutes its original formed opinion, score or completed worker')
                opinions.append({'contractor_id': bid['contractor_id'], 'evaluation_score': bid['evaluation_score'],
                                 'proposal_identity': proposals[0]['identity'], 'final_identity': finals[0]['identity']})
            if not opinions or len({b['contractor_id'] for b in opinions}) != len(opinions):
                raise TaskConflict('QS history requires distinct actually published original opinions')
            if selected not in {b['contractor_id'] for b in opinions}:
                raise TaskConflict('QS history selects an enterprise outside its actual published ranking')
            history.append({'event_id': event.event_id, 'project_id': project_id, 'tick': event.tick,
                'owner_id': project.owner_id, 'qs_id': organization_id, 'preferred_contractor_id': selected,
                'source_event_sha256': task_digest(event.model_dump(mode='json')),
                'micro_identity': identity.as_dict(), 'micro_result_sha256': saved['result_sha256'],
                'published_opinions': opinions})
            if getattr(parent,'admissibility',None) is not None:
                history[-1]['authorized_exclusions'] = parent.admissibility.read_outcomes(plans[0],event,tick=tick)
        return sorted(history, key=lambda r: (r['tick'], r['event_id']))


class QSEvaluationLearning:
    VERSION = 'gba-v1-qs-evaluation-learning.v5'
    PREFIX = 'qs_evaluation_learning:'
    NATIVE_PREFIX = 'qs_evaluation_learning_native:'

    def __init__(self, *, parent, settings, policy_version):
        self.parent = parent
        self.settings = QSEvaluationLearningSettings.model_validate(settings).model_copy(deep=True)
        raw = Path(self.settings.file_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('QS learning source differs from its pinned independent file')
        doc = json.loads(raw)
        if (set(doc) != {'schema_version', 'run_id', 'plans'} or doc['schema_version'] != 'qs-evaluation-learning-input.v1'
                or doc['run_id'] != parent.assembly.client.run_id):
            raise TaskConflict('QS evaluation learning changes its original run or source schema')
        self.plans = [QSEvaluationLearningPlan.model_validate(p) for p in doc['plans']]
        selectors = [(p.organization_id, p.tick) for p in self.plans]
        if not selectors or len(set(selectors)) != len(selectors):
            raise TaskConflict('QS learning requires unique original monthly request selectors')
        for plan in self.plans:
            if not any(p.organization_id == plan.organization_id and p.project_id == plan.context.scope.ref.id
                       and p.tick < plan.tick for p in parent.plans):
                raise TaskConflict('QS learning has no strictly earlier original evaluation source')
        self._fingerprint = self._sources_fingerprint()
        self._bound = {}
        bindings = parent.bindings
        self.recovery_guard = bindings.read_guard
        if parent.assembly.client.native_routes.settings.query_saved_qs_learning_on_error and not self.settings.allow_saved_recovery:
            raise TaskConflict('QS learning query requires explicit saved-result recovery authorization')
        self.assembler = QSLearningActionAssembler(registry=bindings.registry, organizations=bindings.organizations,
            provider=self, macro_version='gba-public-2026-08-21', source_mode='formal', methods=bindings.methods,
            policy_version=policy_version, model_version=parent.assembly.client.versions['model'], model_host=bindings.model_host)
        self.worker = QSLearningResultWorker(store=parent.assembly.client.tasks,
            snapshots=InvocationSnapshotStore(parent.assembly.client.tasks), registry=bindings.registry,
            client_version=self.VERSION, model_version=parent.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation, validate_wait=self.validate_wait,
            validate_recovery=self.validate_recovery)
        self._components = (parent, bindings, self.assembler, self.worker, self.worker.store)

    def _sources_fingerprint(self):
        return (task_digest(self.settings.model_dump(mode='json')),
                task_digest([p.model_dump(mode='json') for p in self.plans]),
                hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest(),
                hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def check(self):
        p = self.parent
        if (self._sources_fingerprint() != self._fingerprint
                or self._fingerprint[2] != self.settings.file_sha256
                or self._components != (p, p.bindings, self.assembler, self.worker, p.assembly.client.tasks)
                or self.worker.registry is not p.bindings.registry or self.assembler.organizations is not p.bindings.organizations):
            raise TaskConflict('QS learning changed original source, registry, authority, worker or shared journal')

    def _current(self, request):
        self.parent._check()
        engine, client = self.parent.assembly.engine, self.parent.assembly.client
        if (request.agent.role != 'QS' or request.operation != 'decide_monthly_operation'
                or client.organization_roles.get(request.agent.agent_id) != 'QS'
                or set(request.inputs) != {'macro_environment'}
                or request.inputs['macro_environment'] != engine.macro_environment.model_dump(mode='json')):
            raise TaskConflict('QS learning requires the exact current original monthly request')
        return next((p for p in self.plans if (p.organization_id, p.tick) ==
                     (request.agent.agent_id, engine.current_tick)), None)

    def _sources(self, plan, request):
        history = read_own_completed_evaluations(self.parent, organization_id=plan.organization_id,
            project_id=plan.context.scope.ref.id, tick=plan.tick)
        if not history:
            raise TaskConflict('Scheduled QS learning has no actual strictly earlier own evaluation')
        for origin in history:
            queried = self.parent.query_native_outcome(origin['micro_identity'],
                organization_id=plan.organization_id, tick=plan.tick)
            if queried['status'] != 'observed' or queried['native_outcome'] != origin:
                raise TaskConflict('QS feedback cannot consume an unknown or changed original evaluation')
        objects = deepcopy(plan.objects)
        evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), request.model_dump(mode='json'))
        evidence_binding(objects, plan.history_evidence_ref.model_dump(mode='json'), history)
        source, = [r['value'] for r in objects if r['ref'] == plan.history_evidence_ref.model_dump(mode='json')]
        feedback, = [r['value'] for r in objects if r['ref'] == plan.feedback_ref.model_dump(mode='json')]
        if feedback['event']['subject_sha256'] is not None or feedback['event_sha256'] is not None:
            raise TaskConflict('QS feedback requires explicitly unbound actual history digests')
        feedback['event'].update(event_key='own-native-evaluation-query:' + task_digest(history), subject_sha256=task_digest(source))
        feedback['event_sha256'] = task_digest(feedback['event'])
        for row in objects:
            if row['ref']['kind'] == 'QSLearningDecision':
                row['value']['interpretation'] = (f'Recorded {len(history)} authenticated own evaluation outcome(s). '
                    'Published opinions and preferred status are not actual costs, profit, contract, payment or improved capability.')
        return objects, history

    def project(self, *, context, organization_id, grants):
        plan, request = self._bound[task_digest(context.model_dump(mode='json'))]
        if self._current(request) != plan or organization_id != plan.organization_id or context != plan.context:
            raise TaskConflict('QS learning projection substitutes its actual current request or private recipient')
        objects, history = self._sources(plan, request)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'own-native-qs-evaluation-query:' + task_digest(history),
            'read_token': context.read_token, 'business_time': context.business_time.model_dump(mode='json'),
            'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        plan, request = self._bound[prepared.context_sha256]
        if (self._current(request) != plan or prepared.context != plan.context
                or row['identity']['organization_id'] != plan.organization_id):
            raise TaskConflict('QS learning execution lost its exact current original source binding')
        prepared.reading.recheck()
        return True

    def validate_wait(self, *args, **kwargs):
        raise TaskConflict('Unresolved QS feedback requires diagnosis, not an automatic native substitute')

    def _records(self):
        store = self.worker.store
        with store._lock:
            rows = list(store._db.execute('SELECT key,value FROM metadata WHERE key LIKE ?', (self.PREFIX + '%',)))
        records = []
        for key, value in rows:
            record = json.loads(value)
            identity = TaskIdentity(**record['identity'])
            if (record.get('key') != key
                    or record.get('record_sha256') != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                    or identity.run_id != self.parent.assembly.client.run_id
                    or identity.role != 'QS' or identity.action_id != 'QS-A12'
                    or record.get('state') not in {'preparing', 'formed'}):
                raise TaskConflict('QS learning journal changes its original identity, state or retained content')
            if record['state'] == 'formed':
                saved = checked_result(self.worker, identity)
                if (saved['result_sha256'] != record.get('result_sha256')
                        or saved['result']['payload'].get('choice') != 'record_feedback'):
                    raise TaskConflict('QS learning journal lost its exact original completed record')
            records.append(record)
        return records

    def _save(self, record):
        record = deepcopy(record)
        record['record_sha256'] = task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
        with self.worker.store._transaction():
            self.worker.store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                                         (record['key'], canonical(record)))
        return record

    def _saved_work(self, request):
        """Rebuild the original authorized reading, never its action result."""
        if not self.settings.allow_saved_recovery:
            raise TaskConflict('QS learning recovery requires explicit allow_saved_recovery')
        plan = self._current(request)
        if plan is None:
            raise TaskConflict('QS learning recovery has no original scheduled private action')
        key = self.PREFIX + task_digest([self.parent.assembly.client.simulation_id, plan.context.model_dump(mode='json')])
        records = [row for row in self._records() if row['key'] == key]
        if len(records) != 1:
            raise TaskConflict('QS learning recovery requires its existing original workflow')
        record, = records
        identity = TaskIdentity(**record['identity'])
        objects, history = self._sources(plan, request)
        if (record.get('native_request') != request.model_dump(mode='json')
                or record['native_request_sha256'] != task_digest(request.model_dump(mode='json'))
                or record['source_sha256'] != task_digest(objects) or record['history'] != history
                or identity.organization_id != plan.organization_id or identity.purpose != 'action'
                or identity.request_id != key
                or self._bound.get(identity.context_sha256) != (plan, request)):
            raise TaskConflict('QS learning recovery changes its original request, sources or task binding')
        prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
        snapshot = self.worker.snapshots.get(identity)
        if (self.worker._prepared_identity(prepared, request_id=identity.request_id, purpose='action') != identity
                or snapshot['context'] != plan.context.model_dump(mode='json')
                or snapshot['action_input'] != plan.action_input):
            raise TaskConflict('QS learning recovery changes its original invocation or execution versions')
        saved = self.worker.get_record(identity)
        if saved is not None:
            if (prepared.reading.evidence() != saved['source_reading']
                    or record.get('result_sha256') not in {None, saved['result_sha256']}
                    or saved['result'].get('kind') != 'completed'
                    or saved['result']['payload'].get('choice') != 'record_feedback'):
                raise TaskConflict('QS learning recovery requires its exact original completed private feedback')
        prepared.reading.recheck()
        return plan, record, identity, saved

    def query_saved_result(self, request):
        with self.recovery_guard():
            _, record, identity, saved = self._saved_work(request)
            return {'status': 'saved' if saved is not None else 'unresolved',
                'identity': identity.as_dict(), 'task_state': self.worker.store.get(identity)['state'],
                'native_phase': self._native_stage(record)['phase'], 'record': deepcopy(saved)}

    def validate_recovery(self, row, saved, snapshot):
        with self.recovery_guard():
            identity = TaskIdentity(**row['identity'])
            bound = self._bound.get(identity.context_sha256)
            if bound is None:
                raise TaskConflict('QS learning recovery lost its original source binding')
            _, _, original, actual = self._saved_work(bound[1])
            if identity != original or actual != saved or snapshot != self.worker.snapshots.get(identity):
                raise TaskConflict('QS learning recovery substitutes its original saved result')
            return True

    def _native_key(self, learned):
        return self.NATIVE_PREFIX + task_digest(learned['identity'])

    def _native_stage(self, learned):
        key = self._native_key(learned)
        with self.worker.store._lock:
            row = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if row is None:
            raise TaskConflict('QS native proposal lacks its original retained execution declaration')
        stage = json.loads(row[0])
        fields = {'key','identity','source_sha256','native_request_sha256','phase','record_sha256'}
        if stage.get('phase') in {'dispatching','returned'}:
            fields |= {'private_record_sha256','result_sha256'}
        if stage.get('phase') == 'returned':
            fields |= {'native_response','native_response_sha256'}
        if (stage.get('key') != key or stage.get('identity') != learned['identity']
                or set(stage) != fields
                or stage.get('record_sha256') != task_digest({k:v for k,v in stage.items() if k != 'record_sha256'})
                or stage.get('native_request_sha256') != learned['native_request_sha256']
                or stage.get('source_sha256') != learned['source_sha256']
                or stage.get('phase') not in {'not_started','dispatching','returned'}
                or stage['phase'] != 'not_started' and (
                    stage.get('private_record_sha256') != learned['record_sha256']
                    or stage.get('result_sha256') != learned.get('result_sha256'))):
            raise TaskConflict('QS native proposal changes its original private result, request or execution stage')
        return stage

    def _native_proposal(self, request, learned):
        """Call the declared native step once, or return its original response.

        A dispatched call without a retained response stays unknown. A saved
        micro result cannot authorize replaying that separate native step.
        """
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        stage = self._native_stage(learned)
        if stage['phase'] == 'returned':
            response = AgentProposalResponseV1.model_validate(stage['native_response'])
            expected = {'identity': learned['identity'], 'result_sha256': learned['result_sha256'],
                        'record_sha256': learned['record_sha256']}
            if (response.request_id != request.request_id
                    or task_digest(response.model_dump(mode='json')) != stage['native_response_sha256']
                    or response.factors.get('private_qs_learning') != expected):
                raise TaskConflict('QS learning lost its original saved native proposal')
            return response
        if stage['phase'] != 'not_started':
            raise TaskConflict('QS native proposal execution is unknown; no automatic replay is allowed')
        stage = self._save({**stage, 'phase': 'dispatching',
            'private_record_sha256': learned['record_sha256'], 'result_sha256': learned['result_sha256']})
        response = self.parent.assembly.client.native_routes.propose(request)
        response = response.model_copy(update={'factors': {**response.factors,
            'private_qs_learning': {'identity': learned['identity'], 'result_sha256': learned['result_sha256'],
                'record_sha256': learned['record_sha256']}}}, deep=True)
        self._save({**stage, 'phase': 'returned', 'native_response': response.model_dump(mode='json'),
            'native_response_sha256': task_digest(response.model_dump(mode='json'))})
        return response

    def recover_saved_proposal(self, request):
        with self.recovery_guard():
            _, learned, identity, saved = self._saved_work(request)
            if saved is None:
                raise TaskConflict('QS learning has no saved completed result; no processor replay is allowed')
            state = self.worker.store.get(identity)['state']
            if state not in {'processing', 'output_formed'}:
                raise TaskConflict('QS learning has unresolved wait/failure state; explicit diagnosis required')
            if self._native_stage(learned)['phase'] not in {'not_started', 'returned'}:
                raise TaskConflict('QS native proposal execution is unknown; no automatic replay is allowed')
            if state == 'processing':
                self.worker._finalize(identity, saved, recovered=True)
            checked_result(self.worker, identity)
            if learned['state'] != 'formed':
                learned = self._save({**learned, 'state': 'formed', 'result_sha256': saved['result_sha256']})
            return self._native_proposal(request, learned)

    def propose(self, request):
        with self.parent.bindings.read_guard():
            plan = self._current(request)
            learned = None
            if plan is not None:
                objects, history = self._sources(plan, request)
                key = self.PREFIX + task_digest([self.parent.assembly.client.simulation_id, plan.context.model_dump(mode='json')])
                if any(r['key'] == key for r in self._records()):
                    raise TaskConflict('QS private feedback already claimed; query its original saved result')
                self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True))
                prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
                identity = self.worker.register(prepared, request_id=key)
                learned = self._save({'key': key, 'state': 'preparing', 'identity': identity.as_dict(),
                    'source_sha256': task_digest(objects), 'history': history,
                    'native_request': request.model_dump(mode='json'),
                    'native_request_sha256': task_digest(request.model_dump(mode='json'))})
                self._save({'key': self._native_key(learned), 'identity': learned['identity'],
                    'source_sha256': learned['source_sha256'],
                    'native_request_sha256': learned['native_request_sha256'], 'phase': 'not_started'})
                self.worker.execute(identity, prepared)
                saved = checked_result(self.worker, identity)
                if saved['result']['payload'].get('choice') != 'record_feedback':
                    raise TaskConflict('QS evaluation history did not form its original private record')
                learned.update(state='formed', result_sha256=saved['result_sha256'])
                learned = self._save(learned)
            # This is a declared native business operation after an independent
            # private micro step, never fallback from a failed micro action.
            if learned is not None:
                return self._native_proposal(request, learned)
            return self.parent.assembly.client.native_routes.propose(request)

    def evidence(self):
        self.check()
        records = self._records()
        return {'version': self.VERSION, 'records': records,
                'native_proposals': [self._native_stage(record) for record in records],
                'limits': 'Original QS-A12 private recording only. Same-call saved-result recovery does not replay '
                    'the micro action or an unknown native proposal. Monthly formal decisions stay native; '
                    'no applied judgment, cost error or training.'}
