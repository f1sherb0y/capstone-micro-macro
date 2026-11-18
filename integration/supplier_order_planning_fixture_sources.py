"""Synthetic A05 sources from saved A04 and independently formed effective orders."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.role_contract_host import RoleContractInvocation
from integration.supplier_order_fixture_sources import SupplierOrderFixtureSettings, build_sources as build_order_sources
from integration.supplier_order_handoff import SupplierOrderHandoffBasisView, SupplierOrderFormationRecordView
from integration.supplier_order_results import SupplierOrderResultWorker
from integration.supplier_planning_fixture_sources import SupplierPlanningFixtureSettings, build_sources as build_planning_sources
from src.actions.contracts.common import EvidenceRecord, Known, Reference, StrictRecord, TextId, TimePoint
from src.actions.contracts.supplier_order_objects import FormationAcceptanceView, OrderProposalView
from src.actions.contracts.supplier_planning_objects import (
    SupplierPlanningOrderView, SupplierPlanningOrderLineView, SupplierWorkAuthorityView,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierOrderHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: SupplierOrderFixtureSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredOrderPartyConfirmation(StrictRecord):
    acceptance: FormationAcceptanceView
    author_grant: Authorization
    author_assignment: RoleAssignment


class DeclaredOrderPlanningRegistration(StrictRecord):
    schema_version: Literal['supplier-order-planning-registration.v1']
    registration_id: TextId
    basis: SupplierOrderHandoffBasisView
    formation_record: SupplierOrderFormationRecordView
    order: SupplierPlanningOrderView
    lines: Annotated[list[SupplierPlanningOrderLineView], Field(min_length=1)]
    work_authority: SupplierWorkAuthorityView
    confirmations: Annotated[list[DeclaredOrderPartyConfirmation], Field(min_length=1)]
    recorded_at: TimePoint
    producer: Literal['core']
    native_record: dict
    current_state: Literal['recorded', 'withdrawn', 'superseded']


class SupplierOrderPlanningFixtureSettings(SupplierPlanningFixtureSettings):
    order_history: SupplierOrderHistorySettings
    registration: DeclaredOrderPlanningRegistration


def check_order_connection_selection(*, request, settings, source):
    """Require a single exact original A04 selection for connected A05."""
    selection = settings.order_inputs
    if (settings.source_factory != 'integration.supplier_order_planning_fixture_sources:build_sources'
            or settings.source_version != _OrderPlanningReception.VERSION
            or selection is None or set(selection.selections) != {request.context.operation_id}):
        raise ValueError('Connected planning requires explicit original A04 selection and source factory')
    selected = selection.selections[request.context.operation_id]
    if (selected.order_identity.as_dict() != source.order_history.identity.as_dict()
            or selected.basis_ref.key() != source.registration.basis.ref.key()):
        raise ValueError('Connected planning changes selected A04 identity or independent order relation')


def check_order_connection_provenance(*, request, source, evidence):
    """Preserve original accepted agreement and native order/work lineage in saved A05."""
    basis, formation = source.registration.basis, source.registration.formation_record
    provenance = evidence.get('order_input')
    expected = {'kind': 'prepared', 'order_ref': source.registration.order.ref.model_dump(mode='json'),
        'work_authority_ref': request.action_input['work_authority_ref'],
        'order_identity': source.order_history.identity.as_dict(),
        'basis_sha256': task_digest(basis.model_dump(mode='json')),
        'order_record_sha256': basis.order_record_sha256, 'order_result_sha256': basis.order_result_sha256,
        'formation_record_sha256': basis.formation_record_sha256,
        'native_order_source_sha256': formation.native_source_sha256,
        'order_projection_sha256': formation.order_projection_sha256}
    if not isinstance(provenance, dict) or any(provenance.get(key) != value for key, value in expected.items()):
        raise ValueError('Connected planning lost exact original accepted A04 or native order/work-authority provenance')


class _OrderPlanningReception:
    VERSION = 'configured-supplier-order-planning-fixture-sources.v1'

    def __init__(self, request, settings, planning, order):
        self.request, self.settings = request.model_copy(deep=True), settings.model_copy(deep=True)
        self.planning, self.order = planning, order
        self._digest = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.order_history
        self.worker = SupplierOrderResultWorker(store=order.store, snapshots=InvocationSnapshotStore(order.store),
            registry=planning.registry, client_version=history.client_version, model_version=history.model_version,
            validate_invocation=order.validators.invocation, validate_wait=order.validators.wait,
            validate_recovery=order.validators.recovery)
        self._input = planning.registry.get('SUPPLIER-A04').contract.validate_input(history.request.action_input)
        self._originals = self._projections(history.source_settings.source_projection['objects'])
        self._current = self._projections(settings.source_projection['objects'])

    @staticmethod
    def _projections(rows):
        projections = {}
        for row in rows:
            if set(row) != {'ref', 'value'}:
                raise ValueError('Order planning requires exact supplied ref/value records')
            key = Reference.model_validate(row['ref']).key()
            if key in projections:
                raise ValueError('Order planning repeats an original source identity')
            projections[key] = row['value']
        return projections

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._digest):
            raise TaskConflict('Order planning changes current recipient or native declarations')
        self.planning.evidence()
        self.order.evidence()

    @contextmanager
    def read_guard(self, context):
        with self.planning.read_guard(context), self.order.read_guard(self.settings.order_history.request.context):
            self._check(context)
            try:
                yield
            finally:
                self._check(context)

    def validate_history(self, saved):
        self._check(saved.current_context)
        history, basis = self.settings.order_history, self.settings.registration.basis
        if (saved.identity.as_dict() != history.identity.as_dict() or saved.context != history.request.context
                or saved.action_input != self._input or saved.result.kind != 'completed'
                or saved.result.payload.choice != 'accept'
                or any(self._originals.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in saved.source_reading)
                or basis.order_task_sha256 != saved.identity.key or basis.order_record_sha256 != saved.record_sha256
                or basis.order_input_sha256 != saved.identity.input_sha256 or basis.order_context_sha256 != saved.identity.context_sha256
                or basis.order_result_sha256 != task_digest(saved.result.model_dump(mode='json'))
                or basis.order_audit_sha256 != task_digest(saved.audit)
                or basis.order_source_reading_sha256 != saved.source_reading_sha256
                or basis.proposal_agreement_sha256 != saved.proposal_agreement_sha256):
            raise TaskConflict('Order planning substitutes original accepted A04 or retained evidence')
        return True

    def validate_planning(self, *, saved, context, basis, source, order, lines, work_authority):
        self._check(context)
        self.validate_history(saved)
        registration = self.settings.registration
        if (registration.current_state != 'recorded' or basis != registration.basis
                or source != registration.formation_record or order != registration.order
                or work_authority != registration.work_authority
                or len({row.ref.key() for row in registration.lines}) != len(registration.lines)
                or {row.ref.key(): row for row in lines} != {row.ref.key(): row for row in registration.lines}
                or registration.recorded_at.clock_ref != context.business_time.clock_ref
                or not saved.context.business_time.offset <= registration.recorded_at.offset <= context.business_time.offset
                or not isinstance(order.effective, Known) or order.effective.value is not True
                or not isinstance(work_authority.permitted, Known) or work_authority.permitted.value is not True):
            raise TaskConflict('Order planning changes independently formed order, full lines or permitted work authority')
        for row in (basis, source, order, work_authority, *lines):
            if (self._current.get(row.ref.key()) != row.model_dump(mode='json')
                    or row.available_at.clock_ref != context.business_time.clock_ref
                    or row.available_at.offset > context.business_time.offset
                    or not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Order planning changes exact current native source or applicability')
        if (order.available_at.offset < registration.recorded_at.offset
                or work_authority.available_at.offset < registration.recorded_at.offset):
            raise TaskConflict('Effective order or work authority precedes independently declared native formation')
        retained = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        proposal = OrderProposalView.model_validate(retained[saved.action_input.order_proposal_ref.key()])

        def evidence_at(refs, at, *, original=False):
            if at.clock_ref != context.business_time.clock_ref or at.offset > context.business_time.offset:
                raise TaskConflict('Order confirmation evidence changes its actual use clock or time')
            for ref in {ref.key(): ref for ref in refs}.values():
                raw = self._current.get(ref.key())
                evidence = EvidenceRecord.model_validate(raw)
                if (evidence.ref != ref or evidence.source_kind != 'synthetic'
                        or original and retained.get(ref.key()) != raw
                        or evidence.effective_window is not None and not evidence.effective_window.contains(at)):
                    raise TaskConflict('Order confirmation changes original synthetic evidence or its validity at use')

        confirmations = registration.confirmations
        if (len({row.acceptance.ref.key() for row in confirmations}) != len(confirmations)
                or {row.acceptance.ref.key() for row in confirmations} != {ref.key() for ref in saved.action_input.counterpart_acceptance_refs}
                or len({row.acceptance.party_id for row in confirmations}) != len(confirmations)
                or not {source.buyer_id, source.payer_id} <= {row.acceptance.party_id for row in confirmations}):
            raise TaskConflict('Native order formation omits or repeats original independent party confirmations')
        actors = set()
        roles = {'OWN': 'Owner', 'BANK': 'Bank', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier',
            'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS', 'GOV': 'Government'}
        for confirmation in confirmations:
            acceptance, grant, assignment = confirmation.acceptance, confirmation.author_grant, confirmation.author_assignment
            authors = [row for row in self.settings.organization_snapshot.organizations
                if row.organization_id == acceptance.party_id and row.actor_id == acceptance.author_actor_id]
            if (retained.get(acceptance.ref.key()) != acceptance.model_dump(mode='json')
                    or retained.get(grant.ref.key()) != grant.model_dump(mode='json')
                    or retained.get(assignment.function_ref.key()) != assignment.model_dump(mode='json')
                    or acceptance.choice != 'accept' or acceptance.status != 'active'
                    or acceptance.run_id != context.run_id or acceptance.scope != order.scope
                    or acceptance.proposal_ref != proposal.ref or acceptance.offer_ref != source.offer_ref
                    or acceptance.terms_ref != source.terms_ref or acceptance.agreement_sha256 != source.agreement_sha256
                    or acceptance.party_id == saved.identity.organization_id or acceptance.author_actor_id == saved.context.actor_id
                    or acceptance.author_actor_id in actors
                    or acceptance.created_at.clock_ref != context.business_time.clock_ref
                    or not proposal.received_at.offset <= acceptance.created_at.offset <= registration.recorded_at.offset
                    or not acceptance.validity.contains(acceptance.created_at)
                    or not acceptance.validity.contains(registration.recorded_at)
                    or not grant.validity.contains(acceptance.created_at) or not grant.validity.contains(registration.recorded_at)
                    or grant.ref != acceptance.authorization_ref or grant.organization_id != acceptance.party_id
                    or grant.actor_id != acceptance.author_actor_id or grant.function_ref != acceptance.author_function_ref
                    or acceptance.action_id not in grant.action_ids
                    or not any(scope_covers(scope, order.scope) for scope in grant.scopes)
                    or not {source.offer_ref.key(), proposal.ref.key(), source.terms_ref.key()} <= {ref.key() for ref in grant.readable_refs}
                    or assignment.function_ref != grant.function_ref or assignment.role != roles.get(acceptance.action_id.split('-')[0])
                    or grant not in self.settings.organization_snapshot.authorizations
                    or len(authors) != 1 or assignment not in authors[0].assignments
                    or self._current.get(grant.ref.key()) != grant.model_dump(mode='json')
                    or self._current.get(assignment.function_ref.key()) != assignment.model_dump(mode='json')):
                raise TaskConflict('Native order formation substitutes original independent acceptance or author authority')
            actors.add(acceptance.author_actor_id)
            evidence_at(acceptance.evidence_refs, acceptance.created_at, original=True)
            for ref in [*grant.basis_refs, *assignment.basis_refs]:
                raw = self._current.get(ref.key())
                if raw is None or retained.get(ref.key()) != raw:
                    raise TaskConflict('Order confirmation replaces an original author authorization basis')
                if ref.kind == 'Evidence':
                    evidence_at([ref], acceptance.created_at, original=True)
        evidence_at([*basis.evidence_refs, *basis.relation_evidence_refs], basis.authored_at)
        evidence_at([source.native_evidence_ref, *[ref for row in (source, order, work_authority, *lines)
            for ref in row.evidence_refs]], context.business_time)
        expected_native = {'schema_version': 'supplier-native-order-formation-observation.v1', 'run_id': context.run_id,
            'recorded_at': registration.recorded_at.model_dump(mode='json'), 'producer': registration.producer,
            'core_event_id': source.core_event_id, 'proposal_ref': source.proposal_ref.model_dump(mode='json'),
            'agreement_sha256': source.agreement_sha256, 'order': order.model_dump(mode='json'),
            'lines': [row.model_dump(mode='json') for row in registration.lines],
            'work_authority': work_authority.model_dump(mode='json'),
            'confirmations': [row.model_dump(mode='json') for row in confirmations]}
        if registration.native_record != expected_native or task_digest(expected_native) != source.native_source_sha256:
            raise TaskConflict('Order planning changes exact native order/party/work-authority observation')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**self.planning.evidence(), 'schema_version': self.VERSION,
            'order_history_task_sha256': self.settings.order_history.identity.key,
            'order_history_journal': str(self.order.store.path),
            'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
            'limitations': ['Explicit synthetic independent native order and work-authority declaration from saved A04.',
                'No order, work permission, reservation, inventory or plan is created.']}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.order.close()
            finally:
                self.planning.close()


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = SupplierOrderPlanningFixtureSettings.model_validate(settings).model_copy(deep=True)
    history = settings.order_history
    journal = Path(history.source_settings.journal_path).resolve()
    if (offline is not True or settings.action_id != 'SUPPLIER-A05' or history.source_settings.action_id != 'SUPPLIER-A04'
            or history.identity.action_id != 'SUPPLIER-A04' or history.identity.role != 'Supplier'
            or history.identity.purpose != 'action' or history.identity.run_id != request.context.run_id
            or history.request.context.run_id != request.context.run_id
            or history.identity.organization_id != settings.source_projection['organization_id']
            or history.identity.organization_id != history.source_settings.source_projection['organization_id']
            or history.identity.request_id != history.request.context.operation_id
            or history.identity.context_sha256 != task_digest(history.request.context.model_dump(mode='json'))
            or history.identity.input_sha256 != task_digest(history.request.action_input)
            or history.request.context.contract_ref.id != 'SUPPLIER-A04'
            or history.request.context.scope != request.context.scope
            or history.request.context.business_time.clock_ref != request.context.business_time.clock_ref
            or history.request.context.business_time.offset > request.context.business_time.offset
            or history.source_settings.source_projection['macro_version'] != history.macro_version
            or history.identity.versions['client'] != history.client_version
            or history.identity.versions['model'] != history.model_version
            or journal == Path(settings.journal_path).resolve() or not journal.is_file()):
        raise ValueError('Order planning requires original same-run A04 and separate existing journal')
    planning = order = None
    try:
        planning = build_planning_sources(request=request, output_directory=output_directory, offline=True,
            settings=settings.model_dump(mode='json', exclude={'order_history', 'registration'}))
        order = build_order_sources(request=history.request, output_directory=output_directory, offline=True,
            settings=history.source_settings)
        binding = _OrderPlanningReception(request, settings, planning, order)
        return replace(planning, version=binding.VERSION, order_worker=binding.worker,
            validate_order_history=binding.validate_history, validate_order_planning=binding.validate_planning,
            read_guard=binding.read_guard, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if order is not None:
                order.close()
        finally:
            if planning is not None:
                planning.close()
        raise
