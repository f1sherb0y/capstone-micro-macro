"""Bind original same-round QS-A06 results to native per-bid evaluations.

Only comparable evaluations map here. Clarification, exclusion recommendations
and unknown sources stay unresolved rather than becoming native approvals.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from integration.qs_bid_actions import QSBidActionAssembler
from integration.qs_bid_results import QSBidResultWorker
from integration.qs_evaluation_learning import QSEvaluationLearning, QSEvaluationLearningSettings
from integration.qs_bid_admissibility import QSBidAdmissibility, QSBidAdmissibilitySettings
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, StrictRecord, TextId, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class NativeBidBinding(StrictRecord):
    contractor_id: TextId
    bid_ref: ref_type('Bid')
    evidence_ref: ref_type('Evidence')
    # An independently sourced professional score; never inferred from price.
    evaluation_score: Measured


class QSBidNativePlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int = Field(ge=0)
    currency: TextId
    context: ActionContext
    action_input: dict
    objects: list[dict]
    bids: list[NativeBidBinding] = Field(min_length=1)

    @model_validator(mode='after')
    def original_context(self):
        if (self.context.contract_ref.id != 'QS-A06' or self.context.execution_mode == 'offline_fixture'
                or self.context.scope.kind != 'project' or self.context.scope.ref.id != self.project_id
                or self.context.business_time.offset != self.tick
                or len({row.contractor_id for row in self.bids}) != len(self.bids)
                or len({row.bid_ref.key() for row in self.bids}) != len(self.bids)
                or len({row.evidence_ref.key() for row in self.bids}) != len(self.bids)):
            raise ValueError('Native QS plan needs an exact original project, tick and distinct bid sources')
        return self


class QSBidNativeSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest
    learning: QSEvaluationLearningSettings | None = None
    publish_native_bid_questions: bool = False
    admissibility: QSBidAdmissibilitySettings | None = None


class QSBidNativeBridge:
    VERSION = 'gba-v1-qs-bid.v8'
    PREFIX = 'qs_bid_native_round:'

    def __init__(self, *, assembly, bindings, settings, policy_version):
        self.assembly, self.bindings = assembly, bindings
        self.settings = QSBidNativeSettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        document = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(document) != {'schema_version', 'run_id', 'plans'}
                or document['schema_version'] != 'qs-bid-native-input.v1'
                or document['run_id'] != assembly.client.run_id):
            raise TaskConflict('QS bid source changes its explicit schema or run')
        self.plans = [QSBidNativePlan.model_validate(row) for row in document['plans']]
        selectors = [(p.organization_id, p.project_id, p.tick) for p in self.plans]
        if (not selectors or len(set(selectors)) != len(selectors)
                or len({p.context.read_token for p in self.plans}) != len(selectors)):
            raise TaskConflict('QS round plans require unique selectors and read tokens')
        self._bound = {}
        self.assembler = QSBidActionAssembler(registry=bindings.registry, organizations=bindings.organizations,
            provider=self, macro_version='gba-public-2026-08-21', source_mode='formal', methods=bindings.methods,
            policy_version=policy_version, model_version=assembly.client.versions['model'], model_host=bindings.model_host)
        self.worker = QSBidResultWorker(store=assembly.client.tasks,
            snapshots=InvocationSnapshotStore(assembly.client.tasks), registry=bindings.registry,
            client_version=self.VERSION, model_version=assembly.client.versions['model'],
            validate_invocation=self.validate_invocation, validate_wait=self.validate_wait)
        self._other_decision = assembly.client.decision_handler
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._plans_sha256 = task_digest([p.model_dump(mode='json') for p in self.plans])
        self._source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self._original_other_decision = self._other_decision
        self._components = (assembly,bindings,self.worker,self.assembler,bindings.registry,
            bindings.organizations,bindings.methods,bindings.read_guard,assembly.client.tasks)
        self.learning = (QSEvaluationLearning(parent=self, settings=self.settings.learning, policy_version=policy_version)
                         if self.settings.learning is not None else None)
        self._original_learning = self.learning
        self.admissibility = (QSBidAdmissibility(parent=self,settings=self.settings.admissibility)
            if self.settings.admissibility is not None else None)
        self._original_admissibility = self.admissibility

    @property
    def store(self):
        return self.worker.store

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('QS bid sources differ from the pinned input file')

    def _check(self):
        self.assembly._validate_components()
        self._check_file()
        actual = (self.assembly,self.bindings,self.worker,self.assembler,self.bindings.registry,
            self.bindings.organizations,self.bindings.methods,self.bindings.read_guard,self.assembly.client.tasks)
        if (any(current is not original for current,original in zip(actual,self._components))
                or self.learning is not self._original_learning
                or self.admissibility is not self._original_admissibility
                or self._other_decision != self._original_other_decision
                or task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256
                or task_digest([p.model_dump(mode='json') for p in self.plans]) != self._plans_sha256
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != self._source_sha256
                or self.worker.store is not self.assembly.client.tasks or self.worker.registry is not self.bindings.registry
                or self.assembler.organizations is not self.bindings.organizations):
            raise TaskConflict('QS evaluation substitutes its original worker, registry or authority')
        if self.learning is not None:
            self.learning.check()
        if self.admissibility is not None:
            self.admissibility.check()

    def install(self):
        client = self.assembly.client
        with client._lock:
            routes = getattr(client, 'native_routes', None)
            if (routes is None or not routes.settings.micro_qs_evaluation_scope or client._tender_feedback is not None
                    or routes.settings.mixed_qs_learning_scope != (self.learning is not None)
                    or client._calls or client._request_hashes or client.decision_handler is not self._other_decision
                    or client.binding_installation_blocked()):
                raise TaskConflict('QS routes require explicit micro task scoping before all bindings and requests')
            client.bind_proposal_handler(role='QS', operation='evaluate_bid', handler=self.propose, client_version=self.VERSION)
            if self.learning is not None:
                client.bind_proposal_handler(role='QS', operation='decide_monthly_operation',
                    handler=self.learning.propose, client_version=self.VERSION + ':private-learning')
            client.decision_handler = self.decide

    def _current(self, request):
        self._check()
        if request.agent.role != 'QS' or request.operation != 'evaluate_bid':
            raise TaskConflict('QS bridge requires its original native evaluation operation')
        scope = self.assembly.client.native_routes._evaluation_scope(request, purpose='propose')
        engine = self.assembly.engine
        project = engine.projects[scope['project_id']]
        contractor = engine.agents.get(scope['contractor_id'])
        qs = engine.agents.get(request.agent.agent_id)
        bid = [b for b in project.bids if b['contractor_id'] == scope['contractor_id']][0]
        # The frozen evaluate_bid call supplies neither tick nor environment;
        # its external adapter therefore always emits tick 0. Use the actual
        # attached engine clock for scope; preserve the original wire identity.
        if (type(request.metadata.get('tick')) is not int or request.metadata['tick'] != 0
                or request.metadata.get('project_id') != project.project_id
                or project.current_stage.value != 'bid_evaluation'
                or project.model_dump(mode='json') != request.inputs.get('project')
                or contractor is None or contractor.role != 'Contractor'
                or contractor.model_dump(mode='json') != request.inputs.get('contractor')
                or qs is None or qs.role != 'QS' or bid != request.inputs.get('bid')):
            raise TaskConflict('QS request substitutes actual current project, enterprise or bid')
        matches = [p for p in self.plans if (p.organization_id, p.project_id, p.tick) ==
                   (request.agent.agent_id, project.project_id, scope['tick'])]
        if len(matches) != 1:
            raise TaskConflict('QS current evaluation has no exact independently supplied source plan')
        plan = matches[0]
        if (plan.context.run_id != self.assembly.client.run_id
                or {b.contractor_id for b in plan.bids} != {b['contractor_id'] for b in project.bids}
                or len(plan.bids) != len(project.bids)):
            raise TaskConflict('QS source plan changes run or complete actual same-round bid set')
        grants = self.bindings.organizations.grants(plan.context, 'QS-A06', 'QS')
        if not grants or grants[0].organization_id != request.agent.agent_id:
            raise TaskConflict('QS current evaluation lacks its original appointed organization authority')
        return plan, project, scope

    def _source_objects(self, plan, project):
        objects = deepcopy(plan.objects)
        by_ref = {task_digest(row['ref']): row for row in objects}
        if len(by_ref) != len(objects):
            raise TaskConflict('QS source plan repeats a concrete original object')
        origins = []
        for binding in plan.bids:
            bids = [b for b in project.bids if b['contractor_id'] == binding.contractor_id]
            events = [e for e in project.event_log if e.get('event_type') == 'bid_submitted'
                      and e.get('agent_id') == binding.contractor_id and e.get('project_id') == project.project_id]
            if len(bids) != 1 or not events or events[-1]['tick'] >= plan.tick:
                raise TaskConflict('QS bid source lacks a prior actual native submission')
            bid, event = bids[0], events[-1]
            if (event['data'].get('contractor_id') != binding.contractor_id
                    or any(event['data'].get(k) != bid.get(k) for k in ('bid_price', 'expected_profit', 'risk_level'))):
                raise TaskConflict('QS native bid no longer agrees with its actual submission event')
            # The shared host authenticates the original transport journal. Only
            # public bid/event provenance enters QS; private bidder discussions do not.
            client = self.assembly.client
            feedback = client._tender_feedback
            if feedback is None:
                raise TaskConflict('QS native bid requires its original Contractor feedback journal')
            records = [r for r in feedback.for_organization(organization_id=binding.contractor_id)
                       if r['event_id'] == event['event_id'] and r['effect'] == 'native_bid_submitted']
            if len(records) != 1:
                raise TaskConflict('QS native bid has no unique authenticated actual submission record')
            record = records[0]
            for name, purpose in [('proposal_identity', 'propose'), ('final_identity', 'decide')]:
                identity = TaskIdentity(**record[name])
                task = client.tasks.get(identity)
                output = task['output'] or {}
                factors = output.get('factors' if purpose == 'propose' else 'data', {})
                if (identity.organization_id != binding.contractor_id or identity.purpose != purpose
                        or task['state'] != 'output_formed' or factors.get('micro_result_sha256') != record['micro_result_sha256']):
                    raise TaskConflict('QS bid source lost its actual original submitted micro decision')
            projection = record['projection']
            if (projection['project_id'] != project.project_id or projection['tick'] != event['tick']
                    or projection['data'].get('bid_price') != bid['bid_price']):
                raise TaskConflict('QS submission provenance changes original project, time or price')
            row = by_ref.get(task_digest(binding.bid_ref.model_dump(mode='json')))
            evidence = by_ref.get(task_digest(binding.evidence_ref.model_dump(mode='json')))
            if (row is None or evidence is None or row['value'].get('price') is not None
                    or row['value'].get('submitted_at') is not None or evidence['value'].get('content_hash') is not None):
                raise TaskConflict('QS observed bid fields require explicit unbound native placeholders')
            value = row['value']
            organization = self.bindings.organizations.get(binding.contractor_id)
            if (value['bidder_organization_id'] != binding.contractor_id or value['bidder_id'] != organization.actor_id
                    or not any(a.role == 'Contractor' and a.function_ref.model_dump(mode='json') == value['function_ref']
                               for a in organization.assignments)
                    or value['status'] != 'submitted' or binding.evidence_ref.model_dump(mode='json') not in value['evidence_refs']):
                raise TaskConflict('QS original bid projection changes the actual registered submitting organization')
            value['price'] = {'state': 'known', 'value': {'value': str(bid['bid_price']), 'currency': plan.currency,
                'basis_ref': binding.evidence_ref.model_dump(mode='json')}}
            value['submitted_at'] = {'clock_ref': plan.context.business_time.clock_ref.model_dump(mode='json'), 'offset': event['tick']}
            origin = {'event_id': event['event_id'], 'tick': event['tick'], 'project_id': project.project_id,
                'contractor_id': binding.contractor_id, 'bid': deepcopy(bid),
                'micro_result_sha256': record['micro_result_sha256'], 'feedback_record_sha256': record['record_sha256']}
            evidence['value']['content_hash'] = task_digest(origin)
            parsed = EvidenceRecord.model_validate(evidence['value'])
            if parsed.source_kind != 'synthetic' or parsed.basis_kind != 'observed':
                raise TaskConflict('QS native source must remain explicit simulator observation evidence')
            origins.append(origin)
        return objects, origins

    def _key(self, plan):
        return self.PREFIX + task_digest([self.assembly.client.simulation_id, plan.organization_id, plan.project_id, plan.tick])

    def _record(self, plan):
        with self.worker.store._lock:
            row = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key(plan),)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        if (value['record_sha256'] != task_digest({k: v for k, v in value.items() if k != 'record_sha256'})
                or value['source_file_sha256'] != self.settings.file_sha256):
            raise TaskConflict('QS round record changed its original source or digest')
        return value

    def _save(self, plan, value):
        value = deepcopy(value)
        value['record_sha256'] = task_digest({k: v for k, v in value.items() if k != 'record_sha256'})
        with self.worker.store._transaction():
            self.worker.store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                (self._key(plan), canonical(value)))
        return value

    def project(self, *, context, organization_id, grants):
        bound = self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or bound[0].organization_id != organization_id:
            raise TaskConflict('QS projection requires the actual currently bound native request')
        plan, request = bound
        _, project, _ = self._current(request)
        objects, origins = self._source_objects(plan, project)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'native-submitted-bids:' + task_digest(origins), 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'), 'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        bound = self._bound.get(prepared.context_sha256)
        if bound is None:
            raise TaskConflict('QS execution lost its original native source binding')
        plan, request = bound
        self._current(request)
        if (prepared.context != plan.context or row['identity']['organization_id'] != plan.organization_id
                or prepared.runner.registry is not self.worker.registry):
            raise TaskConflict('QS execution substitutes its current context or original processor')
        prepared.reading.recheck()
        return True

    def validate_wait(self, *args, **kwargs):
        raise TaskConflict('Pending QS evaluation requires source diagnosis; no automatic resubmission')

    def _result(self, plan, record):
        if record['state'] != 'formed':
            raise TaskConflict('QS original round remains unresolved; diagnose before continuing')
        identity = TaskIdentity(**record['identity'])
        if (identity.run_id != plan.context.run_id or identity.organization_id != plan.organization_id
                or identity.action_id != 'QS-A06' or identity.context_sha256 != task_digest(plan.context.model_dump(mode='json'))):
            raise TaskConflict('QS saved result substitutes its original run, appointed organization or context')
        saved = self.worker.get_record(identity)
        task = self.worker.store.get(identity)
        from integration.qs_no_valid_outcome import no_valid_round_is_authorized
        permitted = saved is not None and saved['result']['kind']=='completed' and (saved['result']['payload'].get('choice')=='evaluate'
            or no_valid_round_is_authorized(self,plan,saved['result']))
        if (saved is None or saved['result_sha256'] != record['result_sha256']
                or task['state'] != 'output_formed' or task['output'] != saved['result']
                or saved['result']['kind'] != 'completed' or not permitted):
            raise TaskConflict('Native scores require an original comparison or fully delegated known-failure round')
        return identity, saved['result']

    def propose(self, request):
        from decimal import Decimal
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1

        with self.bindings.read_guard():
            plan, project, scope = self._current(request)
            objects, origins = self._source_objects(plan, project)
            source_sha256 = task_digest(objects)
            record = self._record(plan)
            if record is None:
                self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True))
                record = self._save(plan, {'state': 'preparing', 'native_request': request.model_dump(mode='json'),
                    'source_file_sha256': self.settings.file_sha256, 'source_sha256': source_sha256, 'origins': origins})
                prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
                identity = self.worker.register(prepared, request_id='qs-native-round:' + self._key(plan))
                outcome = self.worker.execute(identity, prepared)
                record.update(state='formed', identity=identity.as_dict(), result_sha256=task_digest(outcome['result']))
                record = self._save(plan, record)
            if record['source_sha256'] != source_sha256 or record['origins'] != origins:
                raise TaskConflict('QS round cannot reuse its evaluation after original source changes')
            original = self.worker.get_record(TaskIdentity(**record['identity']))
            if original is not None and original['result']['kind']=='completed' and original['result']['payload']['choice']=='clarify':
                if self.settings.publish_native_bid_questions:
                    from integration.qs_bid_clarification import publish_bid_clarification_questions
                    publish_bid_clarification_questions(self, record['identity'], request)
                raise TaskConflict('Original QS bid clarification awaits actual bidder answers and a new authorized evaluation')
            identity, result = self._result(plan, record)
            binding = next(b for b in plan.bids if b.contractor_id == scope['contractor_id'])
            rows = [r for r in result['payload']['evaluations'] if r['bid_ref'] == binding.bid_ref.model_dump(mode='json')]
            pending_exclusion = (self.admissibility is not None
                and self.admissibility.plan(plan,scope) is not None and len(rows)==1
                and rows[0]['status']=='exclusion_recommended' and not rows[0]['unresolved_questions'])
            if len(rows) != 1 or rows[0]['status'] != 'comparable' and not pending_exclusion or rows[0]['unresolved_questions']:
                raise TaskConflict('QS unknown, clarification or exclusion recommendation cannot become native approval')
            if pending_exclusion:
                self.admissibility.remember_request(plan,request,scope)
            evidence_rows = [row for row in objects if row['ref'] == binding.evaluation_score.basis_ref.model_dump(mode='json')]
            score = Decimal(binding.evaluation_score.value)
            if len(evidence_rows) != 1 or binding.evaluation_score.unit != 'score' or not 0 <= score <= 1:
                raise TaskConflict('QS score needs explicit original professional evidence and bounded score units')
            score_evidence = EvidenceRecord.model_validate(evidence_rows[0]['value'])
            if score_evidence.effective_window is not None and not score_evidence.effective_window.contains(plan.context.business_time):
                raise TaskConflict('QS score basis is outside its original effective window')
            return AgentProposalResponseV1(request_id=request.request_id, action_type='evaluate_bid', accepted=True,
                utility=float(score), probability=1.0,
                reason=(rows[0]['explanation'] if not pending_exclusion else
                    'Independently evidenced score retained; original known rule failure requires delegated final admissibility review.'),
                data={'evaluation_score': float(score)},
                factors={'micro_action_id': 'QS-A06', 'micro_task_key': identity.key, 'micro_result_sha256': record['result_sha256'],
                    'native_evaluation_scope': scope, 'source_sha256': source_sha256,
                    'score_basis_ref': binding.evaluation_score.basis_ref.model_dump(mode='json')})

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1

        if (request.agent.role, request.decision_type) != ('QS', 'qs_bid_evaluation'):
            from integration.qs_no_valid_outcome import decide_no_valid_selection
            no_valid = decide_no_valid_selection(self,request)
            if no_valid is not None:return no_valid
            return self._other_decision(request)
        with self.bindings.read_guard():
            self._check()
            scope = self.assembly.client.native_routes._evaluation_scope(request, purpose='decide')
            factors = request.decision_support.get('decision_factors', {})
            plans = [p for p in self.plans if (p.organization_id, p.project_id, p.tick) ==
                     (request.agent.agent_id, scope['project_id'], scope['tick'])]
            if len(plans) != 1:
                raise TaskConflict('QS final decision lacks its original current round plan')
            plan = plans[0]
            record = self._record(plan)
            if record is None:
                raise TaskConflict('QS final decision has no original micro result')
            identity, result = self._result(plan, record)
            # Read the exact per-bid proposal task; do not form another score or
            # run the round worker again during the final transport phase.
            proposals = [row for row in self.worker.store.for_organization(run_id=plan.context.run_id,
                organization_id=plan.organization_id) if row['identity']['purpose'] == 'propose'
                and row['identity']['action_id'] == 'evaluate_bid' and row['state'] == 'output_formed'
                and row['output'].get('factors', {}).get('native_evaluation_scope') == scope]
            if ('evaluate_bid' not in request.constraints.allowed_actions
                    or len(proposals) != 1 or proposals[0]['output']['factors'] != factors
                    or factors.get('micro_result_sha256') != record['result_sha256']
                    or factors.get('micro_task_key') != identity.key):
                raise TaskConflict('QS final decision changes its actual original per-bid proposal')
            objects, origins = self._source_objects(plan, self.assembly.engine.projects[plan.project_id])
            if task_digest(objects) != record['source_sha256'] or origins != record['origins']:
                raise TaskConflict('QS final evaluation sources changed after its micro decision')
            if self.admissibility is not None and self.admissibility.plan(plan,scope) is not None:
                return self.admissibility.decide(request,parent_plan=plan,proposal=proposals[0]['output'])
            return AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
                action_type='evaluate_bid', decision=True, reason=proposals[0]['output']['reason'],
                data={'micro_action_id': 'QS-A06', 'micro_result_sha256': record['result_sha256'],
                    'micro_task_key': identity.key, 'native_evaluation_scope': scope,
                    'evaluation_score': proposals[0]['output']['data']['evaluation_score']})

    def query_native_outcome(self, original_identity, *, organization_id, tick):
        from integration.qs_evaluation_outcome_query import query_qs_evaluation_outcome
        return query_qs_evaluation_outcome(self, original_identity, organization_id=organization_id, tick=tick)

    def query_clarification_review(self, original_identity, *, organization_id, tick):
        from integration.qs_bid_clarification import query_bid_clarification_review
        return query_bid_clarification_review(self, original_identity, organization_id=organization_id, tick=tick)

    def evidence(self):
        self._check()
        return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256,
            'rounds': [record for p in self.plans if (record := self._record(p)) is not None],
            'learning': self.learning.evidence() if self.learning is not None else None,
            'admissibility': self.admissibility.evidence() if self.admissibility is not None else None,
            'limits': 'Comparable evaluate only. Scores require explicit independent evidence; no exclusion or award.'}


def build_application(*, assembly, request, output_directory, offline, settings, authority=None):
    from integration.owner_invitation_native import build_application as build_owner

    if not isinstance(settings, dict) or set(settings) != {'owner_contractor', 'qs_bid', 'policy_version'}:
        raise ValueError('QS composition requires original Owner/Contractor application and explicit QS sources')
    original = build_owner(assembly=assembly, request=request, output_directory=output_directory,
        offline=offline, settings=settings['owner_contractor'],authority=authority)
    try:
        bridge = QSBidNativeBridge(assembly=assembly, bindings=original, settings=settings['qs_bid'],
            policy_version=settings['policy_version'])
        bridge.install()

        def evidence():
            return {'owner_contractor': original.evidence(), 'qs_bid': bridge.evidence()}

        return replace(original, evidence=evidence)
    except Exception:
        original.close()
        raise
