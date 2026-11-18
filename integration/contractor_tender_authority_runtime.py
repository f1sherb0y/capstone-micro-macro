"""Concrete run-local authority and reentrant writer guard for tender applications."""
from contextlib import contextmanager
from copy import deepcopy
import json
from threading import RLock

from integration.bindings.gba_v1 import GbaV1Assembly
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, canonical, task_digest
from src.organization.registry import OrganizationRegistry, OrganizationSnapshot


class TenderAuthorityRuntimeSettings(StrictRecord):
    runtime_id: TextId
    version: TextId
    organization_snapshot: OrganizationSnapshot


class ContractorTenderAuthorityRuntime:
    """Create original micro registries from explicit trusted application input.

    Native identities must already exist in the actual engine/client. Additional
    professional author organizations remain explicit snapshot identities; native
    membership never supplies their competence, author grants or business facts.
    Pass this same read_guard to source providers and the installed module hook;
    all other native engine writers must use it too. Construction advances no
    native state and creates no second journal, model client or formal ledger.
    """
    VERSION = 'contractor-tender-authority-runtime.v1'

    def __init__(self, *, assembly, settings):
        if not isinstance(assembly, GbaV1Assembly):
            raise ValueError('Tender authority runtime requires its original actual GBA assembly')
        assembly._validate_components()
        self.settings = TenderAuthorityRuntimeSettings.model_validate(settings).model_copy(deep=True)
        snapshot = self.settings.organization_snapshot
        if (snapshot.run_id != assembly.client.run_id
                or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
                or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
            raise ValueError('Tender authority snapshot requires its explicit original run and supported version')
        self.assembly = assembly
        self.organizations = OrganizationRegistry(snapshot.run_id)
        for organization in snapshot.organizations:
            self.organizations.register(organization)
        for grant in snapshot.authorizations:
            self.organizations.authorize(grant)
        for ref in snapshot.inactive_authorization_refs:
            self.organizations.revoke(ref)
        self.registry = register_representative_processors(ActionRegistry())
        registration = self.registry.get('CONTRACTOR-A02')
        if registration.role != 'Contractor' or not registration.implemented or registration.skill is None:
            raise ValueError('Tender authority runtime requires the original A02 processor and Skill')
        self._lock = RLock()
        self._guard_depth = 0
        self._closed = False
        self._roles = deepcopy(assembly.client.organization_roles)
        self._components = (assembly, assembly.engine, assembly.client, assembly.client.tasks,
            self.organizations, self.registry, self._lock)
        self._declared = {'schema_version': self.VERSION, 'run_id': snapshot.run_id,
            'simulation_id': assembly.client.simulation_id, 'runtime_id': self.settings.runtime_id,
            'version': self.settings.version, 'configuration_sha256': task_digest(self.settings.model_dump(mode='json')),
            'organization_snapshot_sha256': task_digest(snapshot.model_dump(mode='json')),
            'native_organization_roles': deepcopy(self._roles),
            'guard': module_factory_descriptor(type(self).read_guard.__wrapped__, 'read_guard')}
        self._key = 'contractor_tender_authority_runtime:' + self.settings.runtime_id
        self._check_native_identities()
        with assembly.client.tasks._transaction():
            prior = assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                assembly.client.tasks._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original tender authority runtime configuration or source changed')
        self._publish_authority_epoch(initial=True)

    def _epoch(self):
        row = self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?',
            (self._key + ':authority_epoch',)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        if (set(record) != {'schema_version', 'declaration_sha256', 'snapshot_sha256', 'revision'}
                or record['schema_version'] != 'authority-epoch.v1'
                or record['declaration_sha256'] != task_digest(self._declared)
                or type(record['revision']) is not int or record['revision'] < 0):
            raise TaskConflict('Original authority epoch has changed identity or revision')
        return record

    def _publish_authority_epoch(self, *, snapshot=None, initial=False):
        """Commit completed guarded authority changes to the original journal.

        Only a digest and monotonic revision are stored here. A checkpoint holds
        the actual closed snapshot; a later change invalidates an older point.
        """
        client = self.assembly.client
        pending = getattr(client, '_native_checkpoint_pending', None)
        if pending is not None:
            if not pending['installing']:
                raise TaskConflict('Current authority requires verified checkpoint reinstallation')
            return  # Initial constructors cannot overwrite the saved current epoch.
        from integration.native_checkpoint import _authority_snapshot
        snapshot = _authority_snapshot(self.organizations) if snapshot is None else snapshot
        digest = task_digest(snapshot)
        store = client.tasks
        with store._lock:
            prior = self._epoch()
            if prior is not None and prior['snapshot_sha256'] == digest:
                return
            if initial and prior is not None:
                raise TaskConflict('Changed current authority requires original checkpoint restoration')
            record = {'schema_version': 'authority-epoch.v1', 'declaration_sha256': task_digest(self._declared),
                'snapshot_sha256': digest, 'revision': 0 if prior is None else prior['revision'] + 1}
            def write():
                store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                    (self._key + ':authority_epoch', canonical(record)))
            if store._db.in_transaction:
                write()
            else:
                with store._transaction():
                    write()

    def _validate_authority_epoch(self, snapshot):
        with self.assembly.client.tasks._lock:
            epoch = self._epoch()
        if epoch is None or epoch['snapshot_sha256'] != task_digest(snapshot):
            raise TaskConflict('Checkpoint authority does not match its original durable current epoch')

    def _check_native_identities(self):
        if self.assembly.client.organization_roles != self._roles:
            raise TaskConflict('Tender authority runtime changed original native organization roles')
        for organization_id, role in self._roles.items():
            try:
                organization = self.organizations.get(organization_id)
            except KeyError as exc:
                raise TaskConflict('Explicit authority snapshot omits a bound native organization') from exc
            agent = self.assembly.engine.agents.get(organization_id)
            if (agent is None or agent.agent_id != organization_id or agent.role != role
                    or role not in {assignment.role for assignment in organization.assignments}):
                raise TaskConflict('Tender authority snapshot changes native identity or infers an unassigned role')

    def _check(self):
        actual = (self.assembly, self.assembly.engine, self.assembly.client, self.assembly.client.tasks,
            self.organizations, self.registry, self._lock)
        if (self._closed or any(value is not original for value, original in zip(actual, self._components))
                or self.organizations.run_id != self.assembly.client.run_id
                or self.assembly.client.simulation_id != self._declared['simulation_id']
                or task_digest(self.settings.model_dump(mode='json')) != self._declared['configuration_sha256']
                or module_factory_descriptor(type(self).read_guard.__wrapped__, 'read_guard') != self._declared['guard']):
            raise TaskConflict('Tender authority runtime changed original components, run or configuration, or is closed')
        self.assembly._validate_components()
        self._check_native_identities()
        with self.assembly.client.tasks._lock:
            saved = self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Tender authority runtime configuration evidence changed')

    @contextmanager
    def read_guard(self):
        """Same-thread reentrant lock shared by original sources and engine advancement."""
        with self._lock:
            self._check()
            if self._guard_depth == 0:
                self._publish_authority_epoch()
            self._guard_depth += 1
            try:
                yield
            finally:
                self._guard_depth -= 1
                self._check()
                if self._guard_depth == 0:
                    self._publish_authority_epoch()

    def evidence(self):
        with self.read_guard():
            return {'schema_version': self.VERSION, 'status': 'configured_unverified',
                'run_id': self.assembly.client.run_id, 'simulation_id': self.assembly.client.simulation_id,
                'configuration_sha256': task_digest(self._declared),
                'initial_organization_snapshot_sha256': self._declared['organization_snapshot_sha256'],
                'guard': 'same_thread_reentrant',
                'limitations': ['Explicit initial authority is not native professional competence or business facts.',
                    'All actual engine writers must use this guard; live grant updates require explicit application persistence.']}

    def close(self):
        """Release this runtime only; original engine/client journal stays application-owned."""
        with self._lock:
            self._closed = True


def build_authority_runtime(*, assembly, settings):
    """Concrete application dependency factory; no native read or model call."""
    return ContractorTenderAuthorityRuntime(assembly=assembly, settings=settings)
