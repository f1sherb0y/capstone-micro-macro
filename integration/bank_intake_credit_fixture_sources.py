"""Explicit accepted-intake lineage for the original persistent Bank credit host."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from pydantic import field_validator

from integration.bank_intake_handoff import BankIntakeHandoffBasisView, BankIntakeRecordView
from integration.bank_intake_results import BankIntakeResultWorker
from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class BankIntakeReceptionSettings(StrictRecord):
    identity: TaskIdentity
    basis: BankIntakeHandoffBasisView
    native: BankIntakeRecordView
    native_payload: dict
    relation_payload: dict

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankIntakeCreditFixtureSettings(BankFixtureSourceSettings):
    intake_reception: BankIntakeReceptionSettings


class _IntakeReception:
    VERSION = 'configured-bank-intake-credit-fixture-sources.v1'

    def __init__(self, request, settings, sources):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.sources = sources
        self._configuration_sha256 = task_digest(self.settings.model_dump(mode='json'))
        identity = self.settings.intake_reception.identity
        self.worker = BankIntakeResultWorker(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
            registry=sources.registry, client_version=identity.versions['client'], model_version=identity.versions['model'],
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)

    def _check(self):
        if task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256:
            raise TaskConflict('Bank intake reception declaration changed')
        self.sources.evidence()

    def validate_history(self, saved):
        with self.sources.read_guard(self.request.context):
            self._check()
            reception = self.settings.intake_reception
            basis = reception.basis
            if (saved.identity.as_dict() != reception.identity.as_dict()
                    or saved.current_context != self.request.context
                    or saved.record_sha256 != basis.intake_record_sha256
                    or saved.identity.input_sha256 != basis.intake_input_sha256
                    or saved.identity.context_sha256 != basis.intake_context_sha256
                    or saved.source_reading_sha256 != basis.intake_source_reading_sha256
                    or task_digest(saved.result.model_dump(mode='json')) != basis.intake_result_sha256
                    or task_digest(saved.audit) != basis.intake_audit_sha256
                    or saved.result.kind != 'completed' or saved.result.payload.choice != 'accept_for_review'):
                raise TaskConflict('Bank credit source replaces the selected original accepted intake or private journal lineage')
            return True

    def validate_handoff(self, *, saved, basis, native, application, product, context, reading):
        with self.sources.read_guard(context):
            self._check()
            reception = self.settings.intake_reception
            self.validate_history(saved)
            expected_native = {'schema_version': 'bank-intake-registration.v1',
                'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                'record': native.model_dump(mode='json', exclude={'native_source_sha256', 'native_evidence_ref', 'evidence_refs'}),
                'current_state': 'accepted_for_review'}
            expected_relation = {'schema_version': 'bank-intake-relation.v1',
                'source_identity': saved.identity.as_dict(),
                'basis': basis.model_dump(mode='json', exclude={'evidence_refs', 'relation_evidence_refs'}),
                'current_state': 'active'}
            if (context != self.request.context or basis != reception.basis or native != reception.native
                    or reception.native_payload != expected_native or reception.relation_payload != expected_relation
                    or native.native_source_sha256 != task_digest(reception.native_payload)
                    or basis.native_record_sha256 != task_digest(native.model_dump(mode='json'))
                    or application.ref != native.application_ref or product.ref != native.product_ref):
                raise TaskConflict('Declared native acceptance or independent review-task relation changed')
            for ref, digest in [(native.native_evidence_ref, task_digest(reception.native_payload)),
                    *[(ref, task_digest(reception.relation_payload)) for ref in basis.relation_evidence_refs]]:
                evidence = reading.resolve(ref)
                if (evidence.basis_kind != 'observed' or evidence.source_kind != 'synthetic'
                        or evidence.content_hash != digest):
                    raise TaskConflict('Intake source lacks its independently observed synthetic native and relation records')
            reading.recheck()
            self._check()
            return True

    def evidence(self):
        self._check()
        reception = self.settings.intake_reception
        return {**deepcopy(self.sources.evidence()), 'schema_version': self.VERSION,
            'intake_reception': {'identity': reception.identity.as_dict(),
                'native_payload_sha256': task_digest(reception.native_payload),
                'relation_payload_sha256': task_digest(reception.relation_payload),
                'configuration_sha256': self._configuration_sha256,
                'limitations': ['Explicit synthetic acceptance/relation sources; no native registration or A02 replay.']}}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankIntakeCreditFixtureSettings.model_validate(settings).model_copy(deep=True)
    identity = settings.intake_reception.identity
    if (offline is not True or settings.action_id != 'BANK-A03' or request.context.contract_ref.id != 'BANK-A03'
            or request.context.execution_mode != 'offline_fixture' or identity.action_id != 'BANK-A02'
            or identity.role != 'Bank' or identity.run_id != request.context.run_id
            or identity.organization_id != settings.source_projection['organization_id']
            or not Path(settings.journal_path).is_file()):
        raise ValueError('Credit intake fixture requires an existing same-Bank A02 journal and explicit offline A03 sources')
    sources = build_bank_sources(request=request, output_directory=output_directory, offline=offline,
        settings=BankFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'intake_reception'})))
    try:
        reception = _IntakeReception(request, settings, sources)
        return replace(sources, version=reception.VERSION, intake_worker=reception.worker,
            validate_intake_history=reception.validate_history, validate_intake_handoff=reception.validate_handoff,
            evidence=reception.evidence)
    except Exception:
        sources.close()
        raise
