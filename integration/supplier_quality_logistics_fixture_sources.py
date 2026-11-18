"""Synthetic A08 sources linked to saved A07 and independent release confirmations."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.role_contract_host import RoleContractInvocation
from integration.supplier_logistics_fixture_sources import SupplierLogisticsFixtureSettings, build_sources as build_logistics_sources
from integration.supplier_quality_fixture_sources import SupplierQualityFixtureSettings, build_sources as build_quality_sources
from integration.supplier_quality_handoff import (
    SupplierQualityHandoffBasisView, SupplierQualityReleaseRecordView, supplier_quality_handoff_schemas,
)
from integration.supplier_quality_results import SupplierQualityResultWorker
from integration.supplier_production_quality_fixture_sources import (
    SupplierProductionQualityFixtureSettings, build_sources as build_linked_quality_sources,
)
from src.actions.contracts.common import EvidenceRecord, Known, Reference, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.supplier_logistics_objects import SupplierDispatchableView, SupplierDispatchReleaseView
from src.actions.contracts.supplier_quality_objects import (
    SupplierBatchRecheckView, SupplierQualityBatchView, SupplierQualityMethodView,
    SupplierQualityObservationMethodView, SupplierQualityRequirementView,
    SupplierVisibleDefectView,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierQualityHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: SupplierQualityFixtureSettings | SupplierProductionQualityFixtureSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredQualityDefectResolution(StrictRecord):
    """Existing native closure after independent recheck; no remedy is executed."""
    original_defect_ref: ref_type('Defect')
    closed_defect: SupplierVisibleDefectView
    recheck_ref: ref_type('BatchRecheck')
    closed_at: TimePoint
    core_event_id: TextId
    producer: Literal['core']
    evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class DeclaredProfessionalReleaseConfirmation(StrictRecord):
    recheck: SupplierBatchRecheckView
    method: SupplierQualityMethodView
    observation_method: SupplierQualityObservationMethodView
    requirements: Annotated[list[SupplierQualityRequirementView], Field(min_length=1)]
    author_grant: Authorization
    author_assignment: RoleAssignment
    defect_resolutions: list[DeclaredQualityDefectResolution]


class DeclaredQualityDispatchRegistration(StrictRecord):
    schema_version: Literal['supplier-quality-dispatch-registration.v1']
    registration_id: TextId
    basis: SupplierQualityHandoffBasisView
    release_record: SupplierQualityReleaseRecordView
    batch: SupplierQualityBatchView
    release: SupplierDispatchReleaseView
    dispatchables: Annotated[list[SupplierDispatchableView], Field(min_length=1)]
    confirmation: DeclaredProfessionalReleaseConfirmation
    native_record: dict
    current_state: Literal['released', 'withdrawn', 'superseded']


class SupplierQualityLogisticsFixtureSettings(SupplierLogisticsFixtureSettings):
    quality_history: SupplierQualityHistorySettings
    registration: DeclaredQualityDispatchRegistration


class _QualityDispatchReception:
    VERSION = 'configured-supplier-quality-logistics-fixture-sources.v1'

    def __init__(self, request, settings, logistics, quality):
        self.request, self.settings = request.model_copy(deep=True), settings.model_copy(deep=True)
        self.logistics, self.quality = logistics, quality
        self._digest = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.quality_history
        self.worker = SupplierQualityResultWorker(store=quality.store,
            snapshots=InvocationSnapshotStore(quality.store), registry=logistics.registry,
            client_version=history.client_version, model_version=history.model_version,
            validate_invocation=quality.validators.invocation, validate_wait=quality.validators.wait,
            validate_recovery=quality.validators.recovery)
        self._input = logistics.registry.get('SUPPLIER-A07').contract.validate_input(history.request.action_input)
        self._originals = self._projections(history.source_settings.source_projection['objects'])
        self._current = self._projections(self.settings.source_projection['objects'])

    @staticmethod
    def _projections(rows):
        result = {}
        for row in rows:
            if set(row) != {'ref', 'value'}:
                raise ValueError('Quality dispatch requires exact supplied ref/value projections')
            key = Reference.model_validate(row['ref']).key()
            if key in result:
                raise ValueError('Quality dispatch repeats an original source identity')
            result[key] = row['value']
        return result

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._digest):
            raise TaskConflict('Quality dispatch changes original recipient or declarations')
        self.logistics.evidence()
        self.quality.evidence()

    @contextmanager
    def read_guard(self, context):
        with self.logistics.read_guard(context), self.quality.read_guard(self.settings.quality_history.request.context):
            self._check(context)
            try:
                yield
            finally:
                self._check(context)

    def validate_history(self, saved):
        self._check(saved.current_context)
        history, basis = self.settings.quality_history, self.settings.registration.basis
        if (saved.identity.as_dict() != history.identity.as_dict() or saved.context != history.request.context
                or saved.action_input != self._input or saved.result.kind != 'completed'
                or any(self._originals.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in saved.source_reading)
                or basis.quality_task_sha256 != saved.identity.key or basis.quality_record_sha256 != saved.record_sha256
                or basis.quality_result_sha256 != task_digest(saved.result.model_dump(mode='json'))
                or basis.quality_audit_sha256 != task_digest(saved.audit)
                or basis.quality_source_reading_sha256 != saved.source_reading_sha256):
            raise TaskConflict('Quality dispatch changes the selected original A07 result or retained sources')
        return True

    def validate_dispatch(self, *, saved, context, basis, source, batch, release, dispatchables):
        self._check(context)
        self.validate_history(saved)
        registration = self.settings.registration
        if (registration.current_state != 'released' or basis != registration.basis
                or source != registration.release_record or batch != registration.batch or release != registration.release
                or {row.ref.key(): row for row in dispatchables} != {row.ref.key(): row for row in registration.dispatchables}
                or len({row.ref.key() for row in registration.dispatchables}) != len(registration.dispatchables)):
            raise TaskConflict('Quality dispatch substitutes independent current release registration')
        for row in (basis, source, batch, release, *dispatchables):
            if self._current.get(row.ref.key()) != row.model_dump(mode='json'):
                raise TaskConflict('Quality dispatch changes current native batch, release or dispatchable projection')
        confirmation = registration.confirmation
        recheck, method, observation = confirmation.recheck, confirmation.method, confirmation.observation_method
        now, at = context.business_time, recheck.authored_at
        schemas = supplier_quality_handoff_schemas()
        timed_evidence = set()

        def evidence_at(refs, point):
            if point.clock_ref != now.clock_ref or point.offset > now.offset:
                raise TaskConflict('Professional dispatch evidence changes its original event clock or time')
            for ref in {ref.key(): ref for ref in refs}.values():
                projection = self._current.get(ref.key())
                if projection is None:
                    raise TaskConflict('Professional dispatch confirmation omits an original evidence source')
                row = EvidenceRecord.model_validate(projection)
                if row.ref != ref or row.effective_window is not None and not row.effective_window.contains(point):
                    raise TaskConflict('Professional dispatch evidence was invalid at its original event time')
                timed_evidence.add(ref.key())

        requirements = {row.ref.key(): row for row in confirmation.requirements}
        original = SupplierQualityBatchView.model_validate(self._originals[saved.action_input.batch_ref.key()])
        true = lambda value: isinstance(value, Known) and value.value is True
        if (len(requirements) != len(confirmation.requirements) or not requirements
                or set(requirements) != {ref.key() for ref in original.requirement_refs}
                or set(requirements) != {ref.key() for ref in recheck.requirement_refs}
                or not set(requirements) <= {ref.key() for ref in method.requirement_refs}
                or not all(true(value) for value in (recheck.supported, recheck.passed, method.supported, observation.supported))
                or recheck.physical_batch_key != batch.physical_batch_key or recheck.method_ref != method.ref
                or method.observation_method_ref != observation.ref or method.requires_actual_evidence is not True
                or recheck.author_action_id not in observation.allowed_author_action_ids
                or recheck.scope_of_release.unit != source.released_quantity.unit
                or decimal_fraction(recheck.scope_of_release.value) < decimal_fraction(source.released_quantity.value)
                or batch.state != 'usable' or batch.known_defect_refs):
            raise TaskConflict('Native dispatch release lacks actual applicable passed recheck or usable batch')
        for requirement in requirements.values():
            if (requirement.batch_ref != original.ref or requirement.product_ref != batch.product_ref
                    or method.ref not in requirement.allowed_method_refs
                    or requirement.external_verification_required and recheck.author_organization_id == batch.organization_id):
                raise TaskConflict('Professional release substitutes original requirement or required independent verifier')
        grant, assignment = confirmation.author_grant, confirmation.author_assignment
        authors = [organization for organization in self.settings.organization_snapshot.organizations
            if organization.organization_id == grant.organization_id and organization.actor_id == grant.actor_id]
        roles = {'SUPPLIER': 'Supplier', 'ENGINEER': 'Engineer', 'ARCHITECT': 'Architect',
            'QS': 'QS', 'GOV': 'Government', 'CONTRACTOR': 'Contractor', 'OWN': 'Owner', 'BANK': 'Bank'}
        if (grant.ref != recheck.author_authority_ref or grant.actor_id != recheck.author_actor_id
                or grant.organization_id != recheck.author_organization_id or grant.function_ref != recheck.author_function_ref
                or recheck.author_action_id not in grant.action_ids or not grant.validity.contains(recheck.authored_at)
                or not any(scope_covers(scope, recheck.scope) for scope in grant.scopes)
                or assignment.function_ref != grant.function_ref or assignment.role != roles.get(recheck.author_action_id.split('-')[0])
                or (method.executor_organization_id, method.executor_actor_id, method.executor_function_ref,
                    method.executor_authority_ref, method.executor_action_id) !=
                    (grant.organization_id, grant.actor_id, grant.function_ref, grant.ref, recheck.author_action_id)
                or grant not in self.settings.organization_snapshot.authorizations
                or len(authors) != 1 or assignment not in authors[0].assignments
                or self._current.get(grant.ref.key()) != grant.model_dump(mode='json')
                or self._current.get(assignment.function_ref.key()) != assignment.model_dump(mode='json')):
            raise TaskConflict('Professional dispatch confirmation changes registered independent author authority')
        for row in (recheck, method, observation, *requirements.values()):
            if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(at)
                    or not scope_covers(row.scope, recheck.scope)):
                raise TaskConflict('Professional dispatch sources lack original effective recheck scope/time')
            if row is not recheck and row.available_at.offset > at.offset:
                raise TaskConflict('Professional dispatch recheck uses a method or requirement received later')
            evidence_at(row.evidence_refs, at)
        if (at.clock_ref != now.clock_ref or not scope_covers(recheck.scope, context.scope)
                or recheck.authored_at.offset > recheck.available_at.offset
                or at.offset > source.available_at.offset or at.offset > release.available_at.offset
                or not recheck.effective_window.contains(recheck.authored_at)
                or not recheck.evidence_refs or not set(recheck.evidence_refs) <= set(source.professional_evidence_refs)):
            raise TaskConflict('Native quality release precedes its professional confirmation or lacks its evidence')
        evidence_at([recheck.scope_of_release.basis_ref], at)
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                evidence_at([ref], at)
            else:
                projection = self._current.get(ref.key())
                if projection is None:
                    raise TaskConflict('Professional dispatch confirmation omits an original typed authority basis')
                schemas.validate_projection(ref, projection)
        resolutions = confirmation.defect_resolutions
        if (len({row.original_defect_ref.key() for row in resolutions}) != len(resolutions)
                or {row.original_defect_ref.key() for row in resolutions} != {ref.key() for ref in original.known_defect_refs}
                or len({row.closed_defect.ref.key() for row in resolutions}) != len(resolutions)):
            raise TaskConflict('Native quality release must preserve and resolve every original visible defect exactly once')
        retained = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        closure_events = {release.core_event_id, batch.core_event_id}
        for resolution in resolutions:
            prior_projection = retained.get(resolution.original_defect_ref.key())
            if prior_projection is None:
                raise TaskConflict('Native defect resolution lacks its original retained A07 observation')
            prior = SupplierVisibleDefectView.model_validate(prior_projection)
            closed = resolution.closed_defect
            if (prior.ref != resolution.original_defect_ref or closed.ref.id != prior.ref.id or closed.ref == prior.ref
                    or prior.batch_ref != original.ref or closed.batch_ref != batch.ref
                    or prior.physical_batch_key != batch.physical_batch_key or closed.physical_batch_key != batch.physical_batch_key
                    or closed.status != 'closed' or closed.scope != prior.scope
                    or closed.observation_ref != prior.observation_ref or closed.requirement_refs != prior.requirement_refs
                    or closed.responsible_organization_id != prior.responsible_organization_id
                    or closed.cost_bearer_id != prior.cost_bearer_id or resolution.recheck_ref != recheck.ref
                    or resolution.core_event_id in closure_events
                    or resolution.closed_at.clock_ref != context.business_time.clock_ref
                    or not recheck.authored_at.offset <= resolution.closed_at.offset <= context.business_time.offset
                    or closed.available_at.clock_ref != context.business_time.clock_ref
                    or not resolution.closed_at.offset <= closed.available_at.offset <= context.business_time.offset
                    or not closed.effective_window.contains(context.business_time)
                    or not closed.effective_window.contains(resolution.closed_at)
                    or not set([*resolution.evidence_refs, *closed.evidence_refs]) <= set(source.professional_evidence_refs)):
                raise TaskConflict('Native defect closure changes lineage, independent recheck, time or original responsibility facts')
            closure_events.add(resolution.core_event_id)
            evidence_at([*resolution.evidence_refs, *closed.evidence_refs], resolution.closed_at)
        if not {ref.key() for ref in source.professional_evidence_refs} <= timed_evidence:
            raise TaskConflict('Professional dispatch evidence lacks an actual declared recheck or closure time')
        expected_native = {'schema_version': 'supplier-native-quality-release-observation.v1', 'run_id': context.run_id,
            'batch': batch.model_dump(mode='json'), 'release': release.model_dump(mode='json'),
            'confirmation': confirmation.model_dump(mode='json')}
        if registration.native_record != expected_native or task_digest(expected_native) != source.native_record_sha256:
            raise TaskConflict('Native quality release substitutes exact professional confirmation content')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**self.logistics.evidence(), 'schema_version': self.VERSION,
            'quality_history_task_sha256': self.settings.quality_history.identity.key,
            'quality_history_journal': str(self.quality.store.path),
            'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
            'limitations': ['Explicit synthetic professional/native release declarations from saved A07.',
                'No inspection, passed result, usable stock or dispatch effect is created.']}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.quality.close()
            finally:
                self.logistics.close()


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = SupplierQualityLogisticsFixtureSettings.model_validate(settings).model_copy(deep=True)
    history = settings.quality_history
    journal = Path(history.source_settings.journal_path).resolve()
    if (offline is not True or settings.action_id != 'SUPPLIER-A08' or history.source_settings.action_id != 'SUPPLIER-A07'
            or history.identity.action_id != 'SUPPLIER-A07' or history.identity.role != 'Supplier'
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.identity.organization_id != settings.source_projection['organization_id']
            or history.identity.organization_id != history.source_settings.source_projection['organization_id']
            or history.identity.request_id != history.request.context.operation_id
            or history.identity.context_sha256 != task_digest(history.request.context.model_dump(mode='json'))
            or history.identity.input_sha256 != task_digest(history.request.action_input)
            or history.request.context.contract_ref.id != 'SUPPLIER-A07'
            or history.request.context.scope != request.context.scope
            or history.request.context.business_time.clock_ref != request.context.business_time.clock_ref
            or history.request.context.business_time.offset > request.context.business_time.offset
            or journal == Path(settings.journal_path).resolve() or not journal.is_file()):
        raise ValueError('Quality dispatch requires original same-run A07 and a separate existing journal')
    logistics = quality = None
    try:
        logistics = build_logistics_sources(request=request, output_directory=output_directory, offline=True,
            settings=settings.model_dump(mode='json', exclude={'quality_history', 'registration'}))
        quality_factory = (build_linked_quality_sources if isinstance(history.source_settings,
            SupplierProductionQualityFixtureSettings) else build_quality_sources)
        quality = quality_factory(request=history.request, output_directory=output_directory, offline=True,
            settings=history.source_settings)
        binding = _QualityDispatchReception(request, settings, logistics, quality)
        return replace(logistics, version=binding.VERSION, quality_worker=binding.worker,
            validate_quality_history=binding.validate_history, validate_quality_dispatch=binding.validate_dispatch,
            read_guard=binding.read_guard, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if quality is not None:
                quality.close()
        finally:
            if logistics is not None:
                logistics.close()
        raise
