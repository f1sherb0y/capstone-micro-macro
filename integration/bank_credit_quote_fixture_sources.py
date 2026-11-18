"""Explicit recorded-credit lineage for the original persistent Bank quotation host."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from pydantic import field_validator

from integration.bank_credit_handoff import BankCreditHandoffBasisView
from integration.bank_credit_results import BankCreditResultWorker
from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_quote_objects import QuoteCreditAssessmentView, QuoteRecordedReviewView
from src.actions.contracts.common import StrictRecord
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class BankCreditReceptionSettings(StrictRecord):
    identity: TaskIdentity
    basis: BankCreditHandoffBasisView
    assessment: QuoteCreditAssessmentView
    recorded: QuoteRecordedReviewView
    native_payload: dict
    relation_payload: dict

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankCreditQuoteFixtureSettings(BankFixtureSourceSettings):
    credit_reception: BankCreditReceptionSettings


class _CreditReception:
    VERSION = 'configured-bank-credit-quote-fixture-sources.v1'

    def __init__(self, request, settings, sources):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.sources = sources
        self._configuration_sha256 = task_digest(self.settings.model_dump(mode='json'))
        identity = self.settings.credit_reception.identity
        self.worker = BankCreditResultWorker(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
            registry=sources.registry, client_version=identity.versions['client'], model_version=identity.versions['model'],
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)

    def _check(self):
        if task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256:
            raise TaskConflict('Bank recorded-credit reception declaration changed')
        self.sources.evidence()

    def validate_history(self, saved):
        with self.sources.read_guard(self.request.context):
            self._check()
            reception = self.settings.credit_reception
            basis = reception.basis
            if (saved.identity.as_dict() != reception.identity.as_dict()
                    or saved.current_context != self.request.context
                    or saved.record_sha256 != basis.credit_record_sha256
                    or saved.identity.input_sha256 != basis.credit_input_sha256
                    or saved.identity.context_sha256 != basis.credit_context_sha256
                    or saved.source_reading_sha256 != basis.credit_source_reading_sha256
                    or task_digest(saved.result.model_dump(mode='json')) != basis.credit_result_sha256
                    or task_digest(saved.audit) != basis.credit_audit_sha256
                    or saved.result.kind != 'completed'):
                raise TaskConflict('Bank quote replaces the selected original completed review or private journal lineage')
            return True

    def validate_handoff(self, *, saved, basis, assessment, recorded, context, reading):
        with self.sources.read_guard(context):
            self._check()
            reception = self.settings.credit_reception
            self.validate_history(saved)
            expected_native = {'schema_version': 'bank-credit-registration.v1',
                'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                'native_record_id': basis.native_record_id, 'native_event_id': basis.native_event_id,
                'assessment': assessment.model_dump(mode='json'), 'recorded': recorded.model_dump(mode='json'),
                'current_state': 'recorded'}
            expected_relation = {'schema_version': 'bank-credit-relation.v1',
                'source_identity': saved.identity.as_dict(),
                'basis': basis.model_dump(mode='json', exclude={'evidence_refs', 'relation_evidence_refs'}),
                'current_state': 'active'}
            if (context != self.request.context or basis != reception.basis
                    or assessment != reception.assessment or recorded != reception.recorded
                    or assessment.status != 'recorded' or reception.native_payload != expected_native
                    or reception.relation_payload != expected_relation
                    or basis.native_source_sha256 != task_digest(reception.native_payload)
                    or basis.assessment_sha256 != task_digest(assessment.model_dump(mode='json'))
                    or basis.recorded_decision_sha256 != task_digest(recorded.model_dump(mode='json'))):
                raise TaskConflict('Declared recorded assessment, review source or independent relation changed')
            for ref, digest in [(basis.native_evidence_ref, task_digest(reception.native_payload)),
                    *[(ref, task_digest(reception.relation_payload)) for ref in basis.relation_evidence_refs]]:
                evidence = reading.resolve(ref)
                if (evidence.basis_kind != 'observed' or evidence.source_kind != 'synthetic'
                        or evidence.content_hash != digest):
                    raise TaskConflict('Credit source lacks its independently observed native and relation records')
            reading.recheck()
            self._check()
            return True

    def evidence(self):
        self._check()
        reception = self.settings.credit_reception
        return {**deepcopy(self.sources.evidence()), 'schema_version': self.VERSION,
            'credit_reception': {'identity': reception.identity.as_dict(),
                'native_payload_sha256': task_digest(reception.native_payload),
                'relation_payload_sha256': task_digest(reception.relation_payload),
                'configuration_sha256': self._configuration_sha256,
                'limitations': ['Explicit synthetic recorded review and relation sources; no approval, offer or A03 replay.']}}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankCreditQuoteFixtureSettings.model_validate(settings).model_copy(deep=True)
    identity = settings.credit_reception.identity
    if (offline is not True or settings.action_id != 'BANK-A04' or request.context.contract_ref.id != 'BANK-A04'
            or request.context.execution_mode != 'offline_fixture' or identity.action_id != 'BANK-A03'
            or identity.role != 'Bank' or identity.run_id != request.context.run_id
            or identity.organization_id != settings.source_projection['organization_id']
            or not Path(settings.journal_path).is_file()):
        raise ValueError('Quote credit fixture requires an existing same-Bank A03 journal and explicit offline A04 sources')
    sources = build_bank_sources(request=request, output_directory=output_directory, offline=offline,
        settings=BankFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'credit_reception'})))
    try:
        reception = _CreditReception(request, settings, sources)
        return replace(sources, version=reception.VERSION, credit_worker=reception.worker,
            validate_credit_history=reception.validate_history, validate_credit_handoff=reception.validate_handoff,
            evidence=reception.evidence)
    except Exception:
        sources.close()
        raise
