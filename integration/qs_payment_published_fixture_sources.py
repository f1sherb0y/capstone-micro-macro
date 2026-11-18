"""Read original persisted payment calculations into the original QS action host."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from integration.qs_payment_calculation_fixture_session import QSPaymentCalculationFixtureSettings, build_session
from integration.qs_role_contract_fixture_sources import QSFixtureSourceSettings, build_sources as build_qs_sources
from integration.role_contract_host import RoleContractInvocation
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import Digest


class QSPaymentPublishedFixtureSettings(QSFixtureSourceSettings):
    calculation_request: RoleContractInvocation
    calculation_settings: QSPaymentCalculationFixtureSettings
    calculation_record_sha256: Digest
    calculation_publication_sha256: Digest


class _PublishedPaymentReception:
    VERSION = 'configured-qs-payment-published-fixture-sources.v1'

    def __init__(self, request, settings, sources, session):
        self.request, self.settings = request.model_copy(deep=True), settings.model_copy(deep=True)
        self.sources, self.session = sources, session
        self._configuration_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        self._validate()

    def _validate(self):
        if self._closed or task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256:
            raise TaskConflict('QS payment reading changes its independent original publication configuration')
        self.sources.evidence()
        context = self.request.context
        # Bind the same original method registry content without executing it.
        # This opens the existing publication tables; no new publication occurs.
        publications = self.session._publication_store(self.session.methods)
        with self.session.boundaries.read_guard(context):
            grants = self.session.production.organizations.grants(context, 'QS-A08', 'QS')
            publication = publications.read(context, organization_id=grants[0].organization_id, grants=grants)
            if (publication is None or publication['record_sha256'] != self.settings.calculation_publication_sha256
                    or publication['execution_sha256'] != self.settings.calculation_record_sha256):
                raise TaskConflict('QS payment requires its selected existing original calculation and fresh-token publication')
            projected = self.session.project_published()
            if projected != self.settings.source_projection:
                raise TaskConflict('QS payment source reading replaces original published results or immutable source versions')
            results = [row['value'] for row in publication['objects']]
            if (self.request.action_input['measurement_result_refs'] != [row['ref'] for row in results]
                    or any(row['application_ref'] != self.request.action_input['application_ref']
                        or row['contract_ref'] != self.request.action_input['contract_ref'] for row in results)):
                raise TaskConflict('QS payment input omits or substitutes the complete original saved result bundle')
            return deepcopy(publication)

    def validate_invocation(self, row, prepared):
        with self.sources.read_guard(self.request.context):
            self._validate()
            return self.sources.validators.invocation(row, prepared)

    def validate_wait(self, row, conditions):
        with self.sources.read_guard(self.request.context):
            self._validate()
            return self.sources.validators.wait(row, conditions)

    def validate_recovery(self, row, record, snapshot):
        with self.sources.read_guard(self.request.context):
            self._validate()
            return self.sources.validators.recovery(row, record, snapshot)

    def evidence(self):
        publication = self._validate()
        return {**deepcopy(self.sources.evidence()), 'schema_version': self.VERSION,
            'payment_calculation_input': {'calculation_record_sha256': self.settings.calculation_record_sha256,
                'calculation_publication_sha256': publication['record_sha256'],
                'context_sha256': task_digest(self.request.context.model_dump(mode='json')),
                'measurement_result_refs': deepcopy(self.request.action_input['measurement_result_refs']),
                'configuration_sha256': self._configuration_sha256,
                'limitations': ['Original saved arithmetic only; independent certification power and actual issuance still required.']}}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.sources.close()
            finally:
                self.session.close()


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = QSPaymentPublishedFixtureSettings.model_validate(settings).model_copy(deep=True)
    production = settings.calculation_request
    calculation = settings.calculation_settings
    original_input = production.action_input
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or request.context.contract_ref.id != 'QS-A08'
            or settings.action_id != 'QS-A08' or request.context != calculation.publication_request.context
            or original_input['measurement_result_refs'] or not request.action_input['measurement_result_refs']
            or set(request.action_input) != set(original_input)
            or any(request.action_input[key] != value for key, value in original_input.items() if key != 'measurement_result_refs')
            or settings.organization_snapshot != calculation.publication_sources.organization_snapshot
            or Path(settings.journal_path).resolve() != Path(calculation.production_sources.journal_path).resolve()
            or not Path(settings.journal_path).is_file()):
        raise ValueError('QS published payment requires original same-journal source input, full saved results and unchanged publication authority')
    sources = session = None
    try:
        session = build_session(request=production, settings=calculation, output_directory=output_directory, offline=True)
        excluded = {'calculation_request', 'calculation_settings', 'calculation_record_sha256', 'calculation_publication_sha256'}
        sources = build_qs_sources(request=request, settings=QSFixtureSourceSettings.model_validate(
            settings.model_dump(mode='json', exclude=excluded)), output_directory=output_directory, offline=True)
        binding = _PublishedPaymentReception(request, settings, sources, session)
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
