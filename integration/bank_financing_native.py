"""Execute original Bank A02/A03/A04 inside an actual native financing request."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from integration.bank_intake_actions import BankIntakeActionAssembler
from integration.bank_intake_results import BankIntakeResultWorker
from integration.bank_credit_actions import BankCreditActionAssembler
from integration.bank_credit_results import BankCreditResultWorker
from integration.bank_quote_actions import BankQuoteActionAssembler
from integration.bank_quote_results import BankQuoteResultWorker
from integration.bank_strategy_actions import BankStrategyActionAssembler
from integration.bank_strategy_results import BankStrategyResultWorker
from integration.bank_monthly_native import BankMonthlyApplication, BankMonthlySettings
from integration.bank_financing_private import checked_result, evidence_binding, intake_for_review, review_for_quote, native_quote_summary
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings, build_authority_runtime
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, module_client_implementation, module_factory_descriptor
from integration.bank_financing_native_recovery import recover_saved_financing_proposal, saved_financing_preflight, validate_saved_financing_stage
from integration.unstarted_action_continuation import execute_original_stage
from integration.financing_native_outcome_query import query_bank_financing_outcome, query_owner_financing_outcome
from integration.project_financing_native import financing_scope
from integration.owner_financing_native import OwnerFinancingApplication, OwnerFinancingSettings
from integration.bank_arrangement_native import BankArrangementApplication, BankArrangementSettings
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, Reference, StrictRecord, TextId, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest

COMPONENTS = {'BANK-A01': (BankStrategyActionAssembler, BankStrategyResultWorker),
              'BANK-A02': (BankIntakeActionAssembler, BankIntakeResultWorker),
              'BANK-A03': (BankCreditActionAssembler, BankCreditResultWorker),
              'BANK-A04': (BankQuoteActionAssembler, BankQuoteResultWorker)}


class BankFinancingStep(StrictRecord):
    context: ActionContext
    action_input: dict
    objects: list[dict]


class BankStrategyFeedback(StrictRecord):
    observation_ref: ref_type('Observation')
    evidence_ref: ref_type('Evidence')
    quote_policy_ref: ref_type('QuoteAuthorityPolicy')
    quote_evidence_ref: ref_type('Evidence')
    basis: Literal['selected_financing', 'unconfirmed_arrangement_review'] = 'selected_financing'


class BankFinancingPlan(StrictRecord):
    organization_id: TextId
    borrower_id: TextId
    project_id: TextId
    tick: int = Field(ge=1)
    steps: dict[str, BankFinancingStep]
    native_evidence_ref: ref_type('Evidence')
    native_project_evidence_ref: ref_type('Evidence')
    intake_evidence_ref: ref_type('Evidence')
    review_audit_ref: ref_type('Evidence')
    recorded_review_ref: ref_type('RecordedDecision')
    utility: Measured
    probability: Measured
    periods_per_year: int = Field(ge=1)
    native_region_ids: dict[str, TextId]
    strategy_feedback: BankStrategyFeedback | None = None
    monthly_strategy_evidence_ref: ref_type('Evidence') | None = None


class BankFinancingSettings(StrictRecord):
    version: TextId
    policy_version: TextId
    authority: TenderAuthorityRuntimeSettings
    file_path: TextId
    file_sha256: Digest
    owner_financing: OwnerFinancingSettings | None = None
    arrangement: BankArrangementSettings | None = None
    monthly_strategy: BankMonthlySettings | None = None
    allow_saved_recovery: bool = False
    continue_unstarted_actions_on_error: bool = False


class BankFinancingApplication:
    VERSION = 'gba-v1-bank-financing.v13'
    PREFIX = 'bank_financing_native_request:'

    def __init__(self, *, assembly, settings, authority=None, install=True):
        self.assembly = assembly
        self.settings = BankFinancingSettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        document = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(document) != {'schema_version', 'run_id', 'plans'}
                or document['schema_version'] != 'bank-financing-input.v1' or document['run_id'] != assembly.client.run_id):
            raise TaskConflict('Bank financing input changes its declared run or schema')
        self.plans = [BankFinancingPlan.model_validate(p) for p in document['plans']]
        self._plans_sha256=task_digest([p.model_dump(mode='json') for p in self.plans])
        self._settings_sha256=task_digest(self.settings.model_dump(mode='json'))
        selectors = [(p.organization_id, p.borrower_id, p.project_id, p.tick) for p in self.plans]
        if not selectors or len(set(selectors)) != len(selectors):
            raise TaskConflict('Bank financing plans require unique explicit current request selectors')
        initial_organizations = {o.organization_id: o for o in self.settings.authority.organization_snapshot.organizations}
        for plan in self.plans:
            organization = initial_organizations.get(plan.organization_id)
            if organization is None:
                raise TaskConflict('Bank financing plan requires its declared original organization')
            if (plan.strategy_feedback is not None
                    and plan.strategy_feedback.basis == 'unconfirmed_arrangement_review' and self.settings.arrangement is None):
                raise TaskConflict('Unconfirmed arrangement feedback requires original Bank A05 reception')
            expected = {'BANK-A02','BANK-A03','BANK-A04'} | ({'BANK-A01'} if plan.strategy_feedback else set())
            if set(plan.steps) != expected:
                raise TaskConflict('Bank financing needs all original A02/A03/A04 steps')
            for action, step in plan.steps.items():
                c = step.context
                if (c.run_id != assembly.client.run_id or c.contract_ref.id != action or c.execution_mode == 'offline_fixture'
                        or c.scope.kind != 'project' or c.scope.ref.id != plan.project_id
                        or c.business_time.offset != plan.tick or c.actor_id != organization.actor_id
                        or len({task_digest(r['ref']) for r in step.objects}) != len(step.objects)):
                    raise TaskConflict('Bank financing step changes its original action, organization, project or time')
        self._owns_authority = authority is None
        self.authority = authority or build_authority_runtime(assembly=assembly, settings=self.settings.authority)
        if self.authority.assembly is not assembly or self.authority.settings != self.settings.authority:
            raise TaskConflict('Bank financing shared authority must match its exact declared assembly and snapshot')
        self.registry, self.organizations = self.authority.registry, self.authority.organizations
        self.read_guard = self.authority.read_guard
        self.recovery_guard = self.read_guard
        self._recovery_code = self._recovery_descriptors()
        self.snapshots = InvocationSnapshotStore(assembly.client.tasks)
        self._bound, self.assemblers, self.workers = {}, {}, {}
        self._other_decision = assembly.client.decision_handler
        self._implementation = None
        self._native_settings = task_digest(assembly.client.native_routes.settings.model_dump(mode='json'))
        self.owner = None
        self.arrangement = None
        self.monthly = None
        try:
            for action, (assembler, worker) in COMPONENTS.items():
                self.assemblers[action] = assembler(registry=self.registry, organizations=self.organizations, provider=self,
                    macro_version='gba-public-2026-08-21', source_mode='formal', policy_version=self.settings.policy_version,
                    model_version=assembly.client.versions['model'])
                self.workers[action] = worker(store=assembly.client.tasks, snapshots=self.snapshots, registry=self.registry,
                    client_version=self.VERSION, model_version=assembly.client.versions['model'],
                    validate_invocation=self.validate_invocation, validate_wait=self.validate_wait,
                    validate_recovery=self.validate_recovery)
            client, routes = assembly.client, assembly.client.native_routes
            if routes.settings.query_saved_financing_on_error and not self.settings.allow_saved_recovery:
                raise TaskConflict('Bank financing query on error requires explicit saved-result recovery authorization')
            if bool(self.settings.monthly_strategy)!=routes.settings.micro_bank_monthly_strategy_scope:
                raise TaskConflict('Monthly Bank source configuration and exclusive route ownership must agree')
            if (not routes.settings.native_project_financing_scope or routes.settings.native_financing_proposal_transport
                    or 'Bank' in routes.settings.native_financing_proposal_transport_roles
                    or ('Bank', 'bank_project_financing') in routes._decisions):
                raise TaskConflict('Micro bank financing requires exclusive original Bank proposal/final ownership')
            if self.settings.owner_financing is not None:
                if ('Owner' in routes.settings.native_financing_proposal_transport_roles
                        or ('Owner','select_financing_offer') in routes._proposals
                        or ('Owner','owner_financing_selection') in routes._decisions):
                    raise TaskConflict('Micro Owner financing requires exclusive proposal and final ownership')
                self.owner = OwnerFinancingApplication(bank=self,settings=self.settings.owner_financing)
            if self.settings.arrangement is not None:
                if self.owner is None or client.continuation_dispatcher is not None:
                    raise TaskConflict('Bank arrangement requires original micro Owner acceptance and its exclusive initial receipt dispatcher')
                self.arrangement = BankArrangementApplication(bank=self, settings=self.settings.arrangement)
            if self.settings.monthly_strategy is not None:
                if any(p.monthly_strategy_evidence_ref is None for p in self.plans):
                    raise TaskConflict('Monthly Bank strategy requires each original future quote handoff')
                self.monthly = BankMonthlyApplication(parent=self,settings=self.settings.monthly_strategy)
            if install:
                self.install()
        except Exception:
            if self._owns_authority:
                self.authority.close()
            raise

    def proposal_bindings(self):
        result = {('Bank', 'consider_financing'): self.propose}
        if self.monthly is not None:
            result[('Bank','decide_monthly_operation')] = self.monthly.propose
        if self.owner is not None:
            result[('Owner', 'select_financing_offer')] = self.owner.propose
        return result

    def seal_client_binding(self):
        client = self.assembly.client
        with client._lock:
            if (self._implementation is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or any(client.proposal_handlers.get(key) != handler for key, handler in self.proposal_bindings().items())):
                raise TaskConflict('Bank client binding must be sealed once before any requests, preserving every original owned handler')
            self._implementation = module_client_implementation(client)

    def install(self):
        client = self.assembly.client
        with client._lock:
            for (role, operation), handler in self.proposal_bindings().items():
                client.bind_proposal_handler(role=role, operation=operation, handler=handler,
                    client_version=self.VERSION + ':' + role + ':' + operation)
            client.decision_handler = self.decide
            if self.arrangement is not None:
                client.continuation_dispatcher = self.arrangement.dispatch
            self.seal_client_binding()

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Bank financing independent source file differs from its pinned bytes')

    @staticmethod
    def _recovery_descriptors():
        return {name: module_factory_descriptor(fn, 'bank-financing-recovery.v1') for name, fn in (
            ('preflight', saved_financing_preflight), ('recover', recover_saved_financing_proposal),
            ('validate', validate_saved_financing_stage), ('unstarted', execute_original_stage),
            ('bank_outcome_query', query_bank_financing_outcome), ('owner_outcome_query', query_owner_financing_outcome))}

    def _check(self):
        self.assembly._validate_components()
        self._check_file()
        if self._recovery_descriptors() != self._recovery_code:
            raise TaskConflict('Bank financing original recovery implementation changed')
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha256
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha256):
            raise TaskConflict('Bank financing changes its original pinned plans or settings')
        if ((self._implementation is None or module_client_implementation(self.assembly.client) != self._implementation)
                or task_digest(self.assembly.client.native_routes.settings.model_dump(mode='json')) != self._native_settings):
            raise TaskConflict('Bank financing handlers or original route declarations changed')
        for action in COMPONENTS:
            if (self.workers[action].store is not self.assembly.client.tasks
                    or self.workers[action].registry is not self.registry
                    or self.assemblers[action].organizations is not self.organizations):
                raise TaskConflict('Bank financing substituted its original worker, authority or shared journal')
        if self.owner is not None:
            self.owner.check_components()
        if self.arrangement is not None:
            self.arrangement.check_components()
        if self.monthly is not None:
            self.monthly.check_components()

    def _current(self, request):
        self._check()
        scope = financing_scope(self.assembly, request, purpose='propose')
        if (request.agent.role, request.operation) != ('Bank', 'consider_financing'):
            raise TaskConflict('Bank micro pipeline requires its actual original native financing request')
        plans = [p for p in self.plans if (p.organization_id, p.borrower_id, p.project_id, p.tick)
                 == (request.agent.agent_id, scope['owner_id'], scope['project_id'], scope['tick'])]
        if len(plans) != 1:
            raise TaskConflict('Bank financing has no exact authorized source plan for the actual request')
        if self.assembly.engine.projects[scope['project_id']].region not in plans[0].native_region_ids:
            raise TaskConflict('Bank sources lack an explicit mapping for the actual native project region')
        for action, step in plans[0].steps.items():
            grants = self.organizations.grants(step.context, action, 'Bank')
            if not grants or grants[0].organization_id != plans[0].organization_id:
                raise TaskConflict('Bank financing lost current original action authority')
        return plans[0], scope

    def _key(self, request):
        return self.PREFIX + task_digest([self.assembly.client.simulation_id, request.agent.agent_id,
            request.request_id, financing_scope(self.assembly, request, purpose='propose')])

    def _save(self, key, record):
        record = deepcopy(record)
        record['record_sha256'] = task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
        with self.assembly.client.tasks._transaction():
            self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)', (key, canonical(record)))
        return record

    def _records(self, *, prefix=None):
        with self.assembly.client.tasks._lock:
            records = [json.loads(raw) for raw, in self.assembly.client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ?', ((prefix or self.PREFIX) + '%',))]
        if any(r['record_sha256'] != task_digest({k:v for k,v in r.items() if k != 'record_sha256'}) for r in records):
            raise TaskConflict('Bank native request technical record changed')
        return records

    def _sources(self, plan, request, action, previous):
        step = plan.steps[action]
        objects = deepcopy(step.objects)
        native = {'request_sha256': task_digest(request.model_dump(mode='json')),
                  'scope': financing_scope(self.assembly, request, purpose='propose')}
        native['prior_intake_declines'] = self._prior_intake_declines(plan)
        if self.arrangement is not None:
            reviews = plan.strategy_feedback is not None and plan.strategy_feedback.basis == 'unconfirmed_arrangement_review'
            native['prior_arrangement_reviews' if reviews else 'prior_arrangements'] = (
                self.arrangement.prior_reviews if reviews else self.arrangement.prior_arrangements)(
                organization_id=plan.organization_id, tick=plan.tick)
        if self.monthly is not None:
            from integration.bank_monthly_native_sources import prior_monthly_strategies
            native['prior_monthly_strategy'] = prior_monthly_strategies(self.monthly,
                organization_id=plan.organization_id,tick=plan.tick)
        evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), native)
        if action == 'BANK-A01':
            from integration.bank_financing_strategy import selection_feedback
            selection_feedback(self,plan,request,objects)
            return objects
        app_ref = step.action_input['application_ref']
        application, = [r['value'] for r in objects if r['ref'] == app_ref]
        if (application['borrower_id'] != plan.borrower_id or application['lender_id'] != plan.organization_id
                or application['requested']['value'] is not None or application['requested']['currency'] != 'HKD'):
            raise TaskConflict('Bank application projection changes its declared unbound amount or actual parties')
        application['requested']['value'] = str(request.inputs['requested_amount'])
        application['requested']['basis_ref'] = plan.native_evidence_ref.model_dump(mode='json')
        region = plan.native_region_ids[self.assembly.engine.projects[plan.project_id].region]
        evidence_binding(objects, plan.native_project_evidence_ref.model_dump(mode='json'),
            {'scope': native['scope'], 'region_id': region})
        purpose, = [r['value'] for r in objects if r['ref'] == application['purpose_ref']]
        if purpose['project_region_id'] != {'state': 'known', 'value': None}:
            raise TaskConflict('Bank project region must bind its declared native placeholder')
        purpose['project_region_id']['value'] = region
        for row in objects:
            if row['ref']['kind'] == 'Project':
                if row['value']['region_id'] is not None:
                    raise TaskConflict('Bank project source must bind its actual region once')
                row['value']['region_id'] = region
        if action in {'BANK-A03', 'BANK-A04'}:
            intake_for_review(previous['BANK-A02'], context=step.context,
                action_input=plan.steps['BANK-A03'].action_input, objects=objects,
                evidence_ref=plan.intake_evidence_ref.model_dump(mode='json'))
        if action == 'BANK-A04':
            if plan.strategy_feedback is not None:
                from integration.bank_financing_strategy import strategy_for_quote
                strategy = previous['BANK-A01']
                strategy_for_quote(strategy,invocation=self.snapshots.get(TaskIdentity(**strategy['identity'])),
                    plan=plan,objects=objects)
            if self.monthly is not None:
                from integration.bank_monthly_native_sources import quote_from_monthly
                quote_from_monthly(self.monthly,plan,objects)
            credit = previous['BANK-A03']
            review_for_quote(credit, invocation=self.snapshots.get(TaskIdentity(**credit['identity'])),
                context=step.context, action_input=step.action_input, objects=objects,
                recorded_ref=plan.recorded_review_ref.model_dump(mode='json'), audit_ref=plan.review_audit_ref.model_dump(mode='json'))
        return objects

    def _prior_intake_declines(self, plan):
        """Read actual earlier own refusals, without inventing debt or risk facts."""
        from gba_construction_sim.backend.agents.contracts import AgentObservationV1
        from integration.project_financing_feedback import project_financing_event
        client, engine = self.assembly.client, self.assembly.engine
        if plan.tick != engine.current_tick:
            raise TaskConflict('Bank refusal history changes the current native business time')
        origins = []
        own_tasks = client.tasks.for_organization(run_id=client.run_id, organization_id=plan.organization_id)
        for entry in client.inbox.for_organization(run_id=client.run_id, organization_id=plan.organization_id):
            payload = entry['payload']
            if (payload['event_type'] != 'bank_financing_decision' or payload['tick'] >= plan.tick
                    or payload['agent_id'] != plan.organization_id
                    or payload['data'].get('owner_id') != plan.borrower_id
                    or payload['data'].get('micro_action_id') != 'BANK-A02'):
                continue
            project = engine.projects.get(payload['project_id'])
            events = [] if project is None else [e for e in project.event_log if e['event_id'] == entry['event_id']]
            if len(events) != 1:
                raise TaskConflict('Bank refusal history lost its actual original project event')
            event = events[0]
            projection = project_financing_event(AgentObservationV1.model_validate(event), client.organization_roles)
            scope = {'project_id': project.project_id, 'owner_id': project.owner_id, 'tick': event['tick']}
            records = [r for r in self._records() if r['scope'] == scope
                and r['native_request']['agent']['agent_id'] == plan.organization_id]
            if (projection.get(plan.organization_id) != payload or len(records) != 1
                    or event['data'].get('native_financing_scope') != scope or project.owner_id != plan.borrower_id):
                raise TaskConflict('Bank refusal history changes its own recipient or original financing scope')
            record = records[0]
            original_key = self.PREFIX + task_digest([client.simulation_id, plan.organization_id,
                record['native_request']['request_id'], scope])
            old_plans = [p for p in self.plans if (p.organization_id, p.borrower_id, p.project_id, p.tick)
                == (plan.organization_id, plan.borrower_id, project.project_id, event['tick'])]
            expected_actions = {'BANK-A02'} | ({'BANK-A01'} if old_plans and old_plans[0].strategy_feedback else set())
            if (len(old_plans) != 1 or record['state'] != 'formed' or record.get('terminal_action') != 'BANK-A02'
                    or record['source_file_sha256'] != self.settings.file_sha256
                    or record['key'] != original_key
                    or record['native_request']['agent']['role'] != 'Bank'
                    or record['native_request']['operation'] != 'consider_financing'
                    or set(record['steps']) != expected_actions):
                raise TaskConflict('Bank refusal history requires its original completed intake pipeline')
            for action, origin in record['steps'].items():
                identity = TaskIdentity(**origin['identity'])
                saved = checked_result(self.workers[action], identity)
                old_step = old_plans[0].steps[action]
                snapshot = self.snapshots.get(identity)
                current_context = old_step.context.model_copy(update={'business_time': plan.steps['BANK-A02'].context.business_time})
                grants = self.organizations.grants(current_context, action, 'Bank')
                permitted = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in current_context.visible_refs}
                if (identity.organization_id != plan.organization_id or identity.run_id != client.run_id
                        or identity.action_id != action or identity.purpose != 'action'
                        or identity.request_id != record['key'] + ':' + action
                        or snapshot['context'] != old_step.context.model_dump(mode='json')
                        or any(origin.get(k) != saved[k] for k in ('result_sha256', 'record_sha256', 'source_reading_sha256'))
                        or any(Reference.model_validate(r['ref']).key() not in permitted for r in saved['source_reading'])):
                    raise TaskConflict('Bank refusal history lost its original action or current reading authority')
            identity = TaskIdentity(**record['steps']['BANK-A02']['identity'])
            saved = checked_result(self.workers['BANK-A02'], identity)
            proposals = [t for t in own_tasks if t['identity']['purpose'] == 'propose'
                and t['identity']['action_id'] == 'consider_financing' and t['state'] == 'output_formed'
                and t['output'].get('factors', {}).get('native_financing_scope') == scope]
            finals = [t for t in own_tasks if t['identity']['purpose'] == 'decide'
                and t['identity']['action_id'] == 'bank_project_financing' and t['state'] == 'output_formed'
                and t['output'].get('data', {}).get('native_financing_scope') == scope]
            if len(proposals) != 1 or len(finals) != 1:
                raise TaskConflict('Bank refusal history lost its actual original native proposal and confirmation')
            proposal, final = proposals[0]['output'], finals[0]['output']
            fields = {'micro_action_id': 'BANK-A02', 'micro_task_key': identity.key,
                'micro_result_sha256': saved['result_sha256']}
            if (saved['result']['payload']['choice'] != 'decline'
                    or saved['result']['payload']['application_ref'] != old_plans[0].steps['BANK-A02'].action_input['application_ref']
                    or proposal['accepted'] is not False or final['decision'] is not False
                    or event['data'].get('accepted') is not False
                    or any(v.get('action_type') != 'reject_financing' for v in (proposal, final, event['data']))
                    or task_digest(proposal) != record['proposal_response_sha256']
                    or final['data'].get('proposal_response_sha256') != record['proposal_response_sha256']
                    or event['data'].get('proposal_response_sha256') != record['proposal_response_sha256']
                    or proposal['data'] != record['native_summary']['data']
                    or record['native_summary']['accepted'] is not False
                    or record['native_summary']['data'] != {'approved_amount': 0.0, 'interest_rate': 0.0,
                        'conditions': [], 'requested_amount': record['native_request']['inputs']['requested_amount']}
                    or any(container.get(k) != v for container in (final['data'], event['data'])
                        for k, v in record['native_summary']['data'].items())
                    or any(container.get(k) != v for container in (proposal['factors'], final['data'], event['data'])
                        for k, v in fields.items())):
                raise TaskConflict('Bank refusal history substitutes a refusal, quotation or unexecuted decision')
            origins.append({'event_id': entry['event_id'], 'project_id': project.project_id, 'tick': event['tick'],
                'recipient_organization_id': plan.organization_id, 'borrower_id': plan.borrower_id,
                'proposal_response_sha256': record['proposal_response_sha256'], 'result_sha256': saved['result_sha256'],
                'record_sha256': saved['record_sha256'], 'source_reading_sha256': saved['source_reading_sha256'],
                'micro_task_key': identity.key, 'choice': 'decline'})
        if len({r['event_id'] for r in origins}) != len(origins):
            raise TaskConflict('Bank refusal history repeats one actual native event')
        return sorted(origins, key=lambda r: (r['tick'], r['project_id'], r['event_id']))

    def project(self, *, context, organization_id, grants):
        bound = self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or bound[0].organization_id != organization_id:
            raise TaskConflict('Bank source projection lost its original current native invocation')
        plan, request, action, previous = bound
        self._current(request)
        objects = self._sources(plan, request, action, previous)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'native-bank-financing:' + task_digest(objects), 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'), 'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        bound = self._bound.get(prepared.context_sha256)
        if (bound is None or row['identity']['organization_id'] != bound[0].organization_id
                or prepared.runner.registry is not self.registry or prepared.context != bound[0].steps[bound[2]].context):
            raise TaskConflict('Bank worker changes its original invocation or authority registry')
        self._current(bound[1])
        prepared.reading.recheck()
        return True

    def validate_wait(self, row, result, conditions):
        identity = TaskIdentity(**row['identity'])
        bound = self._bound.get(identity.context_sha256)
        if bound is None or identity.action_id not in self.workers:
            raise TaskConflict('Bank pending result lost its original current source binding')
        plan, request, action, previous = bound
        self._current(request)
        worker, step = self.workers[action], plan.steps[action]
        saved = worker.get_record(identity)
        expected = {'kind': worker.WAIT_KIND, 'result_kind': result.get('kind'), 'result_sha256': task_digest(result)}
        if result.get('kind') == 'needs_information':
            expected.update(missing_fields=result['missing_fields'], requested_refs=result['requested_refs'])
        elif result.get('kind') == 'unsupported':
            expected['capability_ref'] = result['capability_ref']
        elif result.get('kind') == 'deferred':
            expected['resume_condition'] = result['resume_condition']
        else:
            raise TaskConflict('Bank wait requires an original unresolved business result')
        if (identity.organization_id != plan.organization_id or identity.action_id != action
                or saved is None or saved['result'] != result or saved['attempt_revision'] != row['revision']
                or row['state'] != 'processing' or conditions != [expected]):
            raise TaskConflict('Bank wait changes its original task or saved pending result')
        objects = self._sources(plan, request, action, previous)
        schemas = self.assemblers[action].SOURCE_SCHEMAS()
        current = {task_digest(r['ref']): schemas.validate_projection(
            Reference.model_validate(r['ref']), r['value']).model_dump(mode='json') for r in objects}
        grants = self.organizations.grants(step.context, action, 'Bank')
        readable = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in step.context.visible_refs}
        if any(Reference.model_validate(r['ref']).key() not in readable
                or current.get(task_digest(r['ref'])) != r['projection'] for r in saved['source_reading']):
            raise TaskConflict('Bank wait lost its original authorized pending sources')
        return True

    def validate_recovery(self, row, saved, snapshot):
        return validate_saved_financing_stage(self, row, saved, snapshot)

    def recover_saved_proposal(self, request):
        return recover_saved_financing_proposal(self, request)

    def query_native_outcome(self, identity, *, organization_id, tick):
        return query_bank_financing_outcome(self, identity, organization_id=organization_id, tick=tick)

    def _terminal(self, plan, request, record, *, saved_results=None):
        """Recheck the exact executed prefix, including a genuine A02 rejection.

        A completed intake decline is a financing refusal, not a quotation.
        Missing information and technical failures never enter this path.
        """
        actions = [action for action in COMPONENTS if action in plan.steps]
        terminal = record['terminal_action']
        if terminal not in {'BANK-A02', 'BANK-A04'}:
            raise TaskConflict('Bank financing has no supported original terminal decision')
        actions = actions[:actions.index(terminal) + 1]
        if set(record['steps']) != set(actions):
            raise TaskConflict('Bank financing substitutes its exact executed action prefix')
        previous = {}
        for action in actions:
            step, origin = plan.steps[action], record['steps'][action]
            identity = TaskIdentity(**origin['identity'])
            saved = checked_result(self.workers[action], identity) if saved_results is None else saved_results[action]
            snapshot = self.snapshots.get(identity)
            if (identity.run_id != step.context.run_id or identity.organization_id != plan.organization_id
                    or identity.action_id != action or identity.purpose != 'action'
                    or identity.request_id != record['key'] + ':' + action
                    or snapshot['context'] != step.context.model_dump(mode='json')
                    or any(snapshot['action_input'].get(k) != v for k, v in step.action_input.items())
                    or any(origin.get(field) != saved[field] for field in
                        ('result_sha256', 'record_sha256', 'source_reading_sha256'))):
                raise TaskConflict('Bank financing changes its original saved action or invocation')
            objects = self._sources(plan, request, action, previous)
            schemas = self.assemblers[action].SOURCE_SCHEMAS()
            current = {task_digest(row['ref']): schemas.validate_projection(
                Reference.model_validate(row['ref']), row['value']).model_dump(mode='json') for row in objects}
            grants = self.organizations.grants(step.context, action, 'Bank')
            permitted = {ref.key() for grant in grants for ref in grant.readable_refs} & {
                ref.key() for ref in step.context.visible_refs}
            if any(Reference.model_validate(row['ref']).key() not in permitted
                    or current.get(task_digest(row['ref'])) != row['projection'] for row in saved['source_reading']):
                raise TaskConflict('Bank financing lost current permission or changed its original consumed sources')
            previous[action] = saved
        intake = previous['BANK-A02']['result']['payload']
        if record['intake_feedback'] != self._prior_intake_declines(plan):
            raise TaskConflict('Bank financing changes its original consumed refusal feedback')
        if terminal == 'BANK-A02':
            if intake['choice'] != 'decline' or intake['application_ref'] != plan.steps['BANK-A02'].action_input['application_ref']:
                raise TaskConflict('Only the original completed intake decline can end financing before credit review')
            accepted, data = False, {'approved_amount': 0.0, 'interest_rate': 0.0, 'conditions': []}
        else:
            if intake['choice'] != 'accept_for_review':
                raise TaskConflict('Bank financing cannot quote without its original accepted intake')
            accepted, data = native_quote_summary(previous[terminal], objects, periods_per_year=plan.periods_per_year)
        data['requested_amount'] = request.inputs['requested_amount']
        return terminal, previous[terminal], objects, accepted, data

    def propose(self, request):
        with self.read_guard():
            plan, scope = self._current(request)
            key = self._key(request)
            if any(r['key'] == key for r in self._records()):
                raise TaskConflict('Bank request is already claimed; reuse original transport or diagnose unresolved work')
            record = self._save(key, {'key': key, 'state': 'preparing', 'native_request': request.model_dump(mode='json'),
                'scope': scope, 'source_file_sha256': self.settings.file_sha256, 'steps': {}})
            previous = {}
            for action in COMPONENTS:
                if action not in plan.steps:
                    continue
                step = plan.steps[action]
                if action == 'BANK-A02':
                    record['intake_feedback'] = self._prior_intake_declines(plan)
                self._bound[task_digest(step.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True), action, dict(previous))
                prepared = self.assemblers[action].build(step.context, **deepcopy(step.action_input))
                identity = self.workers[action].register(prepared, request_id=key + ':' + action)
                record['steps'][action] = {'identity': identity.as_dict()}
                record = self._save(key, record)
                execute_original_stage(worker=self.workers[action], identity=identity, prepared=prepared,
                    enabled=self.settings.continue_unstarted_actions_on_error, record=record, stage=action,
                    save_record=lambda value: self._save(key, value))
                previous[action] = checked_result(self.workers[action], identity)
                record['steps'][action] = {'identity': identity.as_dict(), **{
                    field: previous[action][field] for field in
                    ('result_sha256', 'record_sha256', 'source_reading_sha256')}}
                if action == 'BANK-A01':
                    from integration.bank_financing_strategy import selection_feedback
                    record['strategy_feedback'] = selection_feedback(self,plan,request,deepcopy(step.objects))
                record = self._save(key, record)
                if action == 'BANK-A01' and previous[action]['result']['payload']['choice'] not in {'retain_strategy', 'revise_strategy'}:
                    raise TaskConflict('Unresolved lending strategy cannot become financing approval or rejection')
                if action == 'BANK-A02':
                    choice = previous[action]['result']['payload']['choice']
                    if choice == 'decline':
                        break
                    if choice != 'accept_for_review':
                        raise TaskConflict('Unresolved intake cannot become financing approval or rejection')
            record['terminal_action'] = action
            terminal, saved, objects, accepted, data = self._terminal(plan, request, record)
            response = self._proposal_response(request, plan, scope, record, terminal, saved, accepted, data, prepared.reading)
            record.update(state='formed', native_summary={'accepted': accepted, 'data': data},
                source_sha256=task_digest(objects), proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self._save(key, record)
            return response

    def _proposal_response(self, request, plan, scope, record, terminal, saved, accepted, data, reading):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        for metric in (plan.utility, plan.probability):
            if not isinstance(reading.resolve(metric.basis_ref), EvidenceRecord):
                raise TaskConflict('Bank native indicators lack their exact authorized evidence source')
        if (plan.utility.unit != 'score' or plan.probability.unit != 'probability'
                or not 0 <= float(plan.utility.value) <= 1 or not 0 <= float(plan.probability.value) <= 1):
            raise TaskConflict('Bank native indicators require explicit sourced bounded units')
        return AgentProposalResponseV1(request_id=request.request_id,
            action_type='approve_financing' if accepted else 'reject_financing', accepted=accepted,
            utility=float(plan.utility.value), probability=float(plan.probability.value),
            reason=saved['result']['payload']['note'], data=data,
            factors={'micro_action_id': terminal, 'micro_result_sha256': saved['result_sha256'],
                'micro_task_key': TaskIdentity(**saved['identity']).key,
                'micro_pipeline': record['steps'], 'native_financing_scope': scope})

    def decide(self, request):
        if self.monthly is not None and (request.agent.role,request.decision_type)==('Bank','monthly_enterprise_operation'):
            return self.monthly.decide(request)
        if self.owner is not None and (request.agent.role,request.decision_type)==('Owner','owner_financing_selection'):
            return self.owner.decide(request)
        if (request.agent.role, request.decision_type) != ('Bank', 'bank_project_financing'):
            return self._other_decision(request)
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1, AgentProposalRequestV1
        with self.read_guard():
            self._check()
            scope = financing_scope(self.assembly, request, purpose='decide')
            record, = [r for r in self._records() if r['scope'] == scope and r['state'] == 'formed'
                and r['native_request']['agent']['agent_id'] == request.agent.agent_id]
            original = AgentProposalRequestV1.model_validate(record['native_request'])
            plan, _ = self._current(original)
            terminal, saved, objects, accepted, data = self._terminal(plan, original, record)
            factors = request.decision_support.get('decision_factors', {})
            action = 'approve_financing' if accepted else 'reject_financing'
            proposals = [t for t in self.assembly.client.tasks.for_organization(
                run_id=self.assembly.client.run_id, organization_id=plan.organization_id)
                if t['identity']['action_id'] == 'consider_financing' and t['identity']['purpose'] == 'propose'
                and t['state'] == 'output_formed' and t['output'].get('factors', {}).get('native_financing_scope') == scope]
            if len(proposals) != 1:
                raise TaskConflict('Bank final confirmation requires its one original formed native proposal')
            proposal = proposals[0]['output']
            support = request.decision_support
            if (task_digest(objects) != record['source_sha256'] or {'accepted': accepted, 'data': data} != record['native_summary']
                    or task_digest(proposal) != record['proposal_response_sha256']
                    or support.get('decision_factors') != proposal['factors']
                    or support.get('action_type') != proposal['action_type'] or support.get('accepted') != proposal['accepted']
                    or any(task_digest(support.get(k)) != task_digest(v) for k,v in proposal['data'].items())
                    or factors.get('micro_pipeline') != record['steps']
                    or factors.get('micro_action_id') != terminal
                    or factors.get('micro_result_sha256') != saved['result_sha256']
                    or factors.get('micro_task_key') != TaskIdentity(**saved['identity']).key
                    or action not in request.constraints.allowed_actions):
                raise TaskConflict('Bank final confirmation changes its exact original micro pipeline or current sources')
            return AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
                action_type=action, decision=accepted, reason=saved['result']['payload']['note'],
                data={**data, 'micro_action_id': terminal, 'micro_result_sha256': saved['result_sha256'],
                    'micro_task_key': TaskIdentity(**saved['identity']).key, 'native_financing_scope': scope,
                    'proposal_response_sha256': record['proposal_response_sha256']})

    def evidence(self):
        with self.read_guard():
            self._check()
            return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256,
                'requests': self._records(), 'authority': self.authority.evidence(),
                'owner': self.owner.evidence() if self.owner is not None else None,
                'arrangement': self.arrangement.evidence() if self.arrangement is not None else None,
                'monthly_strategy': self.monthly.evidence() if self.monthly is not None else None,
                'native_routes': self.assembly.client.native_routes.evidence(),
                'native_outcome_queries': {'bank': 'bank.query_native_outcome(original_terminal_identity, organization_id=own_id, tick=current_tick)',
                    'owner': 'bank.owner.query_native_outcome(original_identity, organization_id=own_id, tick=current_tick)',
                    'limits': 'Read-only original native decision/selection outcomes. Absence remains unknown; no replay, formal loan, drawdown or cash execution.'},
                'limits': 'Completed A02 decline ends original financing; accepted intake continues through private A03 to A04. '
                    'Unresolved intake is not a rejection. No loan/cash ledger.'}


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True:
        raise ValueError('This explicit bank development composition requires offline mode')
    assembly.client.native_routes.attach(assembly)
    app = BankFinancingApplication(assembly=assembly, settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION, evidence=app.evidence,
        close=app.authority.close, writer_guard=app.read_guard)
