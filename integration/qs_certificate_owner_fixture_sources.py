"""Independently issued QS certificates received with complete native Owner mappings."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings, build_sources as build_owner_sources
from integration.qs_payment_actions import QSPaymentActionAssembler
from integration.qs_payment_results import QSPaymentResultWorker
from integration.qs_role_contract_fixture_sources import QSFixtureSourceSettings, build_sources as build_qs_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentCertificateReceiptView, OwnerPaymentComponentView, OwnerPaymentObligationView,
)
from src.actions.contracts.qs_payment_objects import QSPaymentCertificateView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class QSPaymentHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: QSFixtureSourceSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: Literal['offline-fixture-no-model.v1']

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredQSCertificateRegistration(StrictRecord):
    schema_version: Literal['qs-certificate-owner-registration.v1']
    registration_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    receipt: OwnerPaymentCertificateReceiptView
    sharing_authorized: bool
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    issuance_coverage: Literal['complete']
    issuance_history: Annotated[list[QSPaymentCertificateView], Field(min_length=1)]
    native_issuance: dict

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class OwnerSettlementSnapshot(StrictRecord):
    ref: Reference
    value: dict


class DeclaredOwnerCertificateMapping(StrictRecord):
    schema_version: Literal['qs-certificate-owner-mapping.v1']
    run_id: TextId
    recipient_organization_id: TextId
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    receipt_refs: Annotated[list[ref_type('PaymentCertificateReceipt')], Field(min_length=1)]
    obligations: Annotated[list[OwnerPaymentObligationView], Field(min_length=1)]
    components: Annotated[list[OwnerPaymentComponentView], Field(min_length=1)]
    settlement_sources: list[OwnerSettlementSnapshot]
    native_evidence_ref: ref_type('Evidence')
    native_mapping: dict
    coverage: Literal['complete']


class OwnerQSCertificateFixtureSettings(OwnerFixtureSourceSettings):
    histories: Annotated[list[QSPaymentHistorySettings], Field(min_length=1)]
    registrations: Annotated[list[DeclaredQSCertificateRegistration], Field(min_length=1)]
    mapping: DeclaredOwnerCertificateMapping


class _CertificateReception:
    VERSION = 'configured-owner-qs-certificate-fixture-sources.v1'

    def __init__(self, request, settings, owner, sources):
        self.request, self.settings = request.model_copy(deep=True), settings.model_copy(deep=True)
        self.owner, self.sources, self._closed = owner, sources, False
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self.histories = {row.identity.key: row for row in self.settings.histories}
        self.registrations = {row.source_identity.key: row for row in self.settings.registrations}
        self.workers, self.assemblers = {}, {}
        for key, history in self.histories.items():
            source = self.sources[key]
            self.workers[key] = QSPaymentResultWorker(store=source.store, snapshots=InvocationSnapshotStore(source.store),
                registry=source.registry, client_version=history.client_version, model_version=history.model_version,
                validate_invocation=source.validators.invocation, validate_wait=source.validators.wait,
                validate_recovery=source.validators.recovery)
            self.assemblers[key] = QSPaymentActionAssembler(registry=source.registry, organizations=source.organizations,
                provider=source.provider, macro_version=history.macro_version, source_mode='fixture', methods=source.methods,
                policy_version=history.policy_version, model_version=history.model_version)

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256):
            raise TaskConflict('Certificate reception changed current Owner configuration or independent registration')
        self.owner.evidence()
        for source in self.sources.values():
            source.evidence()

    def _validate_history(self, saved, reading, key):
        history, registration = self.histories[key], self.registrations[key]
        shared = [ref.key() for ref in registration.shared_source_refs]
        if (saved.identity.as_dict() != history.identity.as_dict() or saved.current_context != history.request.context
                or saved.action_input.model_dump(mode='json') != history.request.action_input
                or saved.record_sha256 != registration.source_record_sha256
                or saved.source_reading_sha256 != registration.source_reading_sha256
                or task_digest(saved.result.model_dump(mode='json')) != registration.source_result_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice not in {'certify', 'correct_certificate'}
                or not registration.sharing_authorized or len(set(shared)) != len(shared)
                or set(shared) != {Reference.model_validate(row['ref']).key() for row in saved.source_reading}):
            raise TaskConflict('Certificate sharing changes original QS decision, complete sources or disclosure permission')
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original QS certificate sources differ from current authorized history')
        reading.recheck()
        return True

    def read_qs_payment(self, *, context, source_task_sha256):
        self._check(context)
        if source_task_sha256 not in self.histories:
            raise TaskConflict('Certificate reader requires explicitly selected original QS history')
        history, source = self.histories[source_task_sha256], self.sources[source_task_sha256]
        with self.owner.read_guard(context), source.read_guard(history.request.context):
            prepared = self.assemblers[source_task_sha256].build(history.request.context, **history.request.action_input)
            try:
                versions = prepared_action_execution_versions(prepared,
                    client_version=history.client_version, model_version=history.model_version)
                return self.workers[source_task_sha256].read_completed(history.identity,
                    current_context=history.request.context, reading=prepared.reading, execution_versions=versions,
                    validate_current=lambda saved: self._validate_history(saved, prepared.reading, source_task_sha256))
            finally:
                prepared.reading.recheck()
                self._check(context)

    @staticmethod
    def _observed(rows, ref, payload):
        evidence = rows.get(ref.key())
        if (not isinstance(evidence, dict) or evidence.get('source_kind') != 'synthetic'
                or evidence.get('basis_kind') != 'observed' or evidence.get('content_hash') != task_digest(payload)):
            raise TaskConflict('Certificate reception lacks independently observed complete native evidence')

    def _validate_group(self, saved_decisions, receipts, obligations, components, context):
        self._check(context)
        mapping = self.settings.mapping
        rows = {Reference.model_validate(row['ref']).key(): row['value'] for row in self.settings.source_projection['objects']}
        if (mapping.run_id != context.run_id or mapping.recipient_organization_id != self.settings.source_projection['organization_id']
                or mapping.recipient_actor_id != context.actor_id or mapping.recipient_function_ref != context.function_ref
                or mapping.recipient_authorization_refs != context.authorization_refs
                or [receipt.ref for receipt in receipts] != mapping.receipt_refs
                or len(saved_decisions) != len(self.registrations)
                or {saved.identity.key for saved in saved_decisions} != set(self.registrations)
                or {row.ref.key(): row for row in obligations} != {row.ref.key(): row for row in mapping.obligations}
                or {row.ref.key(): row for row in components} != {row.ref.key(): row for row in mapping.components}):
            raise TaskConflict('Certificate mapping omits or substitutes complete native sources or receiver authority')
        for saved, receipt in zip(saved_decisions, receipts):
            registration = self.registrations[saved.identity.key]
            if saved != self.read_qs_payment(context=context, source_task_sha256=saved.identity.key) or receipt != registration.receipt:
                raise TaskConflict('Certificate reception changes original selected journal or issued receipt')
            history = {row.ref.key(): row for row in registration.issuance_history}
            certificate = receipt.certificate
            if (len(history) != len(registration.issuance_history) or history.get(certificate.ref.key()) != certificate
                    or certificate.status != 'active'
                    or any(row.contract_ref != certificate.contract_ref for row in history.values())
                    or len({(row.certificate_key, row.sequence) for row in history.values()}) != len(history)):
                raise TaskConflict('Independent issuance history repeats or substitutes original active certificate')
            for row in history.values():
                if row.predecessor_ref is not None:
                    prior = history.get(row.predecessor_ref.key())
                    if (prior is None or prior.status != 'superseded' or prior.certificate_key != row.certificate_key
                            or prior.sequence >= row.sequence):
                        raise TaskConflict('Certificate correction omits or changes independently superseded predecessor')
            if sum(row.status == 'active' and row.certificate_key == certificate.certificate_key
                    for row in history.values()) != 1:
                raise TaskConflict('Native issuance history contains competing active certificate versions')
            issuance = {'schema_version': 'qs-certificate-native-issuance.v1', 'source_identity': saved.identity.as_dict(),
                'source_record_sha256': saved.record_sha256, 'source_result_sha256': registration.source_result_sha256,
                'source_reading_sha256': saved.source_reading_sha256, 'statement': saved.result.payload.statement.model_dump(mode='json'),
                'certificate': certificate.model_dump(mode='json'),
                'issuance_history': [row.model_dump(mode='json') for row in registration.issuance_history], 'coverage': 'complete'}
            # The receipt carries this digest; exclude that carrier field so
            # independent declarations can be hashed without a circular hash.
            registration_payload = registration.model_dump(mode='json', exclude={'receipt': {'native_record_sha256'}})
            if registration.native_issuance != issuance or receipt.native_record_sha256 != task_digest(registration_payload):
                raise TaskConflict('Independent certificate issuance changes original statement or full correction lineage')
            self._observed(rows, receipt.native_evidence_ref, registration_payload)
        for row in [*mapping.obligations, *mapping.components]:
            if rows.get(row.ref.key()) != row.model_dump(mode='json') or row.as_of != context.business_time:
                raise TaskConflict('Native mapping changes original current due, paid cash or noncash offset source')
        native_sources = {row.ref.key(): row.value for row in mapping.settlement_sources}
        if (len(native_sources) != len(mapping.settlement_sources)
                or any(rows.get(key) != value for key, value in native_sources.items())
                or any(row.source_ref.key() not in native_sources for row in mapping.obligations)
                or any(row.source_ref.key() not in native_sources for row in mapping.components)):
            raise TaskConflict('Certificate cash/offset history lacks its complete independently supplied financial sources')
        owner_fields = {'Account': 'organization_id', 'FundingSource': 'organization_id',
            'CashReservation': 'organization_id', 'Debt': 'borrower_id', 'PaymentExecution': 'organization_id'}
        for row in mapping.settlement_sources:
            if row.value.get('ref') != row.ref.model_dump(mode='json'):
                raise TaskConflict('Native financial snapshot changes its declared source identity')
            if row.ref.kind == 'PaymentReceipt':
                execution_ref = Reference.model_validate(row.value['execution_ref'])
                execution = native_sources.get(execution_ref.key())
                if (execution is None or execution.get('organization_id') != mapping.recipient_organization_id
                        or any(row.value[k] != execution[k] for k in ('command_id', 'business_key', 'amount', 'beneficiary_id', 'status'))):
                    raise TaskConflict('Native cash receipt borrows another Owner command or settlement identity')
            elif (row.ref.kind not in owner_fields
                    or row.value.get(owner_fields[row.ref.kind]) != mapping.recipient_organization_id):
                raise TaskConflict('Native financial history substitutes another Owner or source kind')
            if 'as_of' in row.value and row.value['as_of'] != context.business_time:
                raise TaskConflict('Native financial snapshot is not current at certificate reception')
            if row.ref.kind == 'FundingSource':
                account_ref = Reference.model_validate(row.value['account_ref'])
                if account_ref.kind != 'Account' or account_ref.key() not in native_sources:
                    raise TaskConflict('Certificate funding source omits its independently observed actual account')
        expected = {'schema_version': 'qs-certificate-native-owner-mapping.v1',
            'current_context': context.model_dump(mode='json'), 'current_input': deepcopy(self.request.action_input),
            'registrations': [row.model_dump(mode='json') for row in self.settings.registrations],
            'receipt_refs': [row.model_dump(mode='json') for row in mapping.receipt_refs],
            'obligations': [row.model_dump(mode='json') for row in mapping.obligations],
            'components': [row.model_dump(mode='json') for row in mapping.components],
            'settlement_sources': [row.model_dump(mode='json') for row in mapping.settlement_sources], 'coverage': 'complete'}
        if mapping.native_mapping != expected:
            raise TaskConflict('Independent Owner mapping changes full certificate allocation or cash/offset history')
        self._observed(rows, mapping.native_evidence_ref, expected)
        self._check(context)
        return True

    def validate_reception(self, *, saved, receipt, certificate, obligation, context):
        with self.owner.read_guard(context):
            mapping = self.settings.mapping
            if certificate != receipt.certificate or len(mapping.obligations) != 1 or len(self.registrations) != 1:
                raise TaskConflict('Single certificate reception requires the complete single-obligation group')
            components = mapping.components
            if {row.ref for row in components} != set(obligation.component_refs):
                raise TaskConflict('Single certificate mapping omits original obligation components')
            for original, field in ((obligation.actual_due, 'actual_due'),
                    (obligation.actual_paid, 'actual_cash_paid'), (obligation.actual_offset, 'actual_offset')):
                if (original.state != 'known' or any(getattr(row, field).state != 'known'
                        or getattr(row, field).value.currency != original.value.currency for row in components)
                        or sum((Fraction(getattr(row, field).value.value) for row in components), Fraction()) != Fraction(original.value.value)):
                    raise TaskConflict('Single certificate components change separate due, paid cash or noncash offset totals')
            return self._validate_group([saved], [receipt], [obligation], components, context)

    def validate_mapping(self, *, saved_decisions, receipts, obligations, components, context):
        with self.owner.read_guard(context):
            return self._validate_group(saved_decisions, receipts, obligations, components, context)

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.owner.evidence()), 'schema_version': self.VERSION,
            'certificate_reception': {'configuration_sha256': self._settings_sha256,
                'qs_sources': {key: deepcopy(source.evidence()) for key, source in self.sources.items()},
                'native_mapping_sha256': task_digest(self.settings.mapping.native_mapping),
                'limitations': ['Independent synthetic issued certificates and complete native allocation/cash history; no generated debt or payment.']}}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                for source in self.sources.values():
                    source.close()
            finally:
                self.owner.close()


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = OwnerQSCertificateFixtureSettings.model_validate(settings).model_copy(deep=True)
    histories = {row.identity.key: row for row in settings.histories}
    registrations = {row.source_identity.key: row for row in settings.registrations}
    owner_path = Path(settings.journal_path).resolve()
    mapping = settings.mapping
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.context.contract_ref.id != 'OWN-A06' or settings.action_id != 'OWN-A06'
            or len(histories) != len(settings.histories) or len(registrations) != len(settings.registrations)
            or set(histories) != set(registrations) or not owner_path.is_file()
            or len({row.ref.key() for row in mapping.obligations}) != len(mapping.obligations)
            or len({row.ref.key() for row in mapping.components}) != len(mapping.components)
            or mapping.receipt_refs != [row.receipt.ref for row in settings.registrations]
            or len(set(mapping.receipt_refs)) != len(mapping.receipt_refs)):
        raise ValueError('Certificate reception requires complete original QS selections and an existing separate Owner journal')
    for key, history in histories.items():
        path = Path(history.source_settings.journal_path).resolve()
        registration = registrations[key]
        if (history.identity.run_id != request.context.run_id or history.identity.role != 'QS'
                or history.identity.action_id != 'QS-A08' or history.request.context.contract_ref.id != 'QS-A08'
                or history.source_settings.action_id != 'QS-A08' or history.request.context.run_id != request.context.run_id
                or history.request.context.execution_mode != 'offline_fixture'
                or history.request.context.business_time != request.context.business_time
                or history.identity.versions['client'] != history.client_version
                or history.identity.versions['model'] != history.model_version
                or not registration.sharing_authorized or registration.receipt.run_id != request.context.run_id
                or path == owner_path or not path.is_file()):
            raise ValueError('Certificate reception requires original QS authority, all execution versions and independent existing journal')
    owner, sources = None, {}
    try:
        owner = build_owner_sources(request=request, output_directory=output_directory, offline=offline,
            settings=OwnerFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'histories', 'registrations', 'mapping'})))
        for key, history in histories.items():
            sources[key] = build_qs_sources(request=history.request, output_directory=output_directory,
                offline=offline, settings=history.source_settings)
        binding = _CertificateReception(request, settings, owner, sources)
        return replace(owner, version=binding.VERSION, read_qs_payment=binding.read_qs_payment,
            validate_payment_certificate_reception=binding.validate_reception,
            validate_payment_certificate_mapping=binding.validate_mapping, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            for source in sources.values():
                source.close()
        finally:
            if owner is not None:
                owner.close()
        raise
