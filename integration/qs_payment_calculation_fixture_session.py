"""Explicit offline QS payment calculation persistence and fresh-token publication."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path

from integration.qs_payment_actions import QSPaymentActionAssembler
from integration.qs_payment_calculation_publication import (
    QSPaymentCalculationPublicationStore, QSPaymentCalculationPublishedViewProvider,
)
from integration.qs_payment_calculation_validation import QSPaymentCalculationSourceValidator
from integration.qs_payment_calculations import prepare_qs_payment_calculations
from integration.qs_role_contract_fixture_sources import QSFixtureSourceSettings, build_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, canonical, task_digest
from src.methods.qs_payment import register_qs_payment_method
from src.methods.registry import MethodRegistry


class QSPaymentCalculationFixtureSettings(StrictRecord):
    production_sources: QSFixtureSourceSettings
    publication_request: RoleContractInvocation
    publication_sources: QSFixtureSourceSettings
    author_authority_ref: ref_type('Authorization')
    policy_version: TextId


class _ReadBoundaries:
    """Choose one of two fixed original source guards; no mutable token switch."""

    def __init__(self, production, publication, source_request, publication_request):
        self.production, self.publication = production, publication
        self.source_context = source_request.context.model_copy(deep=True)
        self.publication_context = publication_request.context.model_copy(deep=True)

    def _source(self, context):
        if context == self.source_context:
            return self.production
        if context == self.publication_context:
            return self.publication
        raise TaskConflict('Payment calculation requires one of its original two authorized read boundaries')

    @contextmanager
    def read_guard(self, context):
        self._source(context)
        # Hold both immutable source guards throughout save and publication.
        with self.production.read_guard(self.source_context), self.publication.read_guard(self.publication_context):
            yield

    def project(self, *, context, organization_id, grants):
        with self.read_guard(context):
            return self._source(context).provider.project(context=context,
                organization_id=organization_id, grants=grants)


class QSPaymentCalculationFixtureSession:
    VERSION = 'qs-payment-calculation-fixture-session.v1'

    def __init__(self, request, settings, production, publication):
        self.request, self.settings = request.model_copy(deep=True), settings.model_copy(deep=True)
        self.production, self.publication = production, publication
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._request_sha256 = task_digest(self.request.model_dump(mode='json'))
        self.boundaries = _ReadBoundaries(production, publication, request, settings.publication_request)
        registry = MethodRegistry()
        register_qs_payment_method(registry)
        self.methods = registry.snapshot()
        macro_version = settings.production_sources.source_projection['macro_version']
        self.validator = QSPaymentCalculationSourceValidator(registry=production.registry,
            organizations=production.organizations, provider=self.boundaries,
            macro_version=macro_version, source_mode='fixture')
        self.assembler = QSPaymentActionAssembler(registry=production.registry, organizations=production.organizations,
            provider=self.boundaries, macro_version=macro_version, source_mode='fixture', methods=self.methods,
            policy_version=settings.policy_version, model_version='offline-fixture-no-model.v1')
        self.publications = None
        self.provider = None
        self._closed, self._started = False, False

    def _check(self):
        if (self._closed or task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256
                or task_digest(self.request.model_dump(mode='json')) != self._request_sha256):
            raise TaskConflict('Payment calculation session changes its explicit current input or source configuration')
        self.production.evidence()
        self.publication.evidence()

    def _publication_store(self, methods):
        if self.publications is None:
            self.publications = QSPaymentCalculationPublicationStore(store=self.production.store,
                registry=self.production.registry, methods=methods, organizations=self.production.organizations,
                validate_source=self.validator.validate_source)
            self.provider = QSPaymentCalculationPublishedViewProvider(provider=self.boundaries, publications=self.publications)
        elif self.publications.methods is not methods:
            raise TaskConflict('Payment calculation persistence changes its actual original reading method registry')
        return self.publications

    def calculate_and_publish(self):
        """One explicit arithmetic execution; save before exposing new-token results."""
        self._check()
        if self._started:
            raise TaskConflict('Calculation was already attempted; use explicit saved publication or review the incomplete attempt')
        self._started = True
        with self.boundaries.read_guard(self.request.context):
            prepared = self.assembler.build(self.request.context, **self.request.action_input)
            publications = self._publication_store(prepared.runner.methods)
            # Do not repeat an already persisted target bundle on a new session.
            # The original arithmetic preparation declares those target refs;
            # this check neither invokes its registered method nor derives work.
            from src.actions.roles.qs_payment import prepare_payment_arithmetic
            arithmetic = prepare_payment_arithmetic(prepared.context, prepared.action_input, prepared.reading)
            if arithmetic['kind'] != 'prepared':
                return arithmetic
            targets = [task_digest([prepared.context.run_id, 'QS-A08', ref.model_dump(mode='json')])
                for ref in arithmetic['result_refs'].values()]
            with self.production.store._lock:
                if any(self.production.store._db.execute(
                        'SELECT execution_sha256 FROM qs_payment_calculation_targets WHERE ref_key=?', (key,)).fetchone()
                        is not None for key in targets):
                    raise TaskConflict('Original calculation target is already saved; explicitly publish its saved execution')
            attempts = ['qs_payment_calculation_attempt:' + key for key in targets]
            attempt = {'schema_version': 'qs-payment-calculation-attempt.v1', 'status': 'method_attempted',
                'context_sha256': prepared.context_sha256, 'input_sha256': prepared.input_sha256,
                'method_registry_sha256': prepared.runner.methods.content_digest, 'target_keys': targets}
            # Persist all target claims atomically before the method call. An
            # interrupted calculation cannot be repeated by opening a session.
            with self.production.store._transaction():
                if any(self.production.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
                        is not None for key in attempts):
                    raise TaskConflict('Original calculation already attempted; select its saved execution or explicitly review missing output')
                for key in attempts:
                    self.production.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(attempt)))
            calculated = prepare_qs_payment_calculations(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, author_authority_ref=self.settings.author_authority_ref,
                validate_current=self.validator.validate_current)
            if calculated['kind'] != 'prepared':
                return calculated
            record = publications.save(calculated, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            with self.production.store._transaction():
                for key in attempts:
                    previous = self.production.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
                    if previous is None or json.loads(previous[0]) != attempt:
                        raise TaskConflict('Original payment calculation attempt changed before its saved-result acknowledgement')
                    self.production.store._db.execute('UPDATE metadata SET value=? WHERE key=?',
                        (canonical({**attempt, 'status': 'saved', 'record_sha256': record['record_sha256']}), key))
            published = publications.publish(record['record_sha256'], source_context=prepared.context,
                next_context=self.settings.publication_request.context)
            self._check()
            return {'kind': 'prepared', 'record': record, 'publication': published,
                'limitations': ['Original method results only; certificate issuance and payment remain independent.']}

    def publish_saved(self, record_sha256):
        """Select an original saved execution and publish it without a method call."""
        self._check()
        with self.boundaries.read_guard(self.request.context):
            methods = self.publications.methods if self.publications is not None else self.methods
            publications = self._publication_store(methods)
            with self.production.store._lock:
                raw = self.production.store._db.execute(
                    'SELECT record FROM qs_payment_calculation_records WHERE record_sha256=?', (record_sha256,)).fetchone()
            if raw is None:
                raise TaskConflict('Saved publication requires the selected existing original payment calculation')
            record = json.loads(raw[0])
            if (record['context'] != self.request.context.model_dump(mode='json')
                    or record['action_input'] != self.request.action_input
                    or any(row['author_authority_ref'] != self.settings.author_authority_ref.model_dump(mode='json')
                        for row in record['prepared']['projections'])):
                raise TaskConflict('Saved payment publication changes original input, read boundary or author')
            publication = publications.publish(record_sha256, source_context=self.request.context,
                next_context=self.settings.publication_request.context)
            self._started = True
            self._check()
            return {'kind': 'prepared', 'record': deepcopy(record), 'publication': publication, 'method_calls': 0}

    def project_published(self):
        """Read the original saved bundle at its separately supplied fresh token."""
        self._check()
        if self.provider is None:
            raise TaskConflict('Payment result reading requires an explicit completed save/publication selection')
        context = self.settings.publication_request.context
        with self.boundaries.read_guard(context):
            grants = self.production.organizations.grants(context, 'QS-A08', 'QS')
            if self.publications.read(context, organization_id=grants[0].organization_id, grants=grants) is None:
                raise TaskConflict('Fresh-token payment result reading has no original completed publication')
            projection = self.provider.project(context=context, organization_id=grants[0].organization_id, grants=grants)
            self._check()
            return projection

    def evidence(self):
        self._check()
        return {'schema_version': self.VERSION, 'origin': 'synthetic',
            'configuration_sha256': self._settings_sha256, 'request_sha256': self._request_sha256,
            'source_boundary': deepcopy(self.production.evidence()),
            'publication_boundary': deepcopy(self.publication.evidence()), 'method_registry_sha256': self.methods.content_digest,
            'limitations': ['No generated work, entitlement, certificate, debt, cash or native receipt.']}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.publication.close()
            finally:
                self.production.close()


def build_session(*, request, output_directory, offline, settings):
    """Build only explicit synthetic sources; callers choose new or saved publication."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = QSPaymentCalculationFixtureSettings.model_validate(settings).model_copy(deep=True)
    before, after = settings.production_sources, settings.publication_sources
    next_request = settings.publication_request
    context, next_context = request.context, next_request.context
    if (offline is not True or context.execution_mode != 'offline_fixture' or next_context.execution_mode != 'offline_fixture'
            or context.contract_ref.id != 'QS-A08' or before.action_id != 'QS-A08' or after.action_id != 'QS-A08'
            or request.execution_path != 'deterministic' or next_request.execution_path != 'deterministic'
            or request.action_input != next_request.action_input or request.action_input['measurement_result_refs']
            or context.read_token == next_context.read_token
            or any(getattr(context, name) != getattr(next_context, name) for name in
                ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
            or settings.author_authority_ref not in context.authorization_refs
            or settings.author_authority_ref not in next_context.authorization_refs
            or before.organization_snapshot != after.organization_snapshot
            or before.source_projection['macro_version'] != after.source_projection['macro_version']
            or before.source_projection['organization_id'] != after.source_projection['organization_id']
            or before.source_projection['objects'] != after.source_projection['objects']
            or Path(before.journal_path).resolve() != Path(after.journal_path).resolve()):
        raise ValueError('Payment publication requires same-journal original sources, original time/authority and independent fresh read token')
    production = publication = None
    try:
        production = build_sources(request=request, output_directory=output_directory, offline=offline, settings=before)
        publication = build_sources(request=next_request, output_directory=output_directory, offline=offline, settings=after)
        return QSPaymentCalculationFixtureSession(request, settings, production, publication)
    except Exception:
        try:
            if publication is not None:
                publication.close()
        finally:
            if production is not None:
                production.close()
        raise
