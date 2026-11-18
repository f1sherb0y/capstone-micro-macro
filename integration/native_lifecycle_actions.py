"""Run original private fulfilment actions after authenticated native events.

This application owns no formal ledger or command endpoint. Detailed inputs
remain independently supplied, authorized views. Native aggregate events never
become detailed orders, task releases, certificates or cash executions here.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import Field, model_validator

from integration.bank_financing_private import checked_result, evidence_binding
from integration.action_versions import prepared_action_execution_versions
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, ref_type
from src.actions.runner import ActionRunner
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import scope_covers
from integration.native_private_intake_judgment import (
    NativePrivateIntakeJudgment, NativePrivateIntakeJudgments, bind_outcome,
    preparation_context, validate_plan as validate_private_judgment_plan,
)


# Reuse the original role hosts' action routing, assemblers and durable workers.
ROLE_MODULES = {'Owner': 'owner', 'Bank': 'bank', 'QS': 'qs',
                'Contractor': 'contractor', 'Supplier': 'supplier', 'Architect': 'architect', 'Engineer': 'engineer'}
ACTION_RANGES = {'Owner': {6, 12, 13, 14, 15}, 'Bank': set(range(6, 12)),
                 'QS': set(range(7, 12)), 'Contractor': set(range(6, 12)),
                 'Supplier': set(range(5, 12)), 'Architect': {12}, 'Engineer': {12}}
ACTION_RANGES['QS'].add(12)
EVENT_ROLES = {
    'appointment_decision': {'Architect', 'Engineer', 'QS'},
    'consultant_team_appointed': {'Architect', 'Engineer', 'QS'},
    'supplier_selected': {'Supplier', 'Contractor'},
    'contract_awarded': {'Owner', 'Contractor'},
    'project_financing_selected': {'Owner', 'Bank'},
    'payment_requested': {'Owner', 'Contractor', 'QS'},
    'payment_delayed': {'Owner', 'Contractor', 'QS'},
    'final_account_review_started': {'Owner', 'Contractor', 'QS'},
    'final_account_settled': {'Owner', 'Contractor', 'QS'},
}
EVENT_FIELDS = {
    'appointment_decision': ('role', 'purpose', 'action_type', 'accepted'),
    'consultant_team_appointed': (),  # use the existing recipient-scoped projection
    'supplier_selected': ('supplier_id', 'contractor_id'),
    'contract_awarded': ('owner_id', 'contractor_id', 'contract_sum', 'contract_duration'),
    'project_financing_selected': ('financing_mode', 'selected_bank_id', 'requested_amount'),
    'payment_requested': ('owner_id', 'contractor_id', 'certified_progress', 'payment_amount', 'payment_status'),
    'payment_delayed': ('owner_id', 'contractor_id', 'payment_amount'),
    'final_account_review_started': ('owner_id', 'contractor_id', 'qs_id', 'contract_sum', 'actual_cost', 'claim_risk'),
    'final_account_settled': ('owner_id', 'contractor_id', 'qs_id', 'contract_sum', 'final_account_amount',
                              'cost_overrun_ratio', 'delay_days', 'claim_risk', 'dispute_risk'),
}


class NativeLifecycleSettings(StrictRecord):
    version: TextId
    policy_version: TextId
    file_path: TextId
    file_sha256: Digest


class FinalAccountDisclosure(StrictRecord):
    recipient_ids: list[TextId] = Field(min_length=1)
    fields: Literal['choice_and_note']

    @model_validator(mode='after')
    def unique_recipients(self):
        if len(set(self.recipient_ids)) != len(self.recipient_ids):
            raise ValueError('Final-account disclosure requires distinct explicitly authorized recipients')
        return self


class FinalAccountQuestionReception(StrictRecord):
    """Explicit QS policy: append received Owner communication to one question."""
    message_tick: int = Field(ge=1, strict=True)
    message_index: int | None = Field(default=None, ge=0, strict=True)
    evidence_ref: ref_type('Evidence')
    question_ref: ref_type('EvidenceTarget')
    publish_question_text: bool = Field(default=False, strict=True)
    contractor_message_tick: int | None = Field(default=None, ge=1, strict=True)
    contractor_evidence_ref: ref_type('Evidence') | None = None
    contractor_message_index: int | None = Field(default=None, ge=0, strict=True)


class FinalAccountPositionReception(StrictRecord):
    """Contractor consumes an actual Owner communication in its own A11 note."""
    message_tick: int = Field(ge=1, strict=True)
    evidence_ref: ref_type('Evidence')
    profile_ref: ref_type('HandoverProfile')


class FinalAccountOwnerReception(StrictRecord):
    """Owner handles an actually received QS question through original A06."""
    message_tick: int = Field(ge=1, strict=True)
    evidence_ref: ref_type('Evidence')
    decision_ref: ref_type('PaymentAuthorization')


class ContractorFinalAccountHistory(StrictRecord):
    """A retained own original proposal, not a formal settlement receipt."""
    plan_id: TextId
    final_account_ref: ref_type('FinalAccount')


class NativeLifecyclePlan(StrictRecord):
    plan_id: TextId
    organization_id: TextId
    project_id: TextId
    tick: int = Field(ge=1, strict=True)
    event_type: TextId
    native_contractor_id: TextId | None = None
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    depends_on: list[TextId] = Field(default_factory=list)
    dependency_evidence_ref: ref_type('Evidence') | None = None
    appointment_feedback_ref: ref_type('Feedback') | None = None
    settlement_feedback_ref: ref_type('Feedback') | None = None
    private_intake_judgment: NativePrivateIntakeJudgment | None = None
    final_account_disclosure: FinalAccountDisclosure | None = None
    final_account_question_reception: FinalAccountQuestionReception | None = None
    final_account_position_reception: FinalAccountPositionReception | None = None
    final_account_owner_reception: FinalAccountOwnerReception | None = None
    contractor_final_account_history: ContractorFinalAccountHistory | None = None

    @model_validator(mode='after')
    def original_scope(self):
        c = self.context
        if self.native_contractor_id is not None and self.event_type not in {
                'payment_requested','payment_delayed','final_account_review_started','final_account_settled'}:
            raise ValueError('Conditional Contractor sources support original payment and final-account events only')
        if ((c.execution_mode == 'offline_fixture' and self.private_intake_judgment is None) or c.scope.kind != 'project'
                or c.scope.ref.id != self.project_id or c.business_time.offset != self.tick
                or self.event_type not in EVENT_ROLES
                or len({task_digest(r['ref']) for r in self.objects}) != len(self.objects)
                or len(set(self.depends_on)) != len(self.depends_on) or self.plan_id in self.depends_on
                or bool(self.depends_on) != (self.dependency_evidence_ref is not None)):
            raise ValueError('Lifecycle plan requires its exact original scope, clock, sources and explicit dependencies')
        refs = [self.native_evidence_ref] + ([self.dependency_evidence_ref] if self.depends_on else [])
        if self.final_account_question_reception is not None:
            refs.append(self.final_account_question_reception.evidence_ref)
            if self.final_account_question_reception.contractor_evidence_ref is not None:
                refs.append(self.final_account_question_reception.contractor_evidence_ref)
        if self.final_account_position_reception is not None:
            refs.append(self.final_account_position_reception.evidence_ref)
        if self.final_account_owner_reception is not None:
            refs.append(self.final_account_owner_reception.evidence_ref)
        if len({r.key() for r in refs}) != len(refs):
            raise ValueError('Lifecycle trigger and private dependency evidence must remain separate')
        if self.contractor_final_account_history is not None and (
                c.contract_ref.id != 'CONTRACTOR-A11'
                or self.contractor_final_account_history.plan_id not in self.depends_on):
            raise ValueError('Private final-account history requires an explicit original Contractor dependency')
        for ref in refs:
            if ref not in c.visible_refs:
                raise ValueError('Lifecycle trigger/dependency evidence must be visible under the original context')
            rows = [r['value'] for r in self.objects if r['ref'] == ref.model_dump(mode='json')]
            if (len(rows) != 1 or rows[0].get('content_hash') is not None
                    or rows[0].get('basis_kind') != 'observed' or rows[0].get('source_kind') != 'synthetic'):
                raise ValueError('Lifecycle event/dependency evidence must be explicitly unbound observed sources')
        if any('core_event_id' in r['value'] for r in self.objects):
            raise ValueError('Detailed core-produced sources require a verified native reader, not an aggregate trigger')
        if self.final_account_disclosure is not None and (
                self.event_type != 'final_account_review_started'
                or c.contract_ref.id not in {'OWN-A06', 'CONTRACTOR-A11'}):
            raise ValueError('Final-account position disclosure requires the original Owner review or Contractor closeout action')
        if self.final_account_owner_reception is not None:
            reception = self.final_account_owner_reception
            decisions = [r['value'] for r in self.objects if r['ref'] == reception.decision_ref.model_dump(mode='json')]
            subjects = [r['value'] for r in self.objects if r['ref'] == c.scope.ref.model_dump(mode='json')]
            receipt = reception.evidence_ref.model_dump(mode='json')
            if (self.event_type != 'final_account_review_started' or c.contract_ref.id != 'OWN-A06'
                    or reception.message_tick > self.tick or len(decisions) != 1 or len(subjects) != 1
                    or subjects[0].get('payment_authorization_ref') != reception.decision_ref.model_dump(mode='json')
                    or decisions[0].get('choice') not in {'dispute', 'negotiate'} or not decisions[0].get('note')
                    or receipt not in decisions[0].get('evidence_refs', [])
                    or receipt not in self.action_input.get('evidence_refs', [])):
                raise ValueError('QS-question reception requires original Owner-A06 dispute/negotiation and explicit receipt Evidence')
        if self.final_account_position_reception is not None:
            reception = self.final_account_position_reception
            profiles = [r['value'] for r in self.objects if r['ref'] == reception.profile_ref.model_dump(mode='json')]
            if (self.event_type != 'final_account_review_started' or c.contract_ref.id != 'CONTRACTOR-A11'
                    or reception.message_tick > self.tick or len(profiles) != 1
                    or self.action_input.get('handover_profile_ref') != reception.profile_ref.model_dump(mode='json')
                    or profiles[0].get('choice') not in {'propose_final_account', 'respond_settlement'}
                    or not profiles[0].get('note')
                    or reception.evidence_ref.model_dump(mode='json') not in profiles[0].get('evidence_refs_received', [])
                    or reception.evidence_ref.model_dump(mode='json') not in profiles[0].get('evidence_refs', [])):
                raise ValueError('Owner-position reception requires an original Contractor-A11 settlement profile with explicit receipt Evidence')
        if self.final_account_question_reception is not None:
            reception = self.final_account_question_reception
            questions = [r['value'] for r in self.objects if r['ref'] == reception.question_ref.model_dump(mode='json')]
            profiles = [r['value'] for r in self.objects if r['ref']['kind'] == 'FinalAccountProfile']
            if (self.event_type != 'final_account_review_started' or c.contract_ref.id != 'QS-A09'
                    or reception.message_tick > self.tick or len(questions) != 1 or len(profiles) != 1
                    or profiles[0].get('choice') != 'request_evidence'
                    or profiles[0].get('question_refs') != [reception.question_ref.model_dump(mode='json')]
                    or questions[0].get('contract_ref') != self.action_input.get('contract_ref')
                    or not questions[0].get('question')
                    or reception.evidence_ref.model_dump(mode='json') not in questions[0].get('evidence_refs', [])):
                raise ValueError('Owner-position reception requires an explicit original QS-A09 evidence question and separate unbound receipt Evidence')
            if ((reception.contractor_message_tick is None) != (reception.contractor_evidence_ref is None)
                    or reception.contractor_message_index is not None and reception.contractor_message_tick is None
                    or reception.contractor_message_tick is not None and (
                        reception.contractor_message_tick > self.tick
                        or reception.contractor_evidence_ref.model_dump(mode='json') not in questions[0].get('evidence_refs', []))):
                raise ValueError('QS Contractor-position reception requires its explicit original tick and separate question receipt Evidence')
        if self.appointment_feedback_ref is not None and self.event_type not in {'appointment_decision', 'consultant_team_appointed'}:
            raise ValueError('Appointment feedback requires its original appointment event')
        if self.settlement_feedback_ref is not None and (
                self.appointment_feedback_ref is not None or self.event_type != 'final_account_settled'
                or c.contract_ref.id != 'QS-A12'):
            raise ValueError('Settlement feedback requires the original own QS A12 and actual settlement event')
        bound_feedback = self.appointment_feedback_ref or self.settlement_feedback_ref
        if self.event_type in {'appointment_decision', 'consultant_team_appointed'} or bound_feedback is not None:
            if ((self.event_type in {'appointment_decision', 'consultant_team_appointed'} and self.appointment_feedback_ref is None)
                    or c.contract_ref.id not in {'ARCHITECT-A12', 'ENGINEER-A12', 'QS-A12'}
                    or self.action_input.get('feedback_refs') != [bound_feedback.model_dump(mode='json')]
                    or self.action_input.get('learning_profile_ref') != (
                        self.private_intake_judgment.learning_profile_ref.model_dump(mode='json')
                        if self.private_intake_judgment is not None else None)
                    or any(self.action_input.get(k) for k in ('forecast_refs', 'outcome_refs', 'qualification_refs'))):
                raise ValueError('Appointment feedback requires the original private A12 record-only input')
            rows = {task_digest(r['ref']): r['value'] for r in self.objects}
            feedback = rows.get(task_digest(bound_feedback.model_dump(mode='json')), {})
            strategy = rows.get(task_digest(self.action_input.get('strategy_ref')), {})
            decision = rows.get(task_digest(strategy.get('decision_profile_ref')), {})
            if (feedback.get('event', {}).get('subject_ref') != self.native_evidence_ref.model_dump(mode='json')
                    or feedback.get('event', {}).get('subject_sha256') is not None
                    or feedback.get('event_sha256') is not None or feedback.get('event', {}).get('outcomes') != []
                    or feedback.get('event', {}).get('kind') != ('performance' if self.settlement_feedback_ref else 'market')
                    or feedback.get('recipient_organization_id') != self.organization_id
                    or feedback.get('received_at') != c.business_time.model_dump(mode='json')
                    or decision.get('choice') != ('update_judgment' if self.private_intake_judgment else 'record_feedback')
                    or decision.get('feedback_refs') != self.action_input['feedback_refs']
                    or decision.get('assessment_ref') != (self.private_intake_judgment.assessment_ref.model_dump(mode='json')
                        if self.private_intake_judgment is not None else None)
                    or any(decision.get(k) is not None for k in ('training_profile_ref',
                        'qualification_ref', 'qualification_update_basis_ref', 'forecast_ref', 'outcome_ref', 'error_result_ref'))
                    or self.private_intake_judgment is None and strategy.get('judgments') != []):
                raise ValueError('Appointment feedback must bind an unmodified actual event without inferred learning effects')
        validate_private_judgment_plan(self)
        return self


class NativeLifecycleInput(StrictRecord):
    schema_version: Literal['native-lifecycle-actions-input.v1']
    run_id: TextId
    source_declaration: Literal['independent_inputs_not_native_execution_proof']
    plans: list[NativeLifecyclePlan] = Field(min_length=1)


def _action_types(action_id, role):
    module = ROLE_MODULES.get(role)
    if module is None or not any(action_id == ('OWN' if role == 'Owner' else role.upper()) + f'-A{n:02}'
                                 for n in ACTION_RANGES[role]):
        raise TaskConflict('Lifecycle action is outside the original supported fulfilment/closeout routing')
    action_module, name = importlib.import_module('integration.' + module + '_role_contract_host')._ACTIONS[action_id]
    assembler = getattr(importlib.import_module(f'integration.{module}_{action_module}_actions'),
                        role + name + 'ActionAssembler')
    worker = getattr(importlib.import_module(f'integration.{module}_{action_module}_results'),
                     role + name + 'ResultWorker')
    return assembler, worker


class NativeLifecycleApplication:
    VERSION = 'gba-v1-native-lifecycle-actions.v15'
    PREFIX = 'native_lifecycle_action:'

    def __init__(self, *, assembly, authority, settings, model_host=None):
        self.assembly, self.authority = assembly, authority
        self.settings = NativeLifecycleSettings.model_validate(settings).model_copy(deep=True)
        self.model_host = model_host
        raw = Path(self.settings.file_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Lifecycle source file differs from its sealed independent input')
        doc = NativeLifecycleInput.model_validate_json(raw)
        if doc.run_id != assembly.client.run_id:
            raise TaskConflict('Lifecycle sources require the original run and an explicit independent-input boundary')
        self.plans = doc.plans
        self._by_id = {p.plan_id: p for p in self.plans}
        if not self.plans or len(self._by_id) != len(self.plans):
            raise TaskConflict('Lifecycle source plans require unique nonempty identities')
        if len({task_digest(p.context.model_dump(mode='json')) for p in self.plans}) != len(self.plans):
            raise TaskConflict('Lifecycle plans cannot share an original invocation context')
        for field in ('operation_id', 'read_token'):
            if len({(p.organization_id, getattr(p.context, field)) for p in self.plans}) != len(self.plans):
                raise TaskConflict('Lifecycle actions require distinct original operations and reading identities')
        tokens = [(plan.organization_id, context.read_token) for plan in self.plans
            for context in ([plan.context, preparation_context(plan)] if plan.private_intake_judgment else [plan.context])]
        if len(tokens) != len(set(tokens)):
            raise TaskConflict('Private assessment preparation requires its distinct original reading identity')
        self._bound, self._actions = {}, {}
        self._private_learning = NativePrivateIntakeJudgments(self) if any(
            plan.private_intake_judgment is not None for plan in self.plans) else None
        self._code = {}
        seen = set()
        for plan in self.plans:
            role = assembly.client.organization_roles.get(plan.organization_id)
            if (role not in EVENT_ROLES[plan.event_type] or plan.context.run_id != doc.run_id
                    or any(dep not in seen for dep in plan.depends_on)):
                raise TaskConflict('Lifecycle plan changes the original party, run or topological action order')
            for dep in plan.depends_on:
                prior = self._by_id[dep]
                if (prior.organization_id != plan.organization_id or prior.project_id != plan.project_id
                        or prior.tick > plan.tick or prior.context.business_time.clock_ref != plan.context.business_time.clock_ref
                        or not scope_covers(plan.context.scope, prior.context.scope)):
                    raise TaskConflict('Cross-party lifecycle handoff requires original authorized reception, not private dependency copying')
            if plan.contractor_final_account_history is not None:
                from integration.contractor_final_account_history import validate_history_plan
                validate_history_plan(plan, self._by_id[plan.contractor_final_account_history.plan_id])
            grants = authority.organizations.grants(plan.context, plan.context.contract_ref.id, role)
            if not grants or any(g.organization_id != plan.organization_id for g in grants):
                raise TaskConflict('Lifecycle source is not covered by its actual original organization authority')
            assembler_type, worker_type = _action_types(plan.context.contract_ref.id, role)
            arguments = self._build_arguments(plan)
            inspect.signature(assembler_type.build).bind(None, plan.context, **arguments)
            schemas = assembler_type.SOURCE_SCHEMAS()
            for item in plan.objects:
                value = deepcopy(item['value'])
                if item['ref'] in [p.model_dump(mode='json') for p in
                        (plan.native_evidence_ref, plan.dependency_evidence_ref,
                         plan.final_account_question_reception.evidence_ref if plan.final_account_question_reception else None)
                        + (plan.final_account_question_reception.contractor_evidence_ref if plan.final_account_question_reception else None,
                           plan.final_account_position_reception.evidence_ref if plan.final_account_position_reception else None,
                           plan.final_account_owner_reception.evidence_ref if plan.final_account_owner_reception else None)
                        if p is not None]:
                    value['content_hash'] = '0' * 64  # schema-only copy, never a source or persisted input
                feedback_ref = plan.appointment_feedback_ref or plan.settlement_feedback_ref
                if feedback_ref is not None and item['ref'] == feedback_ref.model_dump(mode='json'):
                    value['event']['subject_sha256'] = value['event_sha256'] = '0' * 64
                schemas.validate_projection(Reference.model_validate(item['ref']), value)
            self._code[plan.plan_id] = self._descriptors(assembler_type, worker_type)
            assembler = assembler_type(registry=authority.registry, organizations=authority.organizations,
                provider=self, macro_version='gba-public-2026-08-21',
                source_mode='fixture' if plan.private_intake_judgment is not None else 'formal',
                policy_version=self.settings.policy_version, model_version=assembly.client.versions['model'],
                model_host=model_host)
            if self._private_learning is not None:
                self._private_learning.attach(plan, assembler)
            worker = worker_type(store=assembly.client.tasks, snapshots=InvocationSnapshotStore(assembly.client.tasks),
                registry=authority.registry, client_version=self.VERSION, model_version=assembly.client.versions['model'],
                validate_invocation=self.validate_invocation, validate_wait=self.validate_wait,
                validate_recovery=self.validate_recovery)
            self._actions[plan.plan_id] = (assembler, worker)
            seen.add(plan.plan_id)
        self._fingerprint = self._source_fingerprint()
        self._original_actions = dict(self._actions)
        self._components = (assembly, assembly.engine, assembly.client, authority, authority.registry,
                            authority.organizations, assembly.client.tasks, assembly.engine.events, model_host,
                            self._private_learning)
        # This is the frozen native event system's public observer API.
        assembly.engine.events.add_observer(self.observe)

    @staticmethod
    def _descriptors(assembler, worker):
        return [{'class': cls.__module__ + ':' + cls.__name__,
                 'source_sha256': hashlib.sha256(Path(inspect.getsourcefile(cls)).read_bytes()).hexdigest(),
                 'operation': module_factory_descriptor(operation, cls.__name__)}
                for cls, operation in ((assembler, assembler.build), (worker, worker.execute))]

    def _build_arguments(self, plan):
        """Keep the original full input contract and its exact scope invariant."""
        contract = self.authority.registry.get(plan.context.contract_ref.id).contract
        values = contract.validate_input(plan.action_input).model_dump(mode='json')
        if 'scope_ref' in values and values['scope_ref'] != plan.context.scope.model_dump(mode='json'):
            raise TaskConflict('Lifecycle contract input changes its original context scope')
        # These two original assemblers derive scope_ref from their context;
        # their public action contracts still require and validate the field.
        if plan.context.contract_ref.id in {'SUPPLIER-A05', 'SUPPLIER-A07'}:
            values.pop('scope_ref')
        return values

    def _source_fingerprint(self):
        from integration import native_lifecycle_dependencies
        projection = None
        if any(p.appointment_feedback_ref is not None for p in self.plans):
            from integration.professional_intake_feedback import authenticate_appointment, authenticate_intake_decision
            projection = [module_factory_descriptor(f, self.VERSION) for f in
                (authenticate_intake_decision, authenticate_appointment)]
        communication = None
        if any(p.final_account_disclosure is not None or p.final_account_question_reception is not None
                or p.final_account_position_reception is not None or p.final_account_owner_reception is not None for p in self.plans):
            from integration.bindings.gba_v1_final_account_positions import publish_final_account_position, receive_owner_position, receive_contractor_position_for_question, receive_qs_question_for_owner
            from integration.bindings.gba_v1_tender_clarification import _publish_once
            communication = [module_factory_descriptor(f, self.VERSION) for f in
                (publish_final_account_position, receive_owner_position, receive_contractor_position_for_question,
                 receive_qs_question_for_owner, _publish_once)]
        history = None
        if any(p.contractor_final_account_history is not None for p in self.plans):
            from integration.contractor_final_account_history import bind_history
            history = module_factory_descriptor(bind_history, self.VERSION)
        payment = None
        if any(p.event_type in {'payment_requested','payment_delayed'} for p in self.plans):
            from integration.native_progress_payment_trigger import payment_trigger_origin
            payment = module_factory_descriptor(payment_trigger_origin, self.VERSION)
        return (task_digest(self.settings.model_dump(mode='json')),
            hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest(),
            task_digest([p.model_dump(mode='json') for p in self.plans]),
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), task_digest(projection), task_digest(communication), task_digest(history),
            hashlib.sha256(Path(native_lifecycle_dependencies.__file__).read_bytes()).hexdigest(),task_digest(payment),
            hashlib.sha256(Path(inspect.getsourcefile(NativePrivateIntakeJudgments)).read_bytes()).hexdigest())

    def check(self):
        a, authority = self.assembly, self.authority
        authority._check()
        current = (a, a.engine, a.client, authority, authority.registry, authority.organizations,
                   a.client.tasks, a.engine.events, self.model_host, self._private_learning)
        if (any(x is not y for x, y in zip(current, self._components))
                or set(self._actions) != set(self._by_id) or set(self._actions) != set(self._original_actions)
                or any(self._by_id.get(p.plan_id) is not p for p in self.plans)
                or any(self._actions[k] != self._original_actions[k] for k in self._actions)
                or self._source_fingerprint() != self._fingerprint
                or self._fingerprint[1] != self.settings.file_sha256
                or a.engine.events._observers.count(self.observe) != 1):
            raise TaskConflict('Lifecycle sources changed original authority, journal, observer or source version')
        a._validate_components()
        for key, (assembler, worker) in self._actions.items():
            if (worker.store is not a.client.tasks or worker.registry is not authority.registry
                    or assembler.registry is not authority.registry or assembler._views.provider is not (
                        self._private_learning.provider_for(self._by_id[key]) if self._private_learning else self)
                    or assembler.organizations is not authority.organizations
                    or worker.validate_invocation != self.validate_invocation
                    or worker.validate_wait != self.validate_wait
                    or worker.validate_recovery != self.validate_recovery
                    or self._descriptors(type(assembler), type(worker)) != self._code[key]):
                raise TaskConflict('Lifecycle action replaced its original worker, assembler or shared components')
        if self._private_learning is not None:
            self._private_learning.check()

    def _event(self, plan, event):
        engine, client = self.assembly.engine, self.assembly.client
        project = engine.projects.get(plan.project_id)
        if plan.native_contractor_id is not None and (project is None or project.selected_contractor_id != plan.native_contractor_id):
            raise TaskConflict('Lifecycle source changes its independently declared actual Contractor')
        original = event.model_dump(mode='json')
        global_rows = [e for e in engine.events.events if e.event_id == event.event_id]
        local_rows = [] if project is None else [e for e in project.event_log if e['event_id'] == event.event_id]
        # The frozen EventSystem appends project.event_log before notifying
        # observers, then adds agent_observer_errors to the global event when
        # an observer raises. Authenticate every business field while retaining
        # that later diagnostic separately; it cannot replace or amend a fact.
        def business_event(value):
            value = deepcopy(value)
            errors = value['data'].pop('agent_observer_errors', [])
            if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
                raise TaskConflict('Lifecycle native observer diagnostics have an invalid original shape')
            return value
        if (not event.event_id or len(global_rows) != 1 or len(local_rows) != 1
                or business_event(global_rows[0].model_dump(mode='json')) != business_event(original)
                or business_event(local_rows[0]) != business_event(original)
                or (event.project_id, event.event_type, event.tick) != (plan.project_id, plan.event_type, plan.tick)):
            raise TaskConflict('Lifecycle trigger lost its exact original global/project native event')
        role = client.organization_roles[plan.organization_id]
        if event.event_type == 'appointment_decision':
            party = event.agent_id
        elif event.event_type == 'consultant_team_appointed':
            from integration.professional_intake_feedback import ROLE_FIELD
            party = event.data.get(ROLE_FIELD[role])
        else:
            party = {'Owner': project.owner_id, 'Bank': project.selected_bank_id, 'QS': project.selected_qs_id,
                'Contractor': project.selected_contractor_id, 'Supplier': event.data.get('supplier_id')}[role]
        if (party != plan.organization_id or role == 'Supplier' and party not in project.selected_supplier_ids
                or role == 'Bank' and event.data.get('selected_bank_id') != party):
            raise TaskConflict('Lifecycle trigger is not visible to this actual original project party')
        data = {k: deepcopy(event.data[k]) for k in EVENT_FIELDS[event.event_type] if k in event.data}
        if event.event_type in {'appointment_decision', 'consultant_team_appointed'}:
            from integration.professional_intake_feedback import authenticate_appointment, authenticate_intake_decision
            projection = (authenticate_appointment if event.event_type == 'consultant_team_appointed'
                else authenticate_intake_decision)
            data = projection(self.assembly, event=original, organization_id=plan.organization_id)
        if event.event_type == 'project_financing_selected':
            from gba_construction_sim.backend.agents.contracts import AgentObservationV1
            from integration.project_financing_feedback import project_financing_event
            if (event.agent_id != project.owner_id
                    or event.data.get('selected_bank_id') != project.selected_bank_id
                    or event.data.get('financing_mode') not in {'bank_finance', 'owner_equity'}
                    or (event.data['financing_mode'] == 'bank_finance') != (project.selected_bank_id is not None)):
                raise TaskConflict('Lifecycle financing trigger changes its actual selecting Owner, Bank or financing mode')
            # Reuse the existing role-scoped reception. In particular, the Bank
            # receives its selection only, not Owner's private task identity,
            # another Bank's quote or a claim that funds were disbursed.
            reception = project_financing_event(AgentObservationV1.model_validate(original), client.organization_roles)
            if plan.organization_id not in reception:
                raise TaskConflict('Lifecycle financing event has no original authorized recipient projection')
            data = reception[plan.organization_id]['data']
        if plan.settlement_feedback_ref is not None:
            reviews = [row for row in project.event_log if row['event_type'] == 'final_account_review_started'
                       and row['tick'] < event.tick]
            if (event.agent_id != (project.selected_qs_id or project.owner_id) or len(reviews) != 1
                    or any(event.data.get(field) != actual for field, actual in (
                        ('owner_id', project.owner_id), ('contractor_id', project.selected_contractor_id),
                        ('qs_id', plan.organization_id)))):
                raise TaskConflict('QS settlement feedback requires actual own parties and strictly earlier native review')
            data['observed_review_event_id'] = reviews[0]['event_id']
        view = {'event_id': event.event_id, 'event_type': event.event_type, 'project_id': event.project_id,
            'tick': event.tick, 'organization_id': plan.organization_id,
            'data': data,
            'source_event_sha256': task_digest(business_event(original)),
            'source_event_sha256_boundary': 'original_native_event_excluding_agent_observer_errors',
            'boundary': 'Actual aggregate native event, not a detailed order, release, certificate, delivery or cash receipt.'}
        if event.event_type in {'payment_requested','payment_delayed'}:
            from integration.native_progress_payment_trigger import payment_trigger_origin
            view['payment_origin'] = payment_trigger_origin(self.assembly,event=event,organization_id=plan.organization_id)
            view['projection_implementation_sha256'] = task_digest(
                module_factory_descriptor(payment_trigger_origin, self.VERSION))
        if event.event_type in {'appointment_decision', 'consultant_team_appointed'}:
            view['projection_implementation_sha256'] = task_digest(
                module_factory_descriptor(projection, self.VERSION))
        if plan.final_account_question_reception is not None or plan.final_account_position_reception is not None:
            from integration.bindings.gba_v1_final_account_positions import receive_owner_position, receive_contractor_position_for_question
            view['data']['received_owner_position'] = receive_owner_position(self, plan)
            if plan.final_account_question_reception is not None and plan.final_account_question_reception.contractor_evidence_ref is not None:
                view['data']['received_contractor_position'] = receive_contractor_position_for_question(self, plan)
            view['projection_implementation_sha256'] = task_digest(
                module_factory_descriptor(receive_owner_position, self.VERSION))
        if plan.final_account_owner_reception is not None:
            from integration.bindings.gba_v1_final_account_positions import receive_qs_question_for_owner
            view['data']['received_qs_question'] = receive_qs_question_for_owner(self, plan)
            view['projection_implementation_sha256'] = task_digest(
                module_factory_descriptor(receive_qs_question_for_owner, self.VERSION))
        return view

    def _is_recipient(self, plan, event):
        project = self.assembly.engine.projects.get(plan.project_id)
        if project is None:
            return False
        if plan.native_contractor_id is not None and project.selected_contractor_id != plan.native_contractor_id:
            return False
        role = self.assembly.client.organization_roles[plan.organization_id]
        if event.event_type == 'appointment_decision':
            return event.agent_id == plan.organization_id
        if event.event_type == 'consultant_team_appointed':
            from integration.professional_intake_feedback import ROLE_FIELD
            return event.data.get(ROLE_FIELD[role]) == plan.organization_id
        party = {'Owner': project.owner_id, 'Bank': project.selected_bank_id, 'QS': project.selected_qs_id,
                 'Contractor': project.selected_contractor_id, 'Supplier': event.data.get('supplier_id')}[role]
        return party == plan.organization_id

    def _key(self, plan):
        return self.PREFIX + task_digest([self.assembly.client.simulation_id, plan.plan_id])

    def _record(self, plan):
        store, key = self.assembly.client.tasks, self._key(plan)
        with store._lock:
            row = store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        if (record.get('key') != key or record.get('plan_id') != plan.plan_id
                or record.get('record_sha256') != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Lifecycle action journal lost its original identity or retained content')
        if 'identity' in record:
            identity = TaskIdentity(**record['identity'])
            if (identity.run_id != plan.context.run_id or identity.organization_id != plan.organization_id
                    or identity.action_id != plan.context.contract_ref.id
                    or identity.role != self.assembly.client.organization_roles[plan.organization_id]
                    or identity.purpose != 'action' or identity.request_id != key
                    or identity.context_sha256 != task_digest(plan.context.model_dump(mode='json'))):
                raise TaskConflict('Lifecycle journal substituted the original action context or organization')
        return record

    def _saved_identity(self, plan, record):
        """Find the original registration even if the caller stopped before saving its identity."""
        tasks = self.assembly.client.tasks.for_organization(
            run_id=plan.context.run_id, organization_id=plan.organization_id)
        matches = [r for r in tasks if r['identity']['purpose'] == 'action'
                   and r['identity']['request_id'] == self._key(plan)]
        if len(matches) > 1 or not matches and 'identity' in record:
            raise TaskConflict('Lifecycle recovery lost its unique original registered task')
        if not matches:
            return None
        identity = TaskIdentity(**matches[0]['identity'])
        worker = self._actions[plan.plan_id][1]
        snapshot = worker.snapshots.get(identity)
        contract = self.authority.registry.get(plan.context.contract_ref.id).contract
        expected_input = contract.validate_input(plan.action_input).model_dump(mode='json')
        if (identity.action_id != plan.context.contract_ref.id
                or identity.role != self.assembly.client.organization_roles[plan.organization_id]
                or snapshot['context'] != plan.context.model_dump(mode='json')
                or snapshot['action_input'] != expected_input
                or 'identity' in record and record['identity'] != identity.as_dict()):
            raise TaskConflict('Lifecycle recovery changes the original context, complete input or identity')
        return identity

    def _saved_sources(self, plan, record):
        events = [e for e in self.assembly.engine.events.events
                  if e.event_id == record['observed']['event_id']]
        if len(events) != 1 or self.assembly.engine.current_tick < plan.tick:
            raise TaskConflict('Lifecycle recovery requires the actual retained event and original clock')
        objects, observed, dependencies = self._sources(plan, events[0])
        if (record['source_sha256'] != task_digest(objects) or record['observed'] != observed
                or record['dependencies'] != dependencies):
            raise TaskConflict('Lifecycle recovery changed its original sources, event or dependencies')
        return objects

    def _current_versions(self, plan):
        assembler, worker = self._actions[plan.plan_id]
        runner = ActionRunner(self.authority.registry, organizations=self.authority.organizations,
            methods=assembler.methods, policy_version=assembler.policy_version,
            model_version=assembler.model_version, decision_strategies=assembler.decision_strategies)
        return prepared_action_execution_versions(SimpleNamespace(context=plan.context, runner=runner),
            client_version=worker.client_version, model_version=worker.model_version)

    def query_saved_result(self, plan_id):
        """Read existing evidence only. Neither missing results nor tasks are recreated."""
        with self.authority.read_guard():
            self.check()
            plan = self._by_id[plan_id]
            record = self._record(plan)
            if record is None:
                return {'status': 'not_started', 'plan_id': plan_id}
            if record['state'] == 'waiting_dependencies':
                from integration.native_lifecycle_dependencies import query_dependency_wait
                return query_dependency_wait(self, plan, record)
            from integration.native_lifecycle_dependencies import authorize_private_sources
            grants = authorize_private_sources(self, plan)
            self._saved_sources(plan, record)
            identity = self._saved_identity(plan, record)
            if identity is None:
                return {'status': 'unknown', 'plan_id': plan_id, 'reason': 'no_original_registration'}
            if identity.versions != self._current_versions(plan):
                raise TaskConflict('Lifecycle result query changes the original seven execution versions')
            worker = self._actions[plan_id][1]
            saved = worker.get_record(identity)
            task = worker.store.get(identity)
            if saved is None:
                return {'status': 'unknown', 'plan_id': plan_id, 'identity': identity.as_dict(),
                        'task_state': task['state'], 'reason': 'no_original_saved_result'}
            readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in plan.context.visible_refs}
            if any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading']):
                raise TaskConflict('Lifecycle result query lost authority for its retained private sources')
            if record.get('result_sha256', saved['result_sha256']) != saved['result_sha256']:
                raise TaskConflict('Lifecycle result query changed its original retained result')
            if plan.private_intake_judgment is not None:
                self._private_learning.validate_saved_reading(plan, saved)
            return {'status': 'saved', 'plan_id': plan_id, 'identity': identity.as_dict(),
                    'task_state': task['state'], 'record': saved,
                    'observer_errors': self._observer_errors(record['observed']['event_id'])}

    def _observer_errors(self, event_id):
        events = [e for e in self.assembly.engine.events.events if e.event_id == event_id]
        if len(events) != 1:
            raise TaskConflict('Lifecycle diagnostics lost their unique original event')
        errors = events[0].data.get('agent_observer_errors', [])
        if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
            raise TaskConflict('Lifecycle native observer diagnostics have an invalid original shape')
        return deepcopy(errors)

    def validate_recovery(self, row, saved, snapshot):
        identity = TaskIdentity(**row['identity'])
        plans = [p for p in self.plans if self._key(p) == identity.request_id
                 and p.organization_id == identity.organization_id]
        if len(plans) != 1:
            raise TaskConflict('Lifecycle recovery requires one original event-bound plan')
        plan = plans[0]
        original = self.query_saved_result(plan.plan_id)
        if (original['status'] != 'saved' or original['identity'] != identity.as_dict()
                or original['record'] != saved or snapshot['context'] != plan.context.model_dump(mode='json')
                or row != self.assembly.client.tasks.get(identity)):
            raise TaskConflict('Lifecycle recovery changed its original saved result or active task revision')
        return True

    def recover_saved_result(self, plan_id):
        """Finalize only an already saved original result, never call build/execute or submit."""
        with self.authority.read_guard():
            original = self.query_saved_result(plan_id)
            if original['status'] != 'saved':
                return original
            plan, worker = self._by_id[plan_id], self._actions[plan_id][1]
            record, identity = self._record(plan), TaskIdentity(**original['identity'])
            saved = original['record']
            # Historical pending conditions need a new authorized continuation;
            # they cannot be finalized as if their old event were current.
            if (original['task_state'] == 'processing' and saved['result']['kind'] not in {'completed', 'technical_error'}
                    and self.assembly.engine.current_tick != plan.tick):
                return {**original, 'status': 'saved_pending_current_continuation'}
            if original['task_state'] == 'processing' and saved['result']['kind'] not in {'completed', 'technical_error'}:
                event = next(e for e in self.assembly.engine.events.events if e.event_id == record['observed']['event_id'])
                self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, event.model_copy(deep=True))
            # The original worker owns lifecycle finalization and its revision checks.
            worker._finalize(identity, saved, recovered=True)
            task = worker.store.get(identity)
            if saved['result']['kind'] == 'completed':
                checked_result(worker, identity)
                state = 'formed'
            elif task['state'] in {'waiting_input', 'technical_failure'}:
                state = 'unresolved'
            else:
                raise TaskConflict('Lifecycle saved result has no finalized original task outcome')
            record.update(state=state, identity=identity.as_dict(), result_sha256=saved['result_sha256'],
                          result_kind=saved['result']['kind'])
            self._save(plan, record)
            return {**original, 'status': state, 'task_state': task['state']}

    def _save(self, plan, record):
        record = deepcopy(record)
        record.update(key=self._key(plan), plan_id=plan.plan_id)
        record['record_sha256'] = task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
        store = self.assembly.client.tasks
        with store._transaction():
            store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)', (record['key'], canonical(record)))
        return record

    def _sources(self, plan, event):
        observed = self._event(plan, event)
        dependencies = []
        for key in plan.depends_on:
            prior, record = self._by_id[key], self._record(self._by_id[key])
            if record is None or record['state'] != 'formed':
                raise TaskConflict('Lifecycle dependency requires its exact completed original private action')
            from integration.native_lifecycle_dependencies import authorize_private_sources
            authorize_private_sources(self, prior)
            worker = self._actions[key][1]
            saved = checked_result(worker, TaskIdentity(**record['identity']))
            authorize_private_sources(self, prior, source_reading=saved['source_reading'])
            if saved['result_sha256'] != record['result_sha256']:
                raise TaskConflict('Lifecycle dependency replaced its original result')
            dependencies.append({'plan_id': prior.plan_id, 'identity': record['identity'],
                'result_sha256': saved['result_sha256'], 'result': deepcopy(saved['result']),
                'boundary': 'Original private action result; not evidence of formal downstream execution.'})
            if prior.final_account_disclosure is not None:
                receipt = self.query_final_account_position(prior.plan_id)
                if receipt['status'] != 'observed':
                    raise TaskConflict('Lifecycle successor requires the actual original native communication receipt')
                dependencies[-1]['native_communication'] = receipt
            if prior.final_account_question_reception is not None and prior.final_account_question_reception.publish_question_text:
                receipt = self.query_final_account_question(prior.plan_id)
                if receipt['status'] != 'observed':
                    raise TaskConflict('Lifecycle successor requires the actual original native question receipt')
                dependencies[-1]['native_communication'] = receipt
        objects = deepcopy(plan.objects)
        evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), observed)
        if plan.final_account_question_reception is not None:
            reception = plan.final_account_question_reception
            received = observed['data']['received_owner_position']
            evidence_binding(objects, reception.evidence_ref.model_dump(mode='json'), received)
            question, = [r['value'] for r in objects if r['ref'] == reception.question_ref.model_dump(mode='json')]
            question['question'] += '\nReceived Owner communication (not agreed settlement facts):\n' + '\n'.join(
                message['content'] for message in received['messages'])
            if reception.contractor_evidence_ref is not None:
                received = observed['data']['received_contractor_position']
                evidence_binding(objects, reception.contractor_evidence_ref.model_dump(mode='json'), received)
                question['question'] += '\nReceived Contractor communication (not agreed settlement facts):\n' + '\n'.join(
                    message['content'] for message in received['messages'])
        if plan.final_account_position_reception is not None:
            reception = plan.final_account_position_reception
            received = observed['data']['received_owner_position']
            evidence_binding(objects, reception.evidence_ref.model_dump(mode='json'), received)
            profile, = [r['value'] for r in objects if r['ref'] == reception.profile_ref.model_dump(mode='json')]
            profile['note'] += '\nReceived Owner communication (not agreed settlement facts):\n' + '\n'.join(
                message['content'] for message in received['messages'])
        if plan.final_account_owner_reception is not None:
            reception = plan.final_account_owner_reception
            received = observed['data']['received_qs_question']
            evidence_binding(objects, reception.evidence_ref.model_dump(mode='json'), received)
            decision, = [r['value'] for r in objects if r['ref'] == reception.decision_ref.model_dump(mode='json')]
            decision['note'] += '\nReceived QS question (not supplied evidence or an agreed settlement):\n' + '\n'.join(
                message['content'] for message in received['messages'])
        if plan.dependency_evidence_ref is not None:
            evidence_binding(objects, plan.dependency_evidence_ref.model_dump(mode='json'), dependencies)
        if plan.contractor_final_account_history is not None:
            from integration.contractor_final_account_history import bind_history
            bind_history(self, plan, objects, dependencies)
        feedback_ref = plan.appointment_feedback_ref or plan.settlement_feedback_ref
        if feedback_ref is not None:
            by_ref = {task_digest(r['ref']): r['value'] for r in objects}
            feedback = by_ref[task_digest(feedback_ref.model_dump(mode='json'))]
            subject = by_ref[task_digest(plan.native_evidence_ref.model_dump(mode='json'))]
            bind_outcome(plan, feedback, observed)
            feedback['event'].update(event_key=self.assembly.client.simulation_id + ':' + event.event_id + ':' + plan.organization_id,
                subject_sha256=task_digest(subject), occurred_at=plan.context.business_time.model_dump(mode='json'))
            feedback['event_sha256'] = task_digest(feedback['event'])
            decision = by_ref[task_digest(by_ref[task_digest(plan.action_input['strategy_ref'])]['decision_profile_ref'])]
            if plan.settlement_feedback_ref is not None:
                decision['interpretation'] = ('Authenticated own native aggregate final-account settlement: '
                    + canonical(observed['data']) + '. This record proves no cash payment, debt clearance, '
                    'detailed certificate, forecast error, judgment or capability change.')
            else:
                meaning = ('Native Owner selection has occurred; this record creates no detailed appointment, '
                    if event.event_type == 'consultant_team_appointed' else
                    'Acceptance alone does not establish Owner selection; this record creates no appointment, ')
                decision['interpretation'] = ('Authenticated own native appointment outcome: '
                    + observed['data']['status'] + '. ' + meaning
                    + 'service delivery, fee, cash, judgment or capability change.')
                if plan.private_intake_judgment is not None:
                    decision['interpretation'] = ('Actual own Owner selection supplies only the declared appointed '
                        'signal for a simulation-only private intake recommendation; no applied strategy or capability change.')
        return objects, observed, dependencies

    def project(self, *, context, organization_id, grants):
        plan, event = self._bound[task_digest(context.model_dump(mode='json'))]
        allowed = (plan.context, preparation_context(plan)) if plan.private_intake_judgment else (plan.context,)
        if context not in allowed or organization_id != plan.organization_id:
            raise TaskConflict('Lifecycle projection changes its original action or private organization')
        objects, observed, dependencies = self._sources(plan, event)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'actual-native-lifecycle-event:' + task_digest([observed, dependencies]),
            'read_token': context.read_token, 'business_time': context.business_time.model_dump(mode='json'),
            'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        self.check()
        plan, event = self._bound[prepared.context_sha256]
        if (prepared.context != plan.context or row['identity']['organization_id'] != plan.organization_id
                or self.assembly.engine.current_tick != plan.tick):
            raise TaskConflict('Lifecycle action lost its original current event, clock or recipient')
        self._sources(plan, event)
        prepared.reading.recheck()
        return True

    def validate_wait(self, row, result, conditions):
        self.check()
        plan, event = self._bound[row['identity']['context_sha256']]
        worker = self._actions[plan.plan_id][1]
        if (self.assembly.engine.current_tick != plan.tick
                or row['identity']['organization_id'] != plan.organization_id
                or row['identity']['action_id'] != plan.context.contract_ref.id
                or result.get('kind') not in {'needs_information', 'unsupported', 'deferred'}
                or len(conditions) != 1 or conditions[0].get('kind') != worker.WAIT_KIND
                or conditions[0].get('result_kind') != result['kind']
                or conditions[0].get('result_sha256') != task_digest(result)):
            raise TaskConflict('Lifecycle wait lost its original source, recipient or unchanged pending result')
        self._sources(plan, event)
        # Persist the original pending condition. This application has no
        # automatic resume/retry or replacement native business response.
        return True

    def observe(self, event, project=None):
        return self._dispatch_event(event)

    def resume_waiting_dependencies(self, plan_id):
        """Start only a never-registered ready successor at its original clock."""
        from integration.native_lifecycle_dependencies import validate_dependency_wait
        with self.authority.read_guard():
            self.check()
            plan = self._by_id[plan_id]
            record = self._record(plan)
            if record is None or record['state'] != 'waiting_dependencies':
                raise TaskConflict('Explicit dependency continuation requires an original unstarted dependency wait')
            event = validate_dependency_wait(self, plan, record)
            if self.assembly.engine.current_tick != plan.tick:
                raise TaskConflict('Lifecycle dependency continuation cannot start at a historical clock')
            self._dispatch_event(event, resume_plan_id=plan_id)
            result = self.query_saved_result(plan_id)
            if result['status'] == 'saved':
                return {**result, 'status': self._record(plan)['state']}
            return result

    def _dispatch_event(self, event, *, resume_plan_id=None):
        from integration.native_lifecycle_dependencies import retain_dependency_wait
        selected = [p for p in self.plans if (p.project_id, p.tick, p.event_type) ==
                    (event.project_id, event.tick, event.event_type)
                    and (resume_plan_id is None or p.plan_id == resume_plan_id)]
        if not selected:
            return
        with self.authority.read_guard():
            self.check()
            for plan in selected:
                if not self._is_recipient(plan, event):
                    continue
                prior = self._record(plan)
                wait_origin = None
                if prior is None or prior['state'] == 'waiting_dependencies':
                    if retain_dependency_wait(self, plan, event, prior, resume=resume_plan_id is not None):
                        continue
                    if prior is not None:
                        wait_origin, prior = prior, None
                objects, observed, dependencies = self._sources(plan, event)
                worker = self._actions[plan.plan_id][1]
                if prior is not None:
                    if (prior.get('source_sha256') != task_digest(objects) or prior['observed'] != observed
                            or prior.get('dependencies') != dependencies):
                        raise TaskConflict('Lifecycle replay changes original event, sources or dependencies')
                    if prior['state'] not in {'formed', 'unresolved'}:
                        recovered = self.recover_saved_result(plan.plan_id)
                        if recovered['status'] not in {'formed', 'unresolved'}:
                            raise TaskConflict('Unknown lifecycle execution has no saved result; automatic replay is forbidden')
                        continue
                    saved = checked_result(worker, TaskIdentity(**prior['identity'])) if prior['state'] == 'formed' else worker.get_record(TaskIdentity(**prior['identity']))
                    if saved is None or saved['result_sha256'] != prior['result_sha256']:
                        raise TaskConflict('Lifecycle replay lost its exact saved original result')
                    if plan.final_account_disclosure is not None and prior['state'] == 'formed':
                        # An already claimed send is queried, never replayed.
                        self.query_final_account_position(plan.plan_id)
                    if (plan.final_account_question_reception is not None
                            and plan.final_account_question_reception.publish_question_text and prior['state'] == 'formed'):
                        self.query_final_account_question(plan.plan_id)
                    continue
                if self.assembly.engine.current_tick != plan.tick:
                    raise TaskConflict('Lifecycle action cannot start against a historical event clock')
                self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, event.model_copy(deep=True))
                if plan.private_intake_judgment is not None:
                    self._bound[task_digest(preparation_context(plan).model_dump(mode='json'))] = (plan, event.model_copy(deep=True))
                record = self._save(plan, {'state': 'preparing', 'observed': observed, 'dependencies': dependencies,
                    'source_sha256': task_digest(objects), 'formal_effect': 'not_submitted',
                    **({'dependency_wait_origin': wait_origin} if wait_origin is not None else {})})
                assembler = self._actions[plan.plan_id][0]
                if plan.private_intake_judgment is not None:
                    record['private_assessment'] = self._private_learning.prepare(plan)
                    self._save(plan, record)
                prepared = assembler.build(plan.context, **self._build_arguments(plan))
                # Bind the trigger and prerequisite results to the original
                # typed reading/audit, including actions whose own processor
                # only consumes the separately supplied detailed input views.
                prepared.reading.resolve(plan.native_evidence_ref)
                if plan.dependency_evidence_ref is not None:
                    prepared.reading.resolve(plan.dependency_evidence_ref)
                if plan.final_account_question_reception is not None:
                    prepared.reading.resolve(plan.final_account_question_reception.evidence_ref)
                    if plan.final_account_question_reception.contractor_evidence_ref is not None:
                        prepared.reading.resolve(plan.final_account_question_reception.contractor_evidence_ref)
                if plan.final_account_position_reception is not None:
                    prepared.reading.resolve(plan.final_account_position_reception.evidence_ref)
                if plan.final_account_owner_reception is not None:
                    prepared.reading.resolve(plan.final_account_owner_reception.evidence_ref)
                prepared.reading.recheck()
                prepared = replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))
                identity = worker.register(prepared, request_id=self._key(plan))
                record.update(state='processing', identity=identity.as_dict())
                self._save(plan, record)
                outcome = worker.execute(identity, prepared)
                saved = worker.get_record(identity)
                if saved is None or saved['result'] != outcome['result']:
                    raise TaskConflict('Lifecycle action lost its original durable result')
                record.update(state='formed' if outcome['result']['kind'] == 'completed' else 'unresolved',
                    result_sha256=saved['result_sha256'], result_kind=outcome['result']['kind'])
                self._save(plan, record)
                if plan.final_account_disclosure is not None and record['state'] == 'formed':
                    self.publish_final_account_position(plan.plan_id)
                if (plan.final_account_question_reception is not None
                        and plan.final_account_question_reception.publish_question_text and record['state'] == 'formed'):
                    self.publish_final_account_question(plan.plan_id)

    def publish_final_account_position(self, plan_id):
        from integration.bindings.gba_v1_final_account_positions import publish_final_account_position
        return publish_final_account_position(self, plan_id)

    def query_final_account_position(self, plan_id):
        from integration.bindings.gba_v1_final_account_positions import query_final_account_position
        return query_final_account_position(self, plan_id)

    def publish_final_account_question(self, plan_id):
        from integration.bindings.gba_v1_final_account_positions import publish_final_account_question
        return publish_final_account_question(self, plan_id)

    def query_final_account_question(self, plan_id):
        from integration.bindings.gba_v1_final_account_positions import query_final_account_question
        return query_final_account_question(self, plan_id)

    def evidence(self):
        with self.authority.read_guard():
            self.check()
            records = []
            for plan in self.plans:
                record = self._record(plan)
                if record is None:
                    continue
                if record['state'] == 'waiting_dependencies':
                    from integration.native_lifecycle_dependencies import validate_dependency_wait
                    validate_dependency_wait(self, plan, record)
                if record['state'] in {'formed', 'unresolved'}:
                    from integration.native_lifecycle_dependencies import authorize_private_sources
                    authorize_private_sources(self, plan)
                    worker = self._actions[plan.plan_id][1]
                    identity = TaskIdentity(**record['identity'])
                    saved = checked_result(worker, identity) if record['state'] == 'formed' else worker.get_record(identity)
                    if saved is None or saved['result_sha256'] != record['result_sha256']:
                        raise TaskConflict('Lifecycle evidence lost its original durable action result')
                    authorize_private_sources(self, plan, source_reading=saved['source_reading'])
                    events = [e for e in self.assembly.engine.events.events
                              if e.event_id == record['observed']['event_id']]
                    if len(events) != 1:
                        raise TaskConflict('Lifecycle evidence lost its actual original event')
                    objects, observed, dependencies = self._sources(plan, events[0])
                    if (record['source_sha256'] != task_digest(objects) or record['observed'] != observed
                            or record['dependencies'] != dependencies):
                        raise TaskConflict('Lifecycle evidence changed its original source/event/dependency binding')
                records.append(record)
            return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256,
                'actions': records,
                'final_account_communications': {p.plan_id: self.query_final_account_position(p.plan_id)
                    for p in self.plans if p.final_account_disclosure is not None
                    and self._record(p) is not None and self._record(p)['state'] == 'formed'},
                'final_account_questions': {p.plan_id: self.query_final_account_question(p.plan_id)
                    for p in self.plans if p.final_account_question_reception is not None
                    and p.final_account_question_reception.publish_question_text
                    and self._record(p) is not None and self._record(p)['state'] == 'formed'},
                'observer_diagnostics': {r['observed']['event_id']: self._observer_errors(r['observed']['event_id'])
                    for r in records if self._observer_errors(r['observed']['event_id'])},
                'untriggered_plan_ids': [p.plan_id for p in self.plans if self._record(p) is None],
                'waiting_dependency_plan_ids': [r['plan_id'] for r in records if r['state'] == 'waiting_dependencies'],
                'all_private_actions_formed': len(records) == len(self.plans) and all(r['state'] == 'formed' for r in records),
                'all_triggered_private_actions_formed': bool(records) and all(r['state'] == 'formed' for r in records),
                'formal_commands_submitted': False,
                'limits': 'Original private actions and authorized same-organization dependencies only. '
                    'Explicit final-account positions may use the existing native room; their receipts prove communication only. '
                    'Detailed business inputs remain independent sources, not native event-derived facts. '
                    'No formal command, second ledger, detailed core release, receipt, certificate or cash execution is created. '
                    'Cross-party handoffs, formal command bindings and process restart still require their original dedicated components.'}

    def close(self):
        # Remove only the callback installed by this application. No native
        # observer or business state is replaced during registration/cleanup.
        observers = self.assembly.engine.events._observers
        if self.observe in observers:
            observers.remove(self.observe)
