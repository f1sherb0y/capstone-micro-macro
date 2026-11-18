"""Compose original Architect/Engineer/QS A02 workers with native appointments."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from integration.architect_intake_actions import ArchitectIntakeActionAssembler
from integration.architect_intake_results import ArchitectIntakeResultWorker
from integration.engineer_intake_actions import EngineerIntakeActionAssembler
from integration.engineer_intake_results import EngineerIntakeResultWorker
from integration.qs_intake_actions import QSIntakeActionAssembler
from integration.qs_intake_results import QSIntakeResultWorker
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings, build_authority_runtime
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, module_client_implementation
from integration.professional_intake_feedback import prior_appointments, recorded_appointment_feedback
from integration.professional_intake_scope import professional_scope
from integration.professional_opportunity_native import ProfessionalOpportunityPlan, ProfessionalOpportunityStep
from integration.owner_commission_native import OwnerCommissionApplication,OwnerCommissionSettings
from integration.professional_appointment_native import ProfessionalAppointmentApplication, ProfessionalAppointmentSettings
from integration.native_lifecycle_actions import NativeLifecycleApplication, NativeLifecycleSettings
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, StrictRecord, TextId, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest

COMPONENTS = {
    'Architect': (ArchitectIntakeActionAssembler, ArchitectIntakeResultWorker, 'accept_design_appointment', 'decline_design_appointment', 'accepted_terms_ref'),
    'Engineer': (EngineerIntakeActionAssembler, EngineerIntakeResultWorker, 'accept_engineering_appointment', 'decline_engineering_appointment', 'terms_ref'),
    'QS': (QSIntakeActionAssembler, QSIntakeResultWorker, 'accept_qs_appointment', 'decline_qs_appointment', 'terms_ref'),
}


class ProfessionalIntakePlan(StrictRecord):
    organization_id: TextId
    role: Literal['Architect', 'Engineer', 'QS']
    project_id: TextId
    tick: int = Field(ge=0)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    # Explicit organization policy about historical actual appointments. It is
    # not a reconstruction of physical capacity from native normalized scalars.
    max_prior_appointments: int | None = Field(default=None, ge=1)
    private_intake_judgment_policy: Literal['ignore', 'pause_after_actual_selection_recommendation'] = 'ignore'
    unresolved_appointment_policy: Literal['require_resolution','decline_new_work']='require_resolution'
    utility: Measured
    probability: Measured
    opportunity: ProfessionalOpportunityPlan | None = None

    @model_validator(mode='after')
    def original_context(self):
        if (self.context.contract_ref.id != self.role.upper() + '-A02' or self.context.scope.kind != 'project'
                or self.context.scope.ref.id != self.project_id or self.context.business_time.offset != self.tick
                or self.context.execution_mode == 'offline_fixture'):
            raise ValueError('Professional intake requires its original formal action, project and current time')
        if len({task_digest(o['ref']) for o in self.objects}) != len(self.objects):
            raise ValueError('Professional intake repeats an original source identity')
        if self.opportunity is not None:
            previous = self.opportunity.context
            if (any(getattr(previous,field)!=getattr(self.context,field) for field in
                    ('run_id','actor_id','function_ref','scope','business_time','execution_mode'))
                    or previous.contract_ref.id!=self.role.upper()+'-A01'
                    or previous.read_token==self.context.read_token or previous.operation_id==self.context.operation_id):
                raise ValueError('Professional opportunity needs its own original same-organization scope and read point')
        return self


class ProfessionalIntakeSettings(StrictRecord):
    version: TextId
    policy_version: TextId
    authority: TenderAuthorityRuntimeSettings
    file_path: TextId
    file_sha256: Digest
    owner_final_source: Literal['original_native_appointment_proposal','original_micro_owner_commission_proposal']
    owner: OwnerCommissionSettings | None=None
    appointment: ProfessionalAppointmentSettings | None = None
    feedback: NativeLifecycleSettings | None = None


class ProfessionalIntakeApplication:
    VERSION = 'gba-v1-professional-intake.v10'
    PREFIX = 'professional_intake_native_request:'

    def __init__(self, *, assembly, settings, authority=None, install=True):
        self.assembly = assembly
        self.settings = ProfessionalIntakeSettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        document = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(document) != {'schema_version', 'run_id', 'plans'}
                or document['schema_version'] != 'professional-intake-input.v1'
                or document['run_id'] != assembly.client.run_id):
            raise TaskConflict('Professional sources change their declared schema or run')
        self.plans = [ProfessionalIntakePlan.model_validate(p) for p in document['plans']]
        if any(p.private_intake_judgment_policy != 'ignore' for p in self.plans) and self.settings.feedback is None:
            raise TaskConflict('Private intake recommendation consumption requires its declared own feedback application')
        if any(p.unresolved_appointment_policy!='require_resolution' for p in self.plans) and self.settings.appointment is None:
            raise TaskConflict('Unresolved appointment policy requires the original A03 reception and history source')
        self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans])
        keys = [(p.organization_id, p.project_id, p.tick) for p in self.plans]
        contexts = [context for plan in self.plans for context in
            ([plan.context,plan.opportunity.context] if plan.opportunity is not None else [plan.context])]
        if (not keys or len(set(keys)) != len(keys) or len({c.read_token for c in contexts}) != len(contexts)
                or {p.role for p in self.plans} != set(COMPONENTS)):
            raise TaskConflict('Professional composition needs distinct plans/tokens for all three original roles')
        self._owns_authority = authority is None
        self.authority = authority or build_authority_runtime(assembly=assembly, settings=self.settings.authority)
        if self.authority.assembly is not assembly or self.authority.settings != self.settings.authority:
            raise TaskConflict('Professional shared authority must match its exact declared assembly and snapshot')
        self.registry, self.organizations = self.authority.registry, self.authority.organizations
        self.read_guard = self.authority.read_guard
        self.snapshots=InvocationSnapshotStore(assembly.client.tasks)
        self._bound = {}
        self.assemblers, self.workers = {}, {}
        self._other_decision = assembly.client.decision_handler
        self._native_settings = task_digest(assembly.client.native_routes.settings.model_dump(mode='json'))
        self._client_implementation = None
        self.owner=None
        self.appointment = None
        self.opportunity = None
        self.feedback = None
        try:
            if not assembly.client.native_routes.settings.micro_professional_intake_scope:
                raise TaskConflict('Professional intake requires its explicit exclusive micro routing declaration')
            enabled=self.settings.owner is not None
            if (assembly.client.native_routes.settings.micro_owner_commission_scope!=enabled
                    or self.settings.owner_final_source!=('original_micro_owner_commission_proposal' if enabled
                        else 'original_native_appointment_proposal')):
                raise TaskConflict('Owner commission requires its exclusive explicit micro routes and declared result source')
            for role, (assembler, worker, *_rest) in COMPONENTS.items():
                self.assemblers[role] = assembler(registry=self.registry, organizations=self.organizations,
                    provider=self, macro_version='gba-public-2026-08-21', source_mode='formal',
                    policy_version=self.settings.policy_version, model_version=assembly.client.versions['model'])
                self.workers[role] = worker(store=assembly.client.tasks, snapshots=self.snapshots,
                    registry=self.registry, client_version=self.VERSION + ':' + role,
                    model_version=assembly.client.versions['model'], validate_invocation=self.validate_invocation,
                    validate_wait=self.validate_wait)
            if any(p.opportunity is not None for p in self.plans):
                self.opportunity = ProfessionalOpportunityStep(self)
            if enabled:self.owner=OwnerCommissionApplication(professional=self,settings=self.settings.owner)
            if self.settings.appointment is not None:
                if not enabled or assembly.client.continuation_dispatcher is not None:
                    raise TaskConflict('Professional appointment reception requires the declared owner handoff and exclusive initial dispatcher')
                self.appointment = ProfessionalAppointmentApplication(professional=self, settings=self.settings.appointment)
            if self.settings.feedback is not None:
                self.feedback = NativeLifecycleApplication(assembly=assembly, authority=self.authority,
                    settings=self.settings.feedback)
                expected = {(p.organization_id, p.project_id, p.tick): p.role for p in self.plans}
                selectors = [(p.organization_id, p.project_id, p.tick, p.event_type) for p in self.feedback.plans]
                if (len(set(selectors)) != len(selectors) or any(
                        p.event_type not in {'appointment_decision', 'consultant_team_appointed'} or p.appointment_feedback_ref is None
                        or p.context.contract_ref.id != expected.get(key[:3], '').upper() + '-A12'
                        for p, key in zip(self.feedback.plans, selectors))):
                    raise TaskConflict('Professional feedback requires one private A12 recording for its exact original intake')
            self._feedback_component = self.feedback
            if self.feedback is not None:
                for plan in self.plans:
                    selected = [p for p in self.feedback.plans if (p.organization_id, p.project_id, p.tick, p.event_type)
                        == (plan.organization_id, plan.project_id, plan.tick, 'consultant_team_appointed')]
                    if plan.private_intake_judgment_policy != 'ignore' and (
                            len(selected) != 1 or selected[0].private_intake_judgment is None):
                        raise TaskConflict('Private intake policy requires its exact declared simulation-only own assessment')
            if install:
                self.install()
        except Exception:
            if self.feedback is not None:
                self.feedback.close()
            if self._owns_authority:
                self.authority.close()
            raise

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Professional inputs differ from their pinned independent file')

    def _check(self):
        self.assembly._validate_components()
        self._check_file()
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha
                or self._client_implementation is None
                or module_client_implementation(self.assembly.client) != self._client_implementation
                or task_digest(self.assembly.client.native_routes.settings.model_dump(mode='json')) != self._native_settings):
            raise TaskConflict('Professional composition changed its original handlers or native routing declarations')
        for role in COMPONENTS:
            if (self.workers[role].store is not self.assembly.client.tasks or self.workers[role].registry is not self.registry
                    or self.assemblers[role].organizations is not self.organizations):
                raise TaskConflict('Professional action substituted its original registry, authority or shared journal')
        if self.owner is not None:self.owner.check_components()
        if self.appointment is not None:self.appointment.check_components()
        if self.opportunity is not None:self.opportunity.check()
        if ((self.feedback is None) != (self.settings.feedback is None)
                or self.feedback is not self._feedback_component
                or self.feedback is not None and (self.feedback.authority is not self.authority
                    or self.feedback.assembly is not self.assembly or self.feedback.settings != self.settings.feedback)):
            raise TaskConflict('Professional feedback lost its explicitly declared original event application')
        if self.feedback is not None:self.feedback.check()

    def install(self):
        client = self.assembly.client
        with client._lock:
            if (not client.native_routes.settings.micro_professional_intake_scope or client._calls or client._request_hashes
                    or client._tender_feedback is not None or client.decision_handler is not self._other_decision
                    or client.binding_installation_blocked()):
                raise TaskConflict('Professional routes must be explicitly installed before native requests or recovered tasks')
            for role in COMPONENTS:
                client.bind_proposal_handler(role=role, operation='consider_appointment', handler=self.propose,
                    client_version=self.VERSION + ':' + role)
            if self.owner is not None:
                client.bind_proposal_handler(role='Owner',operation='select_appointment',handler=self.owner.propose,
                    client_version=self.VERSION+':Owner')
            client.decision_handler = self.decide
            if self.appointment is not None:
                client.continuation_dispatcher = self.appointment.dispatch
            self.seal_client_binding()

    def proposal_bindings(self):
        result = {(role, 'consider_appointment'): self.propose for role in COMPONENTS}
        if self.owner is not None:
            result[('Owner', 'select_appointment')] = self.owner.propose
        return result

    def seal_client_binding(self):
        client = self.assembly.client
        with client._lock:
            if (self._client_implementation is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or any(client.proposal_handlers.get(key) != handler for key, handler in self.proposal_bindings().items())):
                raise TaskConflict('Professional client binding must be sealed once before any requests, preserving every original owned handler')
            self._client_implementation = module_client_implementation(client)

    def _current(self, request):
        self._check()
        scope = professional_scope(self.assembly, request, purpose='propose')
        if request.agent.role not in COMPONENTS or request.operation != 'consider_appointment':
            raise TaskConflict('Professional micro route requires its original service-intake operation')
        matches = [p for p in self.plans if (p.organization_id, p.project_id, p.tick) ==
                   (request.agent.agent_id, scope['project_id'], scope['tick'])]
        if len(matches) != 1 or matches[0].role != request.agent.role:
            raise TaskConflict('Professional current native request has no exact independent plan')
        plan = matches[0]
        if plan.context.run_id != self.assembly.client.run_id:
            raise TaskConflict('Professional plan changes its actual original run')
        grants = self.organizations.grants(plan.context, plan.role.upper() + '-A02', plan.role)
        if not grants or grants[0].organization_id != plan.organization_id:
            raise TaskConflict('Professional intake lacks current original provider authority')
        project = self.assembly.engine.projects[plan.project_id]
        terms,=[row['value'] for row in plan.objects if row['ref']==plan.action_input['terms_ref']]
        if (terms['region_id']!={'state':'known','value':project.region}
                or terms['object_type']!={'state':'known','value':project.project_type}):
            raise TaskConflict('Professional independent terms must match the actual native project region and object type')
        rows = [r['value'] for r in plan.objects if r['ref'] == plan.action_input['request_ref']]
        if (len(rows) != 1 or rows[0]['provider_organization_id'] != plan.organization_id
                or rows[0]['provider_id'] != plan.context.actor_id
                or rows[0]['client_organization_id'] != project.owner_id
                or rows[0]['payer_organization_id'] != project.owner_id):
            raise TaskConflict('Professional private service request changes actual project Owner or provider')
        return plan, scope

    def _sources(self, plan, request):
        objects = deepcopy(plan.objects)
        originals = prior_appointments(self.assembly, organization_id=plan.organization_id, tick=plan.tick)
        if self.feedback is not None:
            originals = recorded_appointment_feedback(self.feedback, organization_id=plan.organization_id,
                appointments=originals)
        observed = {'request_sha256': task_digest(request.model_dump(mode='json')), 'prior_appointments': originals,
                    'max_prior_appointments': plan.max_prior_appointments}
        pause_for_judgment = False
        if plan.private_intake_judgment_policy != 'ignore':
            observed['private_intake_judgment_policy'] = plan.private_intake_judgment_policy
            recommendations = [p['private_feedback']['intake_recommendation'] for p in originals
                if p.get('private_feedback', {}).get('intake_recommendation') is not None]
            observed['prior_private_intake_recommendations'] = deepcopy(recommendations)
            pause_for_judgment = any(p['choice'] == 'pause_new_intake' for p in recommendations)
        decline_no_interest = False
        if self.appointment is not None:
            observed['prior_confirmations'] = self.appointment.prior_confirmations(
                organization_id=plan.organization_id, tick=plan.tick, appointments=originals,
                include_unresolved=plan.unresolved_appointment_policy=='decline_new_work')
        pending=[r for r in observed.get('prior_confirmations',[]) if r['choice']!='confirm']
        if plan.unresolved_appointment_policy!='require_resolution':
            observed['unresolved_appointment_policy']=plan.unresolved_appointment_policy
            observed['unresolved_appointments']=pending
        if plan.opportunity is not None:
            handoff = self.opportunity.handoff(plan, request)
            observed['opportunity_handoff'] = handoff
            decline_no_interest = handoff.get('non_interest_policy') == 'decline_new_work'
            reference = plan.opportunity.handoff_evidence_ref.model_dump(mode='json')
            rows = [row['value'] for row in objects if row['ref']==reference]
            service, = [row['value'] for row in objects if row['ref']==plan.action_input['request_ref']]
            if len(rows)!=1 or rows[0].get('content_hash') is not None or reference not in service['evidence_refs']:
                raise TaskConflict('Professional A02 needs its declared unbound original interest evidence dependency')
            rows[0]['content_hash'] = task_digest(handoff)
            evidence = EvidenceRecord.model_validate(rows[0])
            if evidence.source_kind!='synthetic' or evidence.basis_kind!='observed':
                raise TaskConflict('Professional private interest evidence changed its original provenance')
        rows = [row for row in objects if row['ref'] == plan.native_evidence_ref.model_dump(mode='json')]
        if len(rows) != 1 or rows[0]['value'].get('content_hash') is not None:
            raise TaskConflict('Professional observed evidence needs exactly one declared unbound native placeholder')
        rows[0]['value']['content_hash'] = task_digest(observed)
        evidence = EvidenceRecord.model_validate(rows[0]['value'])
        if evidence.source_kind != 'synthetic' or evidence.basis_kind != 'observed':
            raise TaskConflict('Professional actual simulator evidence cannot become a real-world source')
        if ((plan.max_prior_appointments is not None and len(originals) >= plan.max_prior_appointments)
                or pending and plan.unresolved_appointment_policy=='decline_new_work'
                or decline_no_interest or pause_for_judgment):
            pricing = [row['value'] for row in objects if row['ref']['kind'] == 'FeeBasis']
            if len(pricing) != 1 or pricing[0]['new_work_policy'] != {'state': 'known', 'value': 'evaluate'}:
                raise TaskConflict('Professional feedback policy needs its explicit original evaluate baseline')
            pricing[0]['new_work_policy'] = {'state': 'known', 'value': 'decline'}
            if plan.native_evidence_ref.model_dump(mode='json') not in pricing[0]['evidence_refs']:
                raise TaskConflict('Professional feedback policy lacks its actual observation evidence dependency')
        return objects, observed

    def project(self, *, context, organization_id, grants):
        bound = self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or bound[0].organization_id != organization_id:
            raise TaskConflict('Professional projection lacks its original currently bound native request')
        plan, request = bound
        self._current(request)
        objects, observed = (self.opportunity.sources(plan, request)
            if plan.opportunity is not None and context==plan.opportunity.context else self._sources(plan, request))
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'native-professional-intake:' + task_digest(observed), 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'), 'organization_id': organization_id, 'objects': objects}

    def _key(self, request):
        scope = professional_scope(self.assembly, request, purpose='propose')
        return self.PREFIX + task_digest([self.assembly.client.simulation_id, request.agent.agent_id, request.request_id, scope])

    def _save(self, request, value):
        value = deepcopy(value)
        value['record_sha256'] = task_digest({k: v for k, v in value.items() if k != 'record_sha256'})
        with self.assembly.client.tasks._transaction():
            self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                (self._key(request), canonical(value)))
        return value

    def _record(self, request):
        with self.assembly.client.tasks._lock:
            raw = self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?', (self._key(request),)).fetchone()
        if raw is None:
            return None
        record = json.loads(raw[0])
        if (record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                or record['request_sha256'] != task_digest(request.model_dump(mode='json'))
                or record['source_file_sha256'] != self.settings.file_sha256):
            raise TaskConflict('Professional result changed its original request, source file or durable record')
        return record

    def validate_invocation(self, row, prepared):
        bound = self._bound.get(prepared.context_sha256)
        if bound is None:
            raise TaskConflict('Professional worker lost its actual native invocation')
        plan, request = bound
        self._current(request)
        expected = (plan.opportunity.context if plan.opportunity is not None
            and prepared.ACTION_ID==plan.role.upper()+'-A01' else plan.context)
        if (prepared.context != expected or row['identity']['organization_id'] != plan.organization_id
                or prepared.runner.registry is not self.registry):
            raise TaskConflict('Professional worker substitutes its original action, organization or processor')
        prepared.reading.recheck()
        return True

    def validate_wait(self, *args, **kwargs):
        raise TaskConflict('Unresolved professional intake requires source diagnosis before explicit continuation')

    def _selected(self, plan, result):
        if result['kind'] != 'completed' or result['payload']['choice'] not in {'accept', 'decline'}:
            raise TaskConflict('Clarification, counteroffer, missing inputs and failure do not become native acceptance/decline')
        accepted = result['payload']['choice'] == 'accept'
        if accepted and result['payload'].get(COMPONENTS[plan.role][4]) != plan.action_input['terms_ref']:
            raise TaskConflict('Professional acceptance changes its original offered terms version')
        return accepted, COMPONENTS[plan.role][2 if accepted else 3]

    def propose(self, request):
        from decimal import Decimal
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1

        with self.read_guard():
            plan, scope = self._current(request)
            if self._record(request) is not None:
                raise TaskConflict('Professional request was already claimed; read saved transport or diagnose unresolved work')
            record = self._save(request, {'state': 'preparing', 'native_request': request.model_dump(mode='json'),
                'request_sha256': task_digest(request.model_dump(mode='json')), 'source_file_sha256': self.settings.file_sha256})
            if plan.opportunity is not None:
                self.opportunity.execute(plan, request, record)
            objects, observed = self._sources(plan, request)
            record.update(source_sha256=task_digest(objects), observed=observed)
            self._save(request, record)
            self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True))
            prepared = self.assemblers[plan.role].build(plan.context, **deepcopy(plan.action_input))
            worker = self.workers[plan.role]
            identity = worker.register(prepared, request_id='professional-intake:' + self._key(request))
            result = worker.execute(identity, prepared)['result']
            accepted, action = self._selected(plan, result)
            record.update(state='formed', identity=identity.as_dict(), result_sha256=task_digest(result))
            self._save(request, record)

            def number(value, unit):
                if (not isinstance(prepared.reading.resolve(value.basis_ref), EvidenceRecord)
                        or value.unit != unit or not 0 <= Decimal(value.value) <= 1):
                    raise TaskConflict('Professional native indicator needs explicit original evidence and bounded units')
                return float(value.value)

            return AgentProposalResponseV1(request_id=request.request_id, action_type=action, accepted=accepted,
                utility=number(plan.utility, 'score'), probability=number(plan.probability, 'probability'),
                reason=result['payload']['note'], data={}, factors={'micro_action_id': plan.role.upper() + '-A02',
                    'micro_task_key': identity.key, 'micro_result_sha256': record['result_sha256'],
                    'native_professional_scope': scope, 'source_sha256': record['source_sha256']})

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1, AgentProposalRequestV1

        role = request.agent.role
        if role == 'Owner' and request.decision_type in {'owner_select_architect', 'owner_select_engineer', 'owner_select_qs'}:
            return self.owner.decide(request) if self.owner is not None else self._owner_decide(request)
        if role not in COMPONENTS or request.decision_type != role.lower() + '_appointment_acceptance':
            return self._other_decision(request)
        with self.read_guard():
            self._check()
            scope = professional_scope(self.assembly, request, purpose='decide')
            factors = request.decision_support.get('decision_factors', {})
            with self.assembly.client.tasks._lock:
                rows = [json.loads(raw) for raw, in self.assembly.client.tasks._db.execute(
                    'SELECT value FROM metadata WHERE key LIKE ?', (self.PREFIX + '%',))]
            matches = [row for row in rows if row.get('identity', {}).get('organization_id') == request.agent.agent_id
                and row['native_request']['inputs']['project']['project_id'] == request.project_id
                and row['observed']['request_sha256'] == row['request_sha256']
                and row.get('result_sha256') == factors.get('micro_result_sha256')]
            if len(matches) != 1:
                raise TaskConflict('Professional final decision lacks its one exact original micro result')
            original = AgentProposalRequestV1.model_validate(matches[0]['native_request'])
            plan, original_scope = self._current(original)
            record = self._record(original)
            if record['state'] != 'formed' or original_scope != scope:
                raise TaskConflict('Professional final decision changed its original current proposal scope')
            identity = TaskIdentity(**record['identity'])
            saved = self.workers[role].get_record(identity)
            task = self.assembly.client.tasks.get(identity)
            if (saved is None or saved['result_sha256'] != record['result_sha256'] or task['state'] != 'output_formed'
                    or task['output'] != saved['result'] or factors.get('micro_task_key') != identity.key):
                raise TaskConflict('Professional final decision changed its formed original worker result')
            objects, observed = self._sources(plan, original)
            if task_digest(objects) != record['source_sha256'] or observed != record['observed']:
                raise TaskConflict('Professional sources changed after their original micro decision')
            accepted, action = self._selected(plan, saved['result'])
            if action not in request.constraints.allowed_actions:
                raise TaskConflict('Professional original choice is outside its bounded native actions')
            return AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
                action_type=action, decision=accepted, reason=saved['result']['payload']['note'],
                data={'micro_action_id': plan.role.upper() + '-A02', 'micro_task_key': identity.key,
                    'micro_result_sha256': record['result_sha256'], 'native_professional_scope': scope})

    def _owner_decide(self, request):
        """Transport the original OwnerAgent selection through its bounded port.

        This source is declared at startup. The generic native rule provider
        handles initiation intent and does not return an appointment candidate;
        it is not used for these final choice transports. No new choice is made.
        """
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider

        with self.read_guard():
            self._check()
            scope = professional_scope(self.assembly, request, purpose='decide')
            proposals = [t for t in self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,
                organization_id=request.agent.agent_id) if t['identity']['purpose'] == 'propose'
                and t['identity']['action_id'] == 'select_appointment' and t['state'] == 'output_formed'
                and t['output'].get('factors', {}).get('native_professional_scope') == scope]
            if len(proposals) != 1:
                raise TaskConflict('Owner final appointment needs one original current native selection proposal')
            proposal = proposals[0]['output']
            selected = proposal['data'].get('selected_agent_id')
            support = request.decision_support
            if (proposal['factors'].get('decision_source') != 'native_macro'
                    or support.get('decision_factors') != proposal['factors']
                    or support.get('selected_agent_id') != selected or support.get('accepted') != proposal['accepted']
                    or support.get('action_type') != proposal['action_type']
                    or request.choice_contract.output_field != 'selected_agent_id' or request.choice_contract.multiple
                    or proposal['accepted'] and selected not in {option['id'] for option in request.candidate_options}
                    or proposal['action_type'] not in request.constraints.allowed_actions):
                raise TaskConflict('Owner final appointment substitutes its original native choice or bounded candidates')
            response = AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
                action_type=proposal['action_type'], decision=proposal['accepted'], reason=proposal['reason'],
                data={'selected_agent_id': selected, 'decision_source': 'native_macro',
                    'source': self.settings.owner_final_source, 'proposal_response_sha256': task_digest(proposal),
                    'native_professional_scope': scope})
            ExternalAgentDecisionProvider._validated_action(request, response)
            return response

    def evidence(self):
        with self.read_guard():
            self._check()
            with self.assembly.client.tasks._lock:
                records = [json.loads(raw) for raw, in self.assembly.client.tasks._db.execute(
                    'SELECT value FROM metadata WHERE key LIKE ?', (self.PREFIX + '%',))]
            return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256,
                'authority': self.authority.evidence(), 'requests': records,
                'native_routes': self.assembly.client.native_routes.evidence(),
                'owner_final_source': self.settings.owner_final_source,
                'owner':self.owner.evidence() if self.owner is not None else None,
                'appointment': self.appointment.evidence() if self.appointment is not None else None,
                'feedback': self.feedback.evidence() if self.feedback is not None else None,
                'limits': 'Accept/decline only. Native owns appointments/engagements; micro service fees are not charged here.'}

    def close(self):
        try:
            if self.feedback is not None:self.feedback.close()
        finally:
            if self._owns_authority:self.authority.close()


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True:
        raise ValueError('This explicit development composition requires offline mode; model integration remains separate')
    config = GbaModuleHostConfiguration.model_validate(configuration)
    assembly.client.native_routes.attach(assembly)
    application = ProfessionalIntakeApplication(assembly=assembly, settings=config.settings)
    return GbaModuleHostExtension(version=application.VERSION, evidence=application.evidence,
        close=application.close, writer_guard=application.read_guard)
