"""Original BANK-A01 consumes native monthly requests; the native scheduler executes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pydantic import Field

from integration.bank_financing_private import checked_result, evidence_binding
from integration.bank_monthly_native_sources import monthly_bank_scope, prior_monthly_strategies, quote_from_monthly, selected_strategy
from integration.bank_monthly_native_recovery import original_bank_monthly_work, validate_saved_bank_monthly_stage, recover_saved_bank_monthly_proposal
from integration.bank_strategy_actions import BankStrategyActionAssembler
from integration.bank_strategy_results import BankStrategyResultWorker
from integration.bank_monthly_risk import bind_monthly_risk, received_financing_cases, result_operation, result_judgment
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, Measured, StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class BankMonthlyPlan(StrictRecord):
    organization_id: TextId
    tick: int = Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    observation_ref: ref_type('Observation')
    utility: Measured
    probability: Measured


class BankMonthlySettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest
    allow_saved_recovery: bool = False


class BankMonthlyApplication:
    VERSION = 'gba-v1-bank-monthly-strategy.v4'
    PREFIX = 'bank_monthly_native_request:'

    def __init__(self, *, parent, settings):
        self.parent, self.assembly = parent, parent.assembly
        self.settings = BankMonthlySettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        document = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(document) != {'schema_version', 'run_id', 'plans'} or document['schema_version'] != 'bank-monthly-strategy-input.v1'
                or document['run_id'] != self.assembly.client.run_id):
            raise TaskConflict('Monthly Bank strategy requires its pinned independent original sources')
        self.plans = [BankMonthlyPlan.model_validate(p) for p in document['plans']]
        if not self.plans or len({(p.organization_id, p.tick) for p in self.plans}) != len(self.plans):
            raise TaskConflict('Monthly Bank strategies require unique original organization/time plans')
        for p in self.plans:
            if (p.context.actor_id != parent.organizations.get(p.organization_id).actor_id or p.context.run_id != document['run_id']
                    or p.context.business_time.offset != p.tick or p.context.contract_ref.id != 'BANK-A01'
                    or p.context.scope.kind != 'organization' or p.context.scope.ref.id != p.organization_id):
                raise TaskConflict('Monthly Bank sources change own organization, action or business time')
        self._plans_sha = task_digest([p.model_dump(mode='json') for p in self.plans])
        self._settings_sha = task_digest(self.settings.model_dump(mode='json'))
        self._code = self._descriptors()
        self._bound = {}
        self.recovery_guard = parent.read_guard
        routes = self.assembly.client.native_routes
        if routes.settings.query_saved_bank_monthly_on_error and not self.settings.allow_saved_recovery:
            raise TaskConflict('Bank monthly query on error requires explicit saved-result recovery authorization')
        if (not routes.settings.micro_bank_monthly_strategy_scope
                or ('Bank', 'decide_monthly_operation') in routes._proposals
                or ('Bank', 'monthly_enterprise_operation') in routes._decisions):
            raise TaskConflict('Monthly Bank strategy requires exclusive original proposal and final routes')
        self.assembler = BankStrategyActionAssembler(registry=parent.registry, organizations=parent.organizations,
            provider=self, macro_version='gba-public-2026-08-21', source_mode='formal',
            policy_version=parent.settings.policy_version, model_version=self.assembly.client.versions['model'])
        self.worker = BankStrategyResultWorker(store=self.assembly.client.tasks, snapshots=parent.snapshots,
            registry=parent.registry, client_version=self.VERSION, model_version=self.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation, validate_wait=self.validate_wait, validate_recovery=self.validate_recovery)

    @staticmethod
    def _descriptors():
        return {name: module_factory_descriptor(fn, 'bank-monthly-sources.v2') for name, fn in
                [('scope', monthly_bank_scope), ('history', prior_monthly_strategies),
                 ('selection', selected_strategy), ('quote', quote_from_monthly),
                 ('original_recovery', original_bank_monthly_work), ('validate_recovery', validate_saved_bank_monthly_stage),
                 ('recover_proposal', recover_saved_bank_monthly_proposal),
                 ('bind_risk',bind_monthly_risk),('received_risk_cases',received_financing_cases),
                 ('result_operation',result_operation),('result_judgment',result_judgment)]}

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Monthly Bank strategy independent source bytes changed')

    def check_components(self):
        self._check_file()
        if (self._plans_sha != task_digest([p.model_dump(mode='json') for p in self.plans])
                or self._settings_sha != task_digest(self.settings.model_dump(mode='json')) or self._code != self._descriptors()
                or self.worker.store is not self.assembly.client.tasks or self.worker.registry is not self.parent.registry
                or self.worker.snapshots is not self.parent.snapshots or self.assembler.organizations is not self.parent.organizations
                or self.assembler.provider is not self):
            raise TaskConflict('Monthly Bank strategy changes original sources or shared runtime')
        if self.recovery_guard is not self.parent.read_guard:
            raise TaskConflict('Monthly Bank recovery changes its original shared guard')

    def _current(self, request):
        self.parent._check()
        scope = monthly_bank_scope(self.assembly, request, purpose='propose')
        plans = [p for p in self.plans if (p.organization_id, p.tick) == (scope['organization_id'], scope['tick'])]
        if len(plans) != 1:
            raise TaskConflict('Monthly Bank request lacks its exact original authorized source plan')
        return plans[0], scope

    def _sources(self, plan, request):
        history = prior_monthly_strategies(self, organization_id=plan.organization_id, tick=plan.tick)
        scope = monthly_bank_scope(self.assembly, request, purpose='propose')
        observed = {'scope': scope, 'native_request_sha256': task_digest(request.model_dump(mode='json')),
                    'prior_own_monthly_strategy': history}
        space, = [r['value'] for r in plan.objects if r['ref']['kind']=='LendingStrategySpace']
        if space.get('monthly_risk_policy_ref') is not None:
            observed.update(macro_environment=deepcopy(request.inputs['macro_environment']),
                received_own_financing_cases=received_financing_cases(self,organization_id=plan.organization_id,tick=plan.tick))
        objects = deepcopy(plan.objects)
        evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), observed)
        bind_monthly_risk(objects,observed=observed,plan=plan)
        observation, = [r['value'] for r in objects if r['ref'] == plan.observation_ref.model_dump(mode='json')]
        if observation['interval'] != {'state': 'known', 'value': None}:
            raise TaskConflict('Monthly Bank signal must be its original unbound own-history placeholder')
        amount = {'value': str(len(history)), 'unit': 'count', 'basis_ref': plan.native_evidence_ref.model_dump(mode='json')}
        observation['interval']['value'] = {'lower': amount, 'upper': deepcopy(amount)}
        return objects, observed

    def project(self, *, context, organization_id, grants):
        plan, request = self._bound[task_digest(context.model_dump(mode='json'))]
        self._current(request)
        if context != plan.context or organization_id != plan.organization_id:
            raise TaskConflict('Monthly Bank reading changes its original private source binding')
        objects, _ = self._sources(plan, request)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'native-bank-monthly:' + task_digest(objects), 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'), 'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        plan, request = self._bound[prepared.context_sha256]
        self._current(request)
        if prepared.context != plan.context or row['identity']['organization_id'] != plan.organization_id:
            raise TaskConflict('Monthly Bank worker changes original request or invocation')
        prepared.reading.recheck()
        return True

    def validate_wait(self, *args, **kwargs):
        raise TaskConflict('Unresolved monthly Bank strategy requires explicit diagnosis, never a rule fallback')

    def _records(self):
        with self.assembly.client.tasks._lock:
            records = [json.loads(v) for v, in self.assembly.client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ?', (self.PREFIX + '%',))]
        if any(r['record_sha256'] != task_digest({k: v for k, v in r.items() if k != 'record_sha256'}) for r in records):
            raise TaskConflict('Monthly Bank technical evidence changed')
        return records

    def validate_recovery(self, row, saved, snapshot):
        return validate_saved_bank_monthly_stage(self, row, saved, snapshot)

    def recover_saved_proposal(self, request):
        return recover_saved_bank_monthly_proposal(self, request)

    @staticmethod
    def _proposal_response(request, plan, scope, identity, saved, reading):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        selected_strategy(saved)
        if (plan.utility.unit != 'score' or plan.probability.unit != 'probability'
                or not 0 <= float(plan.utility.value) <= 1 or not 0 <= float(plan.probability.value) <= 1):
            raise TaskConflict('Monthly Bank indicators require explicitly sourced bounded units')
        reading.resolve(plan.utility.basis_ref)
        reading.resolve(plan.probability.basis_ref)
        action = result_operation(saved)
        judgment = result_judgment(saved)
        note = judgment.interpretation if judgment else saved['result']['payload']['note']
        return AgentProposalResponseV1(request_id=request.request_id, action_type=action, accepted=True,
            utility=float(plan.utility.value), probability=float(plan.probability.value), reason=note,
            data={'label': 'Monitored received borrower financing-case risk' if action=='monitor_borrower_risk' else 'Reviewed future private lending strategy', 'description': note}, factors={
                'micro_action_id': 'BANK-A01', 'micro_task_key': identity.key,
                'micro_result_sha256': saved['result_sha256'], 'native_bank_monthly_scope': scope})

    def propose(self, request):
        with self.parent.read_guard():
            plan, scope = self._current(request)
            key = self.PREFIX + task_digest([self.assembly.client.simulation_id, scope, request.request_id])
            if any(r['key'] == key for r in self._records()):
                raise TaskConflict('Monthly Bank request already claimed; diagnose original transport')
            objects, observed = self._sources(plan, request)
            record = self.parent._save(key, {'key': key, 'scope': scope, 'state': 'preparing',
                'native_request': request.model_dump(mode='json'), 'observed': observed,
                'context': plan.context.model_dump(mode='json'), 'action_input': plan.action_input,
                'native_evidence_ref': plan.native_evidence_ref.model_dump(mode='json'), 'source_sha256': task_digest(objects)})
            self._bound[task_digest(record['context'])] = (plan, request.model_copy(deep=True))
            prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
            identity = self.worker.register(prepared, request_id=key + ':BANK-A01')
            record['identity'] = identity.as_dict()
            record = self.parent._save(key, record)
            self.worker.execute(identity, prepared)
            saved = checked_result(self.worker, identity)
            response = self._proposal_response(request, plan, scope, identity, saved, prepared.reading)
            record.update(state='formed', result_sha256=saved['result_sha256'],
                          proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self.parent._save(key, record)
            return response

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1, AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.parent.read_guard():
            self.parent._check()
            scope = monthly_bank_scope(self.assembly, request, purpose='decide')
            record, = [r for r in self._records() if r['state'] == 'formed' and r['scope'] == scope]
            original = AgentProposalRequestV1.model_validate(record['native_request'])
            plan, _ = self._current(original)
            objects, observed = self._sources(plan, original)
            saved = checked_result(self.worker, TaskIdentity(**record['identity']))
            selected_strategy(saved)
            action = result_operation(saved)
            proposal, = [t['output'] for t in self.assembly.client.tasks.for_organization(
                run_id=self.assembly.client.run_id, organization_id=plan.organization_id)
                if t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == 'decide_monthly_operation'
                and t['state'] == 'output_formed' and t['output'].get('factors', {}).get('native_bank_monthly_scope') == scope]
            if (record['source_sha256'] != task_digest(objects) or record['observed'] != observed
                    or record['result_sha256'] != saved['result_sha256'] or record['proposal_response_sha256'] != task_digest(proposal)
                    or request.decision_support.get('decision_factors') != proposal['factors']
                    or request.decision_support.get('accepted') is not True or proposal['accepted'] is not True
                    or request.decision_support.get('action_type') != action or proposal['action_type'] != action
                    or action not in request.constraints.allowed_actions):
                raise TaskConflict('Monthly Bank final changes original source, saved result or proposal')
            response = AgentDecisionResponseV1(request_id=request.request_id, agent_id=plan.organization_id,
                action_type=action, decision=True, reason=proposal['reason'],
                data={**proposal['factors'], 'proposal_response_sha256': task_digest(proposal)})
            ExternalAgentDecisionProvider._validated_action(request, response)
            return response

    def evidence(self):
        self.check_components()
        result = {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256, 'requests': self._records(),
            'source_implementations': self._code,
            'saved_recovery': {'enabled': self.settings.allow_saved_recovery,
                'boundary': 'Only original durable completed BANK-A01 in its current native call; no processor replay, restart or resubmission.'},
            'limits': 'Independent synthetic complete portfolio/capacity disclosures and private policy thresholds. '
                'Only actual earlier own native operations bound future quotes. Native capability changes are not cash '
                'or commitments. No existing contract, loan, cash, formal credit or resource ledger is changed here.'}
        if any(r['ref']['kind']=='MonthlyBorrowerRiskPolicy' for p in self.plans for r in p.objects):
            result['original_own_monthly_events']=[e.model_dump(mode='json') for e in self.assembly.engine.events.events
                if e.event_type=='agent_operation' and e.agent_id in {p.organization_id for p in self.plans} and e.project_id is None
                and e.data.get('operation') in {'review_credit_pipeline','adjust_credit_terms','monitor_borrower_risk'}]
        return result
