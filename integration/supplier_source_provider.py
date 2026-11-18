"""Explicit per-action Supplier source routing with original authorized projections."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.organization.registry import OrganizationRegistry


@dataclass(frozen=True)
class SupplierActionSource:
    """Host-supplied actual provider and explicit source version; no default source."""
    version: str
    provider: object

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version.strip() or not callable(getattr(self.provider, 'project', None)):
            raise ValueError('Supplier action source requires an explicit version and actual project provider')


def _schemas(action_id):
    # Import only the explicitly selected action and retain its original closed schema set.
    from importlib import import_module

    names = {'SUPPLIER-A01': 'screening', 'SUPPLIER-A02': 'product', 'SUPPLIER-A03': 'quote',
        'SUPPLIER-A04': 'order', 'SUPPLIER-A05': 'planning', 'SUPPLIER-A06': 'execution',
        'SUPPLIER-A07': 'quality', 'SUPPLIER-A08': 'logistics', 'SUPPLIER-A09': 'receiving',
        'SUPPLIER-A10': 'payment', 'SUPPLIER-A11': 'remedy', 'SUPPLIER-A13': 'advice'}
    if action_id == 'SUPPLIER-A12':
        from src.actions.contracts.supplier_continuation_objects import supplier_continuation_schemas
        return supplier_continuation_schemas()
    name = names.get(action_id)
    if name is None:
        raise ValueError('Unsupported Supplier source action')
    module = import_module('integration.supplier_' + name + '_actions')
    assembler = getattr(module, 'Supplier' + name.title() + 'ActionAssembler')
    return assembler.SOURCE_SCHEMAS()


def _source_descriptor(source):
    provider = source.provider
    callback = provider.project
    code = getattr(callback, '__code__', None)
    path = Path(code.co_filename) if code is not None else None
    return {'version': source.version,
        'component': type(provider).__module__ + '.' + type(provider).__qualname__,
        'project_component': getattr(callback, '__module__', type(provider).__module__) + '.'
            + getattr(callback, '__qualname__', type(provider).__qualname__ + '.project'),
        'project_code_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path is not None and path.is_file() else None}


class SupplierActionViewProvider:
    """Route to configured actual readers and save their configuration in the original journal.

    Construction performs no source read. Per-action schema validation avoids
    treating different Order/Shipment projections as interchangeable. Sources
    supply their actual envelopes; this layer creates no business object or
    formal macro capability. Actual source health requires a successful read.
    """
    VERSION = 'supplier-action-view-provider.v3'

    def __init__(self, *, store, registry, organizations, provider_id, macro_version, source_mode, sources):
        if (not isinstance(store, TaskStore) or not isinstance(registry, ActionRegistry)
                or not isinstance(organizations, OrganizationRegistry) or organizations.run_id != store.run_id
                or source_mode not in {'formal', 'fixture'} or not isinstance(sources, dict) or not sources
                or any(not isinstance(value, str) or not value.strip() for value in (provider_id, macro_version))
                or any(not isinstance(source, SupplierActionSource) for source in sources.values())):
            raise ValueError('Supplier provider requires original store/registries and explicit mode/version/action sources')
        self.store, self.registry, self.organizations = store, registry, organizations
        self.provider_id, self.macro_version, self.source_mode = provider_id, macro_version, source_mode
        self.sources = MappingProxyType(dict(sources))
        readers, callbacks = {}, {}
        for action_id, source in self.sources.items():
            registration = registry.get(action_id)
            if registration.role != 'Supplier' or not registration.implemented or registration.skill is None:
                raise ValueError('Supplier source route requires its implemented original Supplier contract and Skill')
            readers[action_id] = AuthorizedMacroViewAssembler(organizations, source.provider, _schemas(action_id),
                macro_version=macro_version, source_mode=source_mode)
            callbacks[action_id] = source.provider.project
        self._readers, self._callbacks = MappingProxyType(readers), MappingProxyType(callbacks)
        metadata = {'schema_version': self.VERSION, 'provider_id': provider_id, 'run_id': store.run_id,
            'macro_version': macro_version, 'source_mode': source_mode,
            'sources': {key: _source_descriptor(source) for key, source in sorted(self.sources.items())},
            'routing_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        self.configuration_sha256 = task_digest(metadata)
        self._metadata = {**metadata, 'configuration_sha256': self.configuration_sha256}
        key = 'supplier_action_view_provider:' + provider_id
        with store._transaction():
            row = store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if row is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(self._metadata)))
            elif json.loads(row[0]) != self._metadata:
                raise TaskConflict('Supplier source configuration or code changed under the original provider identity')
            store._db.execute('CREATE TABLE IF NOT EXISTS supplier_source_reads '
                '(sequence INTEGER PRIMARY KEY AUTOINCREMENT, provider_id TEXT NOT NULL, record TEXT NOT NULL)')
        self._calls = []
        self._read_points = {}

    def project(self, *, context, organization_id, grants):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        action_id = context.contract_ref.id
        if (context.contract_ref.kind != 'ActionContract' or action_id not in self.sources
                or context.run_id != self.store.run_id or organization_id not in self.store.organization_ids
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise TaskConflict('Supplier source route requires its configured action, original run/recipient and explicit mode')
        source = self.sources[action_id]
        reader = self._readers[action_id]
        if (reader.provider is not source.provider or source.provider.project != self._callbacks[action_id]
                or _source_descriptor(source) != self._metadata['sources'][action_id]):
            raise TaskConflict('Supplier source provider, version or code changed after assembly')
        actual_grants = self.organizations.grants(context, action_id, 'Supplier')
        if grants != actual_grants or not actual_grants or actual_grants[0].organization_id != organization_id:
            raise TaskConflict('Supplier source read substitutes original current action authorization')
        call = {'action_id': action_id, 'organization_id': organization_id, 'read_token': context.read_token,
            'source_version': source.version, 'component': self._metadata['sources'][action_id]['component'],
            'context_sha256': task_digest(context.model_dump(mode='json')),
            'authorization_sha256': task_digest([grant.model_dump(mode='json') for grant in actual_grants]),
            'status': 'started'}
        self._calls.append(call)
        sequence = self._persist_call(call)
        try:
            projection = reader.assemble(context, action_id, 'Supplier')
            point = (projection.state_version, task_digest(context.business_time.model_dump(mode='json')))
            prior = self._read_points.get(context.read_token)
            if prior is not None and prior != point:
                raise TaskConflict('Supplier action sources disagree on the original immutable read point')
            self._read_points[context.read_token] = point
        except Exception as exc:
            failed = {**call, 'status': 'failed', 'error_type': type(exc).__name__}
            self._persist_call(failed, sequence=sequence)
            call.update(failed)
            raise
        returned = {**call, 'status': 'returned', 'projection_sha256': projection.digest,
            'state_version': projection.state_version,
            'projected_refs': [row.ref.model_dump(mode='json') for row in projection.objects]}
        self._persist_call(returned, sequence=sequence)
        call.update(returned)
        return {'run_id': projection.run_id, 'macro_version': projection.macro_version,
            'state_version': projection.state_version, 'read_token': projection.read_token,
            'business_time': context.business_time.model_dump(mode='json'), 'organization_id': projection.organization_id,
            'objects': [{'ref': row.ref.model_dump(mode='json'), 'value': row.value.model_dump(mode='json')}
                for row in projection.objects]}

    def _checked_record(self, raw):
        record = json.loads(raw)
        digest = record.pop('record_sha256', None)
        if (task_digest(record) != digest or record.get('schema_version') != 'supplier-source-read.v1'
                or record.get('run_id') != self.store.run_id or record.get('provider_id') != self.provider_id
                or record.get('configuration_sha256') != self.configuration_sha256
                or record.get('source_mode') != self.source_mode
                or record.get('call', {}).get('action_id') not in self.sources
                or record['call'].get('organization_id') not in self.store.organization_ids
                or record['call'].get('status') not in {'started', 'returned', 'failed'}):
            raise TaskConflict('Persisted Supplier source read changes its original identity, configuration or content')
        return {**record, 'record_sha256': digest}

    def _persist_call(self, call, *, sequence=None):
        """Commit start before reading and finalize that same attempt once; no replay."""
        body = {'schema_version': 'supplier-source-read.v1', 'run_id': self.store.run_id,
            'provider_id': self.provider_id, 'configuration_sha256': self.configuration_sha256,
            'source_mode': self.source_mode, 'call': deepcopy(call)}
        record = canonical({**body, 'record_sha256': task_digest(body)})
        with self.store._transaction():
            if sequence is None:
                if call['status'] != 'started':
                    raise TaskConflict('Supplier source attempt must start before it can finish')
                cursor = self.store._db.execute('INSERT INTO supplier_source_reads (provider_id,record) VALUES (?,?)',
                    (self.provider_id, record))
                return cursor.lastrowid
            row = self.store._db.execute('SELECT record FROM supplier_source_reads WHERE sequence=? AND provider_id=?',
                (sequence, self.provider_id)).fetchone()
            if row is None:
                raise TaskConflict('Supplier source attempt is missing its original durable start')
            previous = self._checked_record(row[0])['call']
            if (previous['status'] != 'started' or call['status'] not in {'returned', 'failed'}
                    or any(call.get(key) != value for key, value in previous.items() if key != 'status')):
                raise TaskConflict('Supplier source finalization changes or repeats its original attempt')
            self.store._db.execute('UPDATE supplier_source_reads SET record=? WHERE sequence=? AND provider_id=?',
                (record, sequence, self.provider_id))
        return sequence

    def read_evidence(self, *, after_sequence=0, limit=50):
        """Bounded host audit of durable reads; historical starts never trigger a source call."""
        if type(after_sequence) is not int or after_sequence < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('Source evidence requires a nonnegative cursor and a limit from 1 to 200')
        with self.store._lock:
            rows = self.store._db.execute('SELECT sequence,record FROM supplier_source_reads '
                'WHERE provider_id=? AND sequence>? ORDER BY sequence LIMIT ?',
                (self.provider_id, after_sequence, limit)).fetchall()
        records = [{'sequence': row[0], **self._checked_record(row[1])} for row in rows]
        return {'configuration_sha256': self.configuration_sha256, 'records': records,
            'next_sequence': records[-1]['sequence'] if records else after_sequence,
            'limitations': ['Historical read audit only; interrupted starts are unresolved and do not authorize replay or current health.']}

    def health(self, *, context, organization_id, required_refs=()):
        """Report the latest actual read at this exact authorized boundary without querying sources.

        A new token, changed invocation/authorization, restart or unfinished read
        leaves health unknown. Successful empty envelopes prove no required
        object availability. Publication objects have their own read validation.
        """
        context = ActionContext.model_validate(context).model_copy(deep=True)
        action_id = context.contract_ref.id
        if (context.contract_ref.kind != 'ActionContract' or action_id not in self.sources
                or context.run_id != self.store.run_id or organization_id not in self.store.organization_ids
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise TaskConflict('Supplier health requires its configured action, original run/recipient and explicit mode')
        grants = self.organizations.grants(context, action_id, 'Supplier')
        if not grants or grants[0].organization_id != organization_id:
            raise TaskConflict('Supplier health changes original current action authorization')
        required = [Reference.model_validate(ref) for ref in required_refs]
        unique_refs(required)
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        if any(ref.key() not in permitted for ref in required):
            raise TaskConflict('Supplier health requests objects outside original authorized visibility')
        result = {'action_id': action_id, 'organization_id': organization_id, 'source_mode': self.source_mode,
            'source_version': self.sources[action_id].version, 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'), 'status': 'unknown',
            'basis': 'last_actual_authorized_read', 'configuration_sha256': self.configuration_sha256,
            'limitations': ['Availability at this read boundary only; native writes, receipts and publication objects require separate checks.']}
        source = self.sources[action_id]
        if (self._readers[action_id].provider is not source.provider or source.provider.project != self._callbacks[action_id]
                or _source_descriptor(source) != self._metadata['sources'][action_id]):
            return {**result, 'status': 'unavailable', 'reason': 'source_configuration_changed'}
        context_sha = task_digest(context.model_dump(mode='json'))
        grant_sha = task_digest([grant.model_dump(mode='json') for grant in grants])
        call = next((row for row in reversed(self._calls) if row['action_id'] == action_id
            and row['organization_id'] == organization_id and row['context_sha256'] == context_sha
            and row['authorization_sha256'] == grant_sha), None)
        if call is None or call['status'] == 'started':
            return {**result, 'reason': 'no_completed_read_at_current_boundary'}
        if call['status'] == 'failed':
            return {**result, 'status': 'unavailable', 'reason': 'latest_actual_read_failed', 'error_type': call['error_type']}
        available = {Reference.model_validate(ref).key() for ref in call['projected_refs']}
        missing = [ref.model_dump(mode='json') for ref in required if ref.key() not in available]
        return {**result, 'status': 'unavailable' if missing else 'available',
            'reason': 'required_objects_missing' if missing else 'actual_read_returned', 'missing_refs': missing,
            'projection_sha256': call['projection_sha256'], 'state_version': call['state_version'],
            'projected_object_count': len(available)}

    def evidence(self):
        """Configuration and actual read outcomes; configured routes do not prove source health."""
        return {'configuration': deepcopy(self._metadata), 'calls': deepcopy(self._calls),
            'limitations': ['Read-only source routes; native submission/receipts and model transport remain independent.']}
