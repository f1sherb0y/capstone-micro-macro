"""Durable explicit option inputs for repeated invocations of one model host.

Only local decision inputs are stored. The source provider, its read guard and
independent current business gate remain application-owned. Saving alternatives
neither registers nor executes a task and confers no formal permission/effect.
"""
from copy import deepcopy
import json
from types import MappingProxyType

from integration.action_model_host import ActionModelHost, ActionModelHostConfiguration, ActionOptionSource
from integration.action_option_snapshots import (
    ActionOptionSnapshot, build_snapshot_option_source, capture_action_option_snapshot,
)
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext
from src.actions.contracts.references import ActionReadView
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest, _text


class ActionOptionSnapshotStore:
    """Keep exact per-invocation alternatives without changing the host version.

    Each configured action has one stable ActionOptionSource. Its callbacks
    select a saved snapshot using the complete original context/input digests,
    run, organization and action; absent entries fail explicitly. A saved entry
    cannot be replaced or attached for the first time to an already started
    task. Reopening the same namespace reuses its original declaration and rows.
    Optional option_producers are actual application callbacks, one per action;
    the eight role hosts call them before execution only when no saved snapshot
    exists. Without producers, callers explicitly save snapshots themselves.
    """
    VERSION = 'action-option-snapshot-store.v1'

    def __init__(self, *, store, registry, namespace, action_ids, max_options, validate_current,
            option_producers=None):
        if (not isinstance(store, TaskStore) or not isinstance(registry, ActionRegistry)
                or not callable(validate_current) or type(max_options) is not int or max_options <= 0
                or not isinstance(action_ids, (tuple, list, set, frozenset)) or not action_ids
                or len(set(action_ids)) != len(action_ids)):
            raise ValueError('Option storage requires actual journal/registry, explicit actions, limit and current gate')
        _text(namespace)
        for action_id in action_ids:
            _text(action_id)
        self.store, self.registry, self.namespace = store, registry, namespace
        self.action_ids, self.max_options = frozenset(action_ids), max_options
        self.validate_current = validate_current
        if (option_producers is not None and (not isinstance(option_producers, dict)
                or set(option_producers) != self.action_ids
                or any(not callable(callback) for callback in option_producers.values()))):
            raise ValueError('Automatic capture requires one actual option producer per configured action')
        self.option_producers = MappingProxyType(dict(option_producers or {}))
        registrations = {}
        for action_id in self.action_ids:
            registration = registry.get(action_id)
            if not registration.implemented or registration.skill is None:
                raise ValueError('Option storage cannot activate an action without its processor and bound Skill')
            registrations[action_id] = registration
        self.registrations = MappingProxyType(registrations)
        self._components = (store, registry, self.registrations, validate_current, self.option_producers)
        self._declared = self._configuration()
        self.configuration_sha256 = task_digest(self._declared)
        self._metadata_key = 'action_option_snapshot_store:' + task_digest([store.run_id, namespace])
        # Use the existing local journal metadata, without a new domain table
        # or a second formal ledger. Configuration never includes live rows.
        with store._transaction():
            prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._metadata_key,)).fetchone()
            if prior is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._metadata_key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original option snapshot storage configuration changed; no silent migration')
        self.option_sources = MappingProxyType({action_id: self._source(action_id) for action_id in sorted(self.action_ids)})

    def _configuration(self):
        return dict(schema_version=self.VERSION, run_id=self.store.run_id, namespace=self.namespace,
            action_ids=sorted(self.action_ids), max_options=self.max_options,
            registrations={action_id: dict(role=registration.role, contract_source_sha256=registration.contract.source_sha256,
                input_schema_sha256=task_digest(registration.contract.input_model.model_json_schema()),
                processor_id=registration.processor_id, strategy=registration.strategy,
                processor=module_factory_descriptor(registration.processor, registration.processor_id),
                candidate_fields=[[choice, list(fields)] for choice, fields in registration.candidate_fields],
                candidate_collection_fields=[[choice, list(fields)]
                    for choice, fields in registration.candidate_collection_fields],
                skill_version=registration.skill.manifest.skill_version,
                skill_sha256=registration.skill.manifest.skill_sha256,
                shared_sha256s=dict(registration.skill.manifest.shared_sha256s))
                for action_id, registration in sorted(self.registrations.items())},
            validate_current=module_factory_descriptor(self.validate_current, 'option_storage.validate_current'),
            option_producers={action_id: module_factory_descriptor(callback, action_id)
                for action_id, callback in sorted(self.option_producers.items())},
            storage=module_factory_descriptor(type(self).save, self.VERSION),
            capture=module_factory_descriptor(capture_action_option_snapshot, 'capture_options'),
            source=module_factory_descriptor(build_snapshot_option_source, 'snapshot_options'))

    def _check(self):
        if (any(actual is not original for actual, original in zip(
                (self.store, self.registry, self.registrations, self.validate_current, self.option_producers), self._components))
                or self.configuration_sha256 != task_digest(self._declared)
                or self._configuration() != self._declared
                or any(self.registry.get(key) is not row for key, row in self.registrations.items())):
            raise TaskConflict('Original option snapshot journal/registry/gate declaration changed')
        with self.store._lock:
            saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._metadata_key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Original option snapshot storage declaration is missing or changed')

    def _selection(self, context, action_input, registration, organization_id):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.run_id != self.store.run_id or organization_id not in self.store.organization_ids
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id not in self.action_ids
                or self.registrations.get(context.contract_ref.id) is not registration):
            raise TaskConflict('Stored option selection changes original run, organization or action registration')
        original = registration.contract.validate_input(action_input).model_dump(mode='json')
        return dict(run_id=context.run_id, organization_id=organization_id, action_id=registration.action_id,
            request_id=context.operation_id, context_sha256=task_digest(context.model_dump(mode='json')),
            input_sha256=task_digest(original))

    def _entry_key(self, selection):
        return 'action_option_snapshot:' + task_digest([self._metadata_key, selection])

    def _check_not_started(self, selection):
        """Called while holding the same journal lock/transaction as selection."""
        for row in self.store.for_organization(run_id=selection['run_id'],
                organization_id=selection['organization_id']):
            identity = TaskIdentity(**row['identity'])
            # Task slots are keyed by recipient/purpose/request, regardless of
            # action. Direct drivers may also retain an explicit request ID
            # or purpose for this same context. Neither alias may hide an
            # already started invocation from the first-capture guard.
            same_slot = identity.purpose == 'action' and identity.request_id == selection['request_id']
            same_context = identity.context_sha256 == selection['context_sha256']
            if not same_slot and not same_context:
                continue
            original_task = self.store._read(identity)
            if (identity.action_id != selection['action_id'] or identity.role != self.registrations[selection['action_id']].role
                    or identity.context_sha256 != selection['context_sha256']
                    or identity.input_sha256 != selection['input_sha256']
                    or original_task['revision'] != 0 or original_task['state'] != 'waiting_input'
                    or original_task['conditions'] or self.store.continuation(identity) is not None):
                raise TaskConflict('Cannot attach new alternatives to a changed or already started invocation')

    def _record(self, snapshot):
        snapshot = ActionOptionSnapshot.model_validate(snapshot).model_copy(deep=True)
        if snapshot.action_id not in self.action_ids or len(snapshot.options) > self.max_options:
            raise TaskConflict('Stored snapshot leaves its original configured action or option limit')
        registration = self.registrations[snapshot.action_id]
        if snapshot.role != registration.role:
            raise TaskConflict('Stored snapshot changes its original role')
        selection = self._selection(snapshot.context, snapshot.action_input, registration, snapshot.organization_id)
        record = dict(schema_version=self.VERSION, configuration_sha256=self.configuration_sha256,
            selection=selection, snapshot=snapshot.model_dump(mode='json'))
        record['record_sha256'] = task_digest(record)
        return record

    def _decode(self, raw, selection):
        record = json.loads(raw)
        if (not isinstance(record, dict) or set(record) != {
                'schema_version', 'configuration_sha256', 'selection', 'snapshot', 'record_sha256'}
                or record['selection'] != selection or record != self._record(
                    ActionOptionSnapshot.model_validate_json(canonical(record['snapshot'])))):
            raise TaskConflict('Saved option snapshot changed its complete invocation, source contents or digest')
        return deepcopy(record)

    def save(self, *, context, action_input, options, registration, reading):
        """Capture and approve under the caller's actual read guard, then save.

        The current gate is invoked by the same source implementation used at
        decision time. The caller supplies every alternative explicitly; no
        source, candidate, method or task is created while capturing it.
        """
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        snapshot = capture_action_option_snapshot(context=context, action_input=action_input,
            options=options, registration=registration, reading=reading)
        record = self._record(snapshot)
        source = build_snapshot_option_source(snapshot=snapshot, registration=registration,
            validate_current=self.validate_current)
        source.prepare_options(context=context, action_input=action_input, registration=registration, reading=reading)
        self._check()
        key = self._entry_key(record['selection'])
        with self.store._transaction():
            prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if prior is not None:
                if self._decode(prior[0], record['selection']) != record:
                    raise TaskConflict('An original option snapshot cannot be replaced or reordered')
            else:
                self._check_not_started(record['selection'])
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(record)))
            reading.recheck()
            self._check()
        return deepcopy(record)

    def _read_record(self, *, context, action_input, registration, reading):
        """Internal lookup; the caller must validate sources before disclosure."""
        self._check()
        if not isinstance(reading, ActionReadView):
            raise TaskConflict('Stored options require an actual authorized action reading')
        reading.check_method_context(context, registration.action_id)
        selection = self._selection(context, action_input, registration, reading.organization_id)
        with self.store._lock:
            row = self.store._db.execute('SELECT value FROM metadata WHERE key=?',
                (self._entry_key(selection),)).fetchone()
            if row is None:
                raise TaskConflict('No original option snapshot exists for this exact invocation')
            record = self._decode(row[0], selection)
        self._check()
        return record

    def read(self, *, context, action_input, registration, reading):
        """Read the exact snapshot only after its current source/authority gate."""
        kwargs = dict(context=context, action_input=action_input, registration=registration, reading=reading)
        record = self._read_record(**kwargs)
        source = build_snapshot_option_source(snapshot=ActionOptionSnapshot.model_validate_json(
            canonical(record['snapshot'])), registration=registration, validate_current=self.validate_current)
        source.prepare_options(**kwargs)
        if self._read_record(**kwargs) != record:
            raise TaskConflict('Stored snapshot changed during current source/authority validation')
        return record

    def prepare_invocation(self, *, context, action_input, registration, reading):
        """Capture once before claiming; an existing invocation only reads.

        Explicit producers receive the same arguments as prepare_options on a
        direct ActionOptionSource. They only enumerate actual typed inputs;
        the independent current gate still authenticates their business relation.
        No producer is called for an already saved or started invocation.
        """
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if not isinstance(reading, ActionReadView):
            raise TaskConflict('Option preparation requires an actual authorized action reading')
        reading.check_method_context(context, registration.action_id)
        selection = self._selection(context, action_input, registration, reading.organization_id)
        kwargs = dict(context=context, action_input=action_input, registration=registration, reading=reading)
        before = reading.method_evidence()
        try:
            # Do not turn a validation/read failure into permission to replace
            # an original snapshot. Missing records alone permit first capture.
            with self.store._lock:
                prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?',
                    (self._entry_key(selection),)).fetchone()
                if prior is None:
                    self._check_not_started(selection)
            if prior is None:
                producer = self.option_producers.get(registration.action_id)
                if producer is None:
                    raise TaskConflict('Missing original options require an explicitly configured actual producer')
                options = producer(context=context.model_copy(deep=True),
                    action_input=registration.contract.validate_input(action_input).model_copy(deep=True),
                    registration=registration, reading=reading)
                if (not isinstance(options, (list, tuple)) or not options
                        or len(options) > self.max_options):
                    raise TaskConflict('Actual producer must return an explicit bounded collection of typed options')
                if reading.method_evidence() != before:
                    raise TaskConflict('Option production cannot execute professional methods')
                self._check()
                record = self.save(options=options, **kwargs)
            else:
                record = self.read(**kwargs)
            self._check()
            return dict(schema_version='action-option-preparation.v1', selection=deepcopy(record['selection']),
                configuration_sha256=self.configuration_sha256, record_sha256=record['record_sha256'],
                snapshot_sha256=task_digest(record['snapshot']), option_count=len(record['snapshot']['options']))
        finally:
            reading.recheck()
            if reading.method_evidence() != before:
                raise TaskConflict('Option preparation cannot execute professional methods')

    def _source(self, action_id):
        def prepare_options(**kwargs):
            if kwargs['registration'] is not self.registrations[action_id]:
                raise TaskConflict('Option storage source changed its configured action')
            record = self._read_record(**kwargs)
            source = build_snapshot_option_source(snapshot=ActionOptionSnapshot.model_validate_json(
                canonical(record['snapshot'])), registration=kwargs['registration'], validate_current=self.validate_current)
            result = source.prepare_options(**kwargs)
            self._check()
            if self._read_record(**kwargs) != record:
                raise TaskConflict('Original stored alternatives changed during source validation')
            return result

        def validate_options(**kwargs):
            supplied = kwargs.pop('options')
            if kwargs['registration'] is not self.registrations[action_id]:
                raise TaskConflict('Option storage validation changed its configured action')
            record = self._read_record(**kwargs)
            source = build_snapshot_option_source(snapshot=ActionOptionSnapshot.model_validate_json(
                canonical(record['snapshot'])), registration=kwargs['registration'], validate_current=self.validate_current)
            result = source.validate_options(options=supplied, **kwargs)
            self._check()
            if self._read_record(**kwargs) != record:
                raise TaskConflict('Original stored alternatives changed during option validation')
            return result

        version = task_digest(dict(schema_version=self.VERSION,
            configuration_sha256=self.configuration_sha256, action_id=action_id))
        return ActionOptionSource(version, prepare_options, validate_options, self.prepare_invocation)

    def evidence(self):
        self._check()
        return dict(schema_version=self.VERSION, configuration_sha256=self.configuration_sha256,
            configuration=deepcopy(self._declared), status='configured_execution_unverified')


def build_snapshot_action_model_host(*, snapshots, client, model_version, configuration):
    """Assemble the original host with its same-journal stable option sources.

    This constructs no client and makes no model call. Source snapshots are
    captured explicitly before each invocation starts, either by the caller or
    its configured producers through the role host's preparation hook. New
    invocations retain this host's original configuration and durable budget.
    """
    if not isinstance(snapshots, ActionOptionSnapshotStore):
        raise ValueError('Snapshot model host requires its actual option snapshot storage')
    snapshots._check()
    config = ActionModelHostConfiguration.model_validate(configuration).model_copy(deep=True)
    if (frozenset(config.action_ids) != snapshots.action_ids
            or len(config.action_ids) != len(snapshots.action_ids) or config.max_options != snapshots.max_options):
        raise ValueError('Snapshot model host action set and option limit must match its original declared source')
    host = ActionModelHost(store=snapshots.store, registry=snapshots.registry, client=client,
        model_version=model_version, configuration=config, option_sources=dict(snapshots.option_sources))
    snapshots._check()
    return host
