"""Independent certification basis received after original immutable QS valuation."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import field_validator

from integration.qs_payment_actions import QSPaymentActionAssembler
from integration.qs_payment_published_fixture_sources import QSPaymentPublishedFixtureSettings, _PublishedPaymentReception
from integration.qs_payment_calculation_fixture_session import build_session
from integration.qs_payment_results import QSPaymentResultWorker
from integration.qs_role_contract_fixture_sources import QSFixtureSourceSettings, build_sources as build_qs_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.qs_payment_objects import QSPaymentAuthorityView, QSPaymentCertificationView, QSPaymentCorrectionView
from src.actions.roles.qs_change import content_digest
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class IndependentQSCertificationReception(StrictRecord):
    schema_version: Literal['qs-independent-certification-reception.v1']
    verify_identity: TaskIdentity
    verify_record_sha256: Digest
    verify_result_sha256: Digest
    verify_reading_sha256: Digest
    basis: QSPaymentCertificationView | QSPaymentCorrectionView
    authority: QSPaymentAuthorityView
    received_at: TimePoint
    native_evidence_ref: ref_type('Evidence')
    native_payload: dict

    @field_validator('verify_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class QSPaymentCertificationFixtureSettings(QSPaymentPublishedFixtureSettings):
    current_policy_version: TextId
    certification_reception: IndependentQSCertificationReception


class _CertificationReception(_PublishedPaymentReception):
    VERSION = 'configured-qs-payment-certification-fixture-sources.v1'

    def __init__(self, request, settings, sources, session):
        identity = settings.certification_reception.verify_identity
        self.worker = QSPaymentResultWorker(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
            registry=sources.registry, client_version=identity.versions['client'], model_version=identity.versions['model'],
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)
        self.assembler = QSPaymentActionAssembler(registry=sources.registry, organizations=sources.organizations,
            provider=sources.provider, macro_version=settings.source_projection['macro_version'], source_mode='fixture',
            methods=session.methods, policy_version=settings.current_policy_version, model_version='offline-fixture-no-model.v1')
        super().__init__(request, settings, sources, session)

    def _validate_verify(self, saved, reading):
        declared = self.settings.certification_reception
        if (saved.identity.as_dict() != declared.verify_identity.as_dict()
                or saved.record_sha256 != declared.verify_record_sha256
                or saved.source_reading_sha256 != declared.verify_reading_sha256
                or task_digest(saved.result.model_dump(mode='json')) != declared.verify_result_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'verify'
                or saved.result.payload.statement.source_application_ref != declared.basis.application_ref
                or content_digest(saved.result.payload.statement) != declared.basis.statement_sha256):
            raise TaskConflict('Independent certification replaces original verified QS statement, task or source history')
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Certification changes an original source version of its verified valuation')
        reading.recheck()
        return True

    def _validate(self):
        if self._closed or task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256:
            raise TaskConflict('Independent certification reception configuration changed')
        self.sources.evidence()
        context = self.request.context
        original_context = self.settings.calculation_settings.publication_request.context
        publications = self.session._publication_store(self.session.methods)
        with self.sources.read_guard(context), self.session.boundaries.read_guard(original_context):
            grants = self.session.production.organizations.grants(original_context, 'QS-A08', 'QS')
            publication = publications.read(original_context, organization_id=grants[0].organization_id, grants=grants)
            if (publication is None or publication['record_sha256'] != self.settings.calculation_publication_sha256
                    or publication['execution_sha256'] != self.settings.calculation_record_sha256):
                raise TaskConflict('Certification requires the selected existing original calculation and publication')
            original = self.session.project_published()
            rows = {Reference.model_validate(row['ref']).key(): row['value'] for row in self.settings.source_projection['objects']}
            if (len(rows) != len(self.settings.source_projection['objects'])
                    or any(rows.get(Reference.model_validate(row['ref']).key()) != row['value'] for row in original['objects'])
                    or self.request.action_input['measurement_result_refs'] != [row['ref'] for row in publication['objects']]):
                raise TaskConflict('Certification replaces complete immutable valuation sources or saved result bundle')
            prepared = self.assembler.build(context, **self.request.action_input)
            try:
                declared = self.settings.certification_reception
                identity = declared.verify_identity
                saved = self.worker.read_completed(identity, current_context=context, reading=prepared.reading,
                    execution_versions=identity.versions,
                    validate_current=lambda saved: self._validate_verify(saved, prepared.reading))
                basis, power = declared.basis, declared.authority
                purpose = 'correct' if isinstance(basis, QSPaymentCorrectionView) else 'certify'
                application = rows[Reference.model_validate(self.request.action_input['application_ref']).key()]
                expected_ref = application['correction_basis_ref' if purpose == 'correct' else 'certification_basis_ref']
                if (rows.get(basis.ref.key()) != basis.model_dump(mode='json')
                        or rows.get(power.ref.key()) != power.model_dump(mode='json')
                        or expected_ref != basis.ref.model_dump(mode='json')
                        or power.ref != basis.authority_ref
                        or self.request.action_input['certification_authority_ref'] != power.ref.model_dump(mode='json')
                        or power.contract_ref != basis.contract_ref or power.application_ref not in (None, basis.application_ref)
                        or basis.contract_ref != saved.action_input.contract_ref or basis.application_ref != saved.action_input.application_ref
                        or basis.actor_id != context.actor_id or basis.function_ref != context.function_ref
                        or power.actor_id != context.actor_id or power.function_ref != context.function_ref
                        or purpose not in power.purposes or power.certificate_key != basis.certificate_key
                        or not basis.effective_window.contains(context.business_time)
                        or not power.effective_window.contains(context.business_time)
                        or declared.native_evidence_ref not in basis.evidence_refs
                        or declared.native_evidence_ref not in power.evidence_refs):
                    raise TaskConflict('Independent basis changes original application, acting QS, certificate key or actual power')
                points = [saved.context.business_time, basis.authored_at, basis.available_at, declared.received_at, context.business_time]
                if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                        or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                        or power.available_at.clock_ref != context.business_time.clock_ref
                        or power.available_at.offset > declared.received_at.offset):
                    raise TaskConflict('Independent certification basis changes original verification or reception chronology')
                native = {'schema_version': 'qs-independent-certification-native.v1',
                    'verify_identity': saved.identity.as_dict(), 'verify_record_sha256': saved.record_sha256,
                    'verify_result_sha256': declared.verify_result_sha256, 'verify_reading_sha256': saved.source_reading_sha256,
                    'statement': saved.result.payload.statement.model_dump(mode='json'),
                    'basis': basis.model_dump(mode='json'), 'authority': power.model_dump(mode='json'),
                    'received_at': declared.received_at.model_dump(mode='json'),
                    'current_context': context.model_dump(mode='json'), 'current_input': deepcopy(self.request.action_input)}
                observed = rows.get(declared.native_evidence_ref.key())
                if (declared.native_payload != native or not isinstance(observed, dict)
                        or observed.get('source_kind') != 'synthetic' or observed.get('basis_kind') != 'observed'
                        or observed.get('content_hash') != task_digest(native)):
                    raise TaskConflict('Certification reception lacks independently observed complete native basis/power relation')
                prepared.reading.recheck()
                return deepcopy(publication)
            finally:
                prepared.reading.recheck()

    def evidence(self):
        evidence = super().evidence()
        evidence['payment_calculation_input']['limitations'] = [
            'Original saved arithmetic and independently received certification power; native certificate issuance remains separate.']
        declared = self.settings.certification_reception
        evidence['independent_certification_input'] = {
            'verify_identity': declared.verify_identity.as_dict(), 'verify_record_sha256': declared.verify_record_sha256,
            'verify_result_sha256': declared.verify_result_sha256, 'verify_reading_sha256': declared.verify_reading_sha256,
            'basis_ref': declared.basis.ref.model_dump(mode='json'), 'authority_ref': declared.authority.ref.model_dump(mode='json'),
            'native_payload_sha256': task_digest(declared.native_payload),
            'limitations': ['Independent received authority only; actual certificate issuance remains a separate native operation.']}
        return evidence


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = QSPaymentCertificationFixtureSettings.model_validate(settings).model_copy(deep=True)
    calculation = settings.calculation_settings
    original = settings.calculation_request.action_input
    context, previous = request.context, calculation.publication_request.context
    identity = settings.certification_reception.verify_identity
    if (offline is not True or request.execution_path != 'deterministic' or context.execution_mode != 'offline_fixture'
            or context.contract_ref.id != 'QS-A08' or settings.action_id != 'QS-A08'
            or context.read_token == previous.read_token or context.operation_id == previous.operation_id
            or any(getattr(context, name) != getattr(previous, name) for name in
                ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
            or set(request.action_input) != set(original)
            or any(request.action_input[key] != value for key, value in original.items()
                if key not in {'measurement_result_refs', 'certification_authority_ref'})
            or not request.action_input['measurement_result_refs'] or request.action_input['certification_authority_ref'] is None
            or not all(ref in context.authorization_refs for ref in previous.authorization_refs)
            or identity.run_id != context.run_id or identity.organization_id != settings.source_projection['organization_id']
            or identity.role != 'QS' or identity.action_id != 'QS-A08' or identity.request_id == context.operation_id
            or identity.versions['model'] != 'offline-fixture-no-model.v1'
            or Path(settings.journal_path).resolve() != Path(calculation.production_sources.journal_path).resolve()
            or not Path(settings.journal_path).is_file()):
        raise ValueError('Certification requires same original valuation/time/actor and independent current basis/token/task')
    original_grants = calculation.publication_sources.organization_snapshot.authorizations
    current_grants = {grant.ref.key(): grant for grant in settings.organization_snapshot.authorizations}
    if (any(current_grants.get(grant.ref.key()) != grant for grant in original_grants)
            or any(ref in settings.organization_snapshot.inactive_authorization_refs for ref in previous.authorization_refs)):
        raise ValueError('Independent certification cannot replace or revoke original valuation source authority')
    sources = session = None
    try:
        session = build_session(request=settings.calculation_request, settings=calculation, output_directory=output_directory, offline=True)
        excluded = {'calculation_request', 'calculation_settings', 'calculation_record_sha256', 'calculation_publication_sha256',
            'current_policy_version', 'certification_reception'}
        sources = build_qs_sources(request=request, settings=QSFixtureSourceSettings.model_validate(
            settings.model_dump(mode='json', exclude=excluded)), output_directory=output_directory, offline=True)
        binding = _CertificationReception(request, settings, sources, session)
        return replace(sources, version=binding.VERSION, methods=session.methods,
            validators=type(sources.validators)(invocation=binding.validate_invocation,
                wait=binding.validate_wait, recovery=binding.validate_recovery), evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if sources is not None:
                sources.close()
        finally:
            if session is not None:
                session.close()
        raise
