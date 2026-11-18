"""Shared explicit synthetic role sources and original persistent invocation validation."""
from contextlib import contextmanager
from copy import deepcopy
import importlib
from pathlib import Path
from threading import RLock

from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, task_digest
from src.organization.registry import OrganizationRegistry, OrganizationSnapshot


class RoleFixtureSourceSettings(StrictRecord):
    action_id: TextId
    source_note: TextId
    journal_path: TextId
    organization_snapshot: OrganizationSnapshot
    source_projection: dict
    allow_saved_recovery: bool = False


class RoleFixtureApplication:
    # Concrete role applications supply closed routes and their original prefix.
    ROLE = None
    ACTIONS = None
    MODULE_PREFIX = None
    ASSEMBLER_PREFIX = None
    VERSION = None
    WAIT_KIND = None

    def __init__(self, request, settings):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self._context = self.request.context.model_dump(mode='json')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._lock = RLock()
        self._closed = False
        snapshot = self.settings.organization_snapshot
        self.organizations = OrganizationRegistry(snapshot.run_id)
        for organization in snapshot.organizations:
            self.organizations.register(organization)
        for authorization in snapshot.authorizations:
            self.organizations.authorize(authorization)
        for ref in snapshot.inactive_authorization_refs:
            self.organizations.revoke(ref)
        self.registry = register_representative_processors(ActionRegistry())
        self.registration = self.registry.get(settings.action_id)
        if self.registration.role != self.ROLE or not self.registration.implemented or self.registration.skill is None:
            raise ValueError('Role fixture requires its original implemented processor and Skill')
        self._input = self.registration.contract.validate_input(request.action_input).model_dump(mode='json')
        self._grants = self.organizations.grants(request.context, settings.action_id, self.ROLE)
        self._organization_id = self._grants[0].organization_id
        module, name = self.ACTIONS[settings.action_id]
        assembler = getattr(importlib.import_module('integration.' + self.MODULE_PREFIX + '_' + module + '_actions'),
            self.ASSEMBLER_PREFIX + name + 'ActionAssembler')
        schemas = assembler.SOURCE_SCHEMAS()
        self._sources = {}
        for item in settings.source_projection.get('objects', []):
            if not isinstance(item, dict) or set(item) != {'ref', 'value'}:
                raise ValueError('Role fixture projections require original ref/value records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in self._sources:
                raise ValueError('Role fixture repeats an original source reference')
            self._sources[ref.key()] = schemas.validate_projection(ref, item['value']).model_dump(mode='json')
        # Build the only resource last. TaskStore cleans up its own failed open.
        self.store = TaskStore(run_id=snapshot.run_id,
            organization_ids=[organization.organization_id for organization in snapshot.organizations],
            path=Path(settings.journal_path))

    def _check_context(self, context):
        if (self._closed or context.model_dump(mode='json') != self._context
                or task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256
                or self.organizations.grants(context, self.settings.action_id, self.ROLE) != self._grants):
            raise TaskConflict('Synthetic role source configuration, invocation or authority changed')

    @contextmanager
    def read_guard(self, context):
        with self._lock:
            self._check_context(context)
            try:
                yield
            finally:
                self._check_context(context)

    def project(self, *, context, organization_id, grants):
        with self.read_guard(context):
            if organization_id != self._organization_id or grants != self._grants:
                raise TaskConflict('Synthetic role source recipient or grants changed')
            return deepcopy(self.settings.source_projection)

    def _check_identity(self, row):
        self._check_context(self.request.context)
        identity = TaskIdentity(**row['identity'])
        if (identity.run_id != self.request.context.run_id or identity.organization_id != self._organization_id
                or identity.action_id != self.settings.action_id or identity.role != self.ROLE
                or identity.request_id != self.request.context.operation_id or identity.purpose != 'action'
                or identity.context_sha256 != task_digest(self._context)
                or identity.input_sha256 != task_digest(self._input)):
            raise TaskConflict('Synthetic role task changes its original invocation identity')
        return identity

    def _check_sources(self, sources):
        seen = set()
        for item in sources:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Synthetic role reading has an invalid source record')
            key = Reference.model_validate(item['ref']).key()
            if key in seen or key not in self._sources or item['projection'] != self._sources[key]:
                raise TaskConflict('Synthetic role reading changes an original configured source')
            seen.add(key)

    def validate_invocation(self, row, prepared):
        with self.read_guard(prepared.context):
            self._check_identity(row)
            if (prepared.runner.registry is not self.registry
                    or prepared.runner.organizations is not self.organizations
                    or prepared.action_input.model_dump(mode='json') != self._input):
                raise TaskConflict('Synthetic role invocation substitutes input or original registries')
            prepared.reading.recheck()
            self._check_sources(prepared.reading.evidence())
            return True

    def validate_wait(self, row, result, conditions):
        with self.read_guard(self.request.context):
            self._check_identity(row)
            result = self.registration.contract.result_adapter.validate_python(result).model_dump(mode='json')
            module, _ = self.ACTIONS[self.settings.action_id]
            expected = {'kind': self.WAIT_KIND or 'manual_' + self.MODULE_PREFIX + '_' + module + '_result_review',
                'result_kind': result['kind'], 'result_sha256': task_digest(result)}
            if result['kind'] == 'needs_information':
                expected.update(missing_fields=result['missing_fields'], requested_refs=result['requested_refs'])
            elif result['kind'] == 'unsupported':
                expected['capability_ref'] = result['capability_ref']
            elif result['kind'] == 'deferred':
                expected['resume_condition'] = result['resume_condition']
            else:
                raise TaskConflict('Synthetic role wait requires a pending original result')
            if conditions != [expected]:
                raise TaskConflict('Synthetic role wait changes its original result condition')
            return True

    def validate_recovery(self, row, record, snapshot):
        with self.read_guard(self.request.context):
            identity = self._check_identity(row)
            if (not self.settings.allow_saved_recovery or record['identity'] != identity.as_dict()
                    or snapshot['identity'] != identity.as_dict() or snapshot['context'] != self._context
                    or snapshot['action_input'] != self._input):
                raise TaskConflict('Synthetic role saved-result recovery requires explicit matching configuration')
            self._check_sources(record['source_reading'])
            return True

    def evidence(self):
        with self.read_guard(self.request.context):
            return {'schema_version': self.VERSION, 'source_mode': 'fixture', 'origin': 'synthetic',
                'source_note': self.settings.source_note, 'configuration_sha256': self._settings_sha256,
                'organization_snapshot_sha256': task_digest(self.settings.organization_snapshot.model_dump(mode='json')),
                'source_projection_sha256': task_digest(self.settings.source_projection),
                'read_token': self.request.context.read_token, 'journal_path': str(self.store.path),
                'allow_saved_recovery': self.settings.allow_saved_recovery,
                'limitations': ['Configured synthetic facts only; no native registration, acceptance, loan, payment or formal receipt.']}

    def close(self):
        with self._lock:
            if not self._closed:
                self.store.close()
                self._closed = True
