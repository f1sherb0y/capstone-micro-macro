"""Completed-tick persistence for the frozen native engine, not business replay.

The original constructors rebuild services, locks, clients and observers. Only
allowlisted state is restored. Callers reinstall their original application
after build_module_engine returns. Changed runtime bindings require an explicit,
verified reinstallation window before any new business invocation.
"""
from collections import Counter, defaultdict, deque
from contextlib import contextmanager, nullcontext
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import platform
import random
import sys
import time

import networkx as nx
import pydantic
from pydantic import BaseModel

from integration.bootstrap import enable_gba_imports
from src.coordination.tasks import TaskConflict, canonical, task_digest
from src.json_input import read_json_object


SCHEMA = 'gba-native-completed-tick-checkpoint.v3'
_ROOT = Path(__file__).resolve().parents[1]
_PREFIX = 'gba_construction_sim.backend.'


class NativeEngineLease:
    """An OS lease held until client.close, including across checkpoint writes."""

    def __init__(self, task_path):
        if task_path is None:
            raise TaskConflict('Native checkpoints require a persistent original task store')
        self.path = Path(str(Path(task_path).resolve()) + '.native-engine.lock')
        self._file = self.path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.path.stat().st_size == 0:
                    self._file.write(b'0')
                    self._file.flush()
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self._file.close()
            raise TaskConflict('Another native engine still owns this task store') from exc

    def close(self):
        if not self._file.closed:
            self._file.close()


def _sources():
    macro = enable_gba_imports() / 'gba_construction_sim' / 'backend'
    paths = [p for base in (macro, _ROOT / 'integration', _ROOT / 'src')
             for p in base.rglob('*.py') if '__pycache__' not in p.parts]
    return {p.relative_to(_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def _types():
    """Fixed module names: checkpoint contents can never select an import."""
    enable_gba_imports()
    names = ('core.enums', 'models.action', 'models.agent', 'models.engagement',
             'models.environment', 'models.event', 'models.metrics', 'models.policy',
             'models.procurement', 'models.project', 'models.project_performance',
             'models.simulation', 'models.stage_rule', 'agents.contracts',
             'agents.base_agent', 'simulation.decision_request',
             'simulation.interaction_session', 'simulation.message_bus',
             'network.collaboration_network', 'network.collaboration_prior')
    result = {}
    for name in names:
        module = importlib.import_module(_PREFIX + name)
        for value in vars(module).values():
            if (inspect.isclass(value) and value.__module__ == module.__name__
                    and (issubclass(value, (BaseModel, Enum)) or is_dataclass(value))):
                result[value.__module__ + ':' + value.__qualname__] = value
    from gba_construction_sim.backend.agents.agent_registry import ROLE_AGENT_TYPES
    result.update({v.__module__ + ':' + v.__qualname__: v for v in ROLE_AGENT_TYPES.values()})
    return result


class _Graph:
    """JSON references preserve profiles, message payloads and bus aliases."""

    def __init__(self, anchors):
        self.anchors = anchors
        self.anchor_ids = {id(v): k for k, v in anchors.items()}
        self.types = _types()
        self.nodes, self.seen, self.decoded = [], {}, {}
        self.originals = []  # retain temporary graph/RNG values against id reuse

    def encode(self, value):
        if id(value) in self.anchor_ids:
            return {'anchor': self.anchor_ids[id(value)]}
        if isinstance(value, Enum):
            key = type(value).__module__ + ':' + type(value).__qualname__
            if key not in self.types:
                raise TaskConflict('Unsupported checkpoint enum: ' + key)
            return {'enum': key, 'name': value.name}
        if value is None or type(value) in (str, int, bool):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise TaskConflict('Non-finite native checkpoint state')
            return value
        if id(value) in self.seen:
            return {'ref': self.seen[id(value)]}
        index = len(self.nodes)
        self.seen[id(value)] = index
        self.originals.append(value)
        node = {}
        self.nodes.append(node)
        key = type(value).__module__ + ':' + type(value).__qualname__
        if type(value) in (dict, Counter, defaultdict):
            if isinstance(value, defaultdict) and value.default_factory is not deque:
                raise TaskConflict('Unsupported checkpoint default factory')
            node.update(kind=type(value).__name__, items=[
                [self.encode(k), self.encode(v)] for k, v in value.items()])
        elif type(value) in (list, tuple, set, frozenset, deque):
            node.update(kind=type(value).__name__, items=[self.encode(v) for v in value])
        elif type(value) is random.Random:
            node.update(kind='random', state=self.encode(value.getstate()))
        elif type(value) is nx.Graph:
            node.update(kind='graph', attributes=self.encode(value.graph),
                        nodes=self.encode(list(value.nodes(data=True))),
                        edges=self.encode(list(value.edges(data=True))))
        elif key in self.types and isinstance(value, BaseModel):
            if (getattr(value, '__pydantic_extra__', None)
                    or getattr(value, '__pydantic_private__', None)
                    or set(vars(value)) - set(type(value).model_fields)):
                raise TaskConflict('Unsupported extra/private model checkpoint state: ' + key)
            node.update(kind='model', type=key, values=self.encode(vars(value)),
                        fields_set=self.encode(value.model_fields_set))
        elif key in self.types and is_dataclass(value):
            expected = {f.name for f in fields(value)}
            if set(vars(value)) != expected:
                raise TaskConflict('Unsupported native dataclass state: ' + key)
            node.update(kind='dataclass', type=key, values=self.encode(vars(value)))
        elif key in self.types and set(vars(value)) == {'profile', 'rng'}:
            node.update(kind='behavior', type=key, values=self.encode(vars(value)))
        else:
            raise TaskConflict('Unsupported native checkpoint state: ' + key)
        return {'ref': index}

    def decode(self, value):
        if value is None or type(value) in (str, int, bool, float):
            return value
        if not isinstance(value, dict):
            raise TaskConflict('Invalid checkpoint reference')
        if set(value) == {'anchor'} and value['anchor'] in self.anchors:
            return self.anchors[value['anchor']]
        if set(value) == {'enum', 'name'} and value['enum'] in self.types:
            cls = self.types[value['enum']]
            if issubclass(cls, Enum):
                return cls[value['name']]
        if set(value) != {'ref'} or type(value['ref']) is not int or not 0 <= value['ref'] < len(self.nodes):
            raise TaskConflict('Invalid checkpoint object reference')
        index = value['ref']
        if index in self.decoded:
            return self.decoded[index]
        n = self.nodes[index]
        kind = n['kind']
        expected = {
            'model': {'kind', 'type', 'values', 'fields_set'},
            'dataclass': {'kind', 'type', 'values'}, 'behavior': {'kind', 'type', 'values'},
            'random': {'kind', 'state'}, 'graph': {'kind', 'attributes', 'nodes', 'edges'},
            **{k: {'kind', 'items'} for k in ('dict', 'Counter', 'defaultdict', 'list', 'deque', 'set', 'tuple', 'frozenset')},
        }
        if kind not in expected or set(n) != expected[kind]:
            raise TaskConflict('Invalid checkpoint node fields')
        cls = self.types.get(n.get('type'))
        if kind in ('model', 'dataclass', 'behavior'):
            if cls is None:
                raise TaskConflict('Unregistered checkpoint type')
            if kind == 'model' and issubclass(cls, BaseModel):
                obj = cls.model_construct()
            elif ((kind == 'dataclass' and is_dataclass(cls))
                  or (kind == 'behavior' and not issubclass(cls, (BaseModel, Enum)) and not is_dataclass(cls))):
                obj = object.__new__(cls)
            else:
                raise TaskConflict('Checkpoint object type mismatch')
            self.decoded[index] = obj
            values = self.decode(n['values'])
            if kind == 'model':
                if set(values) != set(cls.model_fields):
                    raise TaskConflict('Native model fields changed')
                object.__setattr__(obj, '__dict__', values)
                object.__setattr__(obj, '__pydantic_fields_set__', self.decode(n['fields_set']))
            else:
                expected = {f.name for f in fields(cls)} if kind == 'dataclass' else {'profile', 'rng'}
                if set(values) != expected:
                    raise TaskConflict('Native state object fields changed')
                for key, item in values.items():
                    object.__setattr__(obj, key, item)
        elif kind in ('dict', 'Counter', 'defaultdict'):
            obj = {'dict': dict, 'Counter': Counter, 'defaultdict': lambda: defaultdict(deque)}[kind]()
            self.decoded[index] = obj
            for k, v in n['items']:
                obj[self.decode(k)] = self.decode(v)
        elif kind in ('list', 'deque', 'set', 'tuple', 'frozenset'):
            # Native tuples/sets have no self cycles; mutable lists may alias.
            obj = {'list': list, 'deque': deque, 'set': set, 'tuple': list, 'frozenset': set}[kind]()
            self.decoded[index] = obj
            for v in n['items']:
                (obj.add if isinstance(obj, set) else obj.append)(self.decode(v))
            if kind in ('tuple', 'frozenset'):
                obj = tuple(obj) if kind == 'tuple' else frozenset(obj)
        elif kind == 'random':
            obj = random.Random()
            obj.setstate(self.decode(n['state']))
        elif kind == 'graph':
            obj = nx.Graph()
            obj.graph.update(self.decode(n['attributes']))
            obj.add_nodes_from(self.decode(n['nodes']))
            obj.add_edges_from(self.decode(n['edges']))
        else:
            raise TaskConflict('Unsupported checkpoint node kind')
        self.decoded[index] = obj
        return obj


def _anchors(engine, client):
    from integration.native_routes import NativeRouteAgentClient
    if type(client) is not NativeRouteAgentClient:
        from integration.model_tender_native import ModelTenderAgentClient
        from src.actions.model_strategy import model_client_request_policy
        if type(client) is not ModelTenderAgentClient:
            raise TaskConflict('Checkpoint requires an explicit original native client composition')
        policy = model_client_request_policy(client.tender_model_client)
        if (client._model_closed or client._model_policy != policy
                or client.versions['model'] != 'tender-model:' + task_digest(policy)):
            raise TaskConflict('Checkpoint model client changed its original bounded transport')
    names = ('collaboration_prior', 'events', 'workflow_runtime', 'stage_rules',
             'engagement_manager', 'action_validator', 'action_applier', 'lifecycle_engine',
             'state_update_engine', 'macro_updater', 'project_generator',
             'agent_operation_scheduler', 'network', 'metrics_calculator', 'result_store')
    anchors = {'engine': engine, **{name: getattr(engine, name) for name in names},
               'module': engine.agent_module, 'provider': engine.agent_module.decision_provider,
               'scheduler': engine.agent_module.decision_scheduler,
               'collector': engine.agent_module.decision_collector,
               'sessions': engine.lifecycle_engine.interaction_sessions,
               'bus': engine.lifecycle_engine.interaction_sessions.message_bus,
               'lifecycle_action_applier': engine.lifecycle_engine.action_applier,
               'pool': engine.lifecycle_engine.agent_pool,
               'route_behaviors': client.native_routes.behaviors,
               'route_collector': client.native_routes.behaviors.decision_collector,
               'route_provider': client.native_routes.provider}
    if (len({id(v) for v in anchors.values()}) != len(anchors)
            or engine.agent_registry is not engine.agent_module
            or engine.lifecycle_engine.decision_scheduler is not anchors['scheduler']
            or engine.lifecycle_engine.decision_collector is not anchors['collector']
            or engine.procurement_executor is not None or engine.procurement_execution.mode != 'gba_native'):
        raise TaskConflict('Unsupported native component topology or procurement execution')
    return anchors


# Complete native component inventories: new mutable fields require review.
_FIELDS = {
    'engine': '_procurement_execution procurement_executor simulation_id name ticks random_seed rng current_tick policy macro_environment agents projects agent_module agent_registry enable_project_generation max_tender_invites target_project_count max_active_projects collaboration_prior events workflow_config workflow_runtime stage_rules engagement_manager action_validator action_applier lifecycle_engine state_update_engine macro_updater project_generator agent_operation_scheduler network metrics_calculator result_store metrics status _generated_project_counter current_phase current_operation last_step_profile step_profile_history',
    'collaboration_prior': 'edges _by_pair edge_count average_fit',
    'events': 'events _counter _observers',
    'workflow_runtime': 'workflow policy macro_environment events baseline_policy baseline_environment current_period active_interventions triggered_event_ids last_applied_events _previous_period_id _previous_intervention_ids',
    'stage_rules': 'rules', 'engagement_manager': 'events _counter',
    'action_validator': 'events', 'action_applier': '', 'lifecycle_action_applier': '',
    'lifecycle_engine': 'events engagement_manager stage_rules action_validator agent_module agent_registry decision_provider rng max_tender_invites max_tender_camel_advisors decision_scheduler decision_collector action_applier interaction_sessions agent_pool',
    'state_update_engine': 'events rng collaboration_prior', 'macro_updater': 'rng',
    'project_generator': 'rng', 'agent_operation_scheduler': 'rng agent_registry',
    'network': 'graph edges collaboration_prior', 'metrics_calculator': '',
    'result_store': 'performance_history tick_snapshots store_full_agent_snapshots',
    'module': 'client decision_provider random_seed decision_scheduler decision_collector _agents',
    'provider': 'client',
    'scheduler': 'decision_provider concurrency_limit tick_max_decisions project_max_decisions agent_max_decisions model_min_interval_ms rate_limit_cooldown_seconds rate_limit_backoff_multiplier rate_limit_skip_priority _current_tick _tick_count _project_counts _agent_counts _last_model_start _rate_limited_until _adaptive_min_interval_ms',
    'collector': '', 'sessions': 'message_bus _lock _sessions', 'bus': '_lock _queues _log',
    'pool': 'rng max_tender_invites collaboration_prior',
    'route_behaviors': 'random_seed decision_scheduler decision_collector _agents',
    'route_collector': '', 'route_provider': '',
}
_SKIP = {'events': {'_observers'}, 'module': {'client', '_native_routes'},
         'provider': {'client'}, 'sessions': {'_lock'}, 'bus': {'_lock'}}


def _inventories(anchors):
    from integration.bindings.gba_v1_native_composition import DeclaredNativeComposition
    result = {}
    for name, obj in anchors.items():
        expected = set(_FIELDS[name].split())
        if name == 'module' and type(obj) is DeclaredNativeComposition:
            expected.update('_native_routes _declared_settings_sha256 _declared_keys _source_sha256 _native_calls'.split())
        if set(vars(obj)) != expected:
            raise TaskConflict('Unsupported native component fields: ' + name)
        result[name] = sorted(expected - _SKIP.get(name, set()))
    return result


def _quiescent(engine):
    profile = engine.last_step_profile
    if (engine.current_tick < 1 or engine.current_operation not in {'tick_ready', 'completed'}
            or engine.status not in {'running', 'completed'}
            or profile.get('tick') != engine.current_tick
            or profile.get('current_operation') != engine.current_operation
            or 'failed_operation' in profile):
        raise TaskConflict('Native checkpoint requires a successfully completed tick; failed/in-progress state cannot be replayed')


def _journal(client):
    if client.tasks.path is None or client.inbox.path is None:
        raise TaskConflict('Native checkpoint requires persistent tasks and recipient inbox')
    db = client.tasks._db
    tables = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    # Table names come from the live schema and are quoted as identifiers.
    rows = {t: list(db.execute('SELECT * FROM "' + t.replace('"', '""') + '" ORDER BY rowid')) for t in tables}
    return {'task_path': str(client.tasks.path.resolve()), 'tables_sha256': task_digest(rows),
            'inbox_path': str(client.inbox.path.resolve()),
            'inbox_sha256': hashlib.sha256(client.inbox.path.read_bytes()).hexdigest(),
            'loaded_inbox_sha256': task_digest(list(client.inbox._records.values()))}


def _external_storage():
    # The original cognition service owns this database. Keep it in place; never
    # roll it back or replay its writes as part of native engine restoration.
    from gba_construction_sim.backend.storage.agent_database import agent_database
    path = Path(agent_database.db_path).resolve()
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
            for p in (path, Path(str(path) + '-wal'))}


def _identity(client, request):
    routes = client.native_routes
    return {'run_id': client.run_id, 'organization_roles': client.organization_roles,
            'initial_binding': client._native_initial_binding,
            'request_sha256': task_digest(request.model_dump(mode='json')),
            'routes_sha256': task_digest(routes.settings.model_dump(mode='json')),
            'runtime': {'python': platform.python_version(), 'platform': sys.platform,
                        'pydantic': pydantic.__version__, 'networkx': nx.__version__},
            'sources': _sources()}


def _binding_manifest(engine, client):
    from integration.module_host import module_client_implementation, module_factory_descriptor
    return {'versions': dict(client.versions), 'implementation': module_client_implementation(client),
            'observers': [module_factory_descriptor(observer, 'native.event_observer')
                          for observer in engine.events._observers]}


def _restore_client_history(client, state):
    client._calls = state['calls']
    client._request_hashes = state['request_hashes']
    client._cache = state['cache']
    client.native_routes._calls = state['route_calls']


def _consume(client, payload):
    key = 'native_checkpoint_consumed:' + payload['checkpoint_sha256']
    client.tasks._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical({
        'simulation_id': payload['simulation_id'], 'tick': payload['tick']})))


def _check_reinstallation(client, pending):
    engine = pending['engine']
    if (client._calls or client._request_hashes or client._cache
            or engine.current_tick != pending['payload']['tick']
            or engine.simulation_id != pending['payload']['simulation_id']
            or _journal(client) != pending['payload']['journal']):
        raise TaskConflict('Checkpoint reinstallation changed original clock, transport history or saved journal')
    _quiescent(engine)


def checkpoint_binding_installation_allowed(client):
    """Existing saved tasks are legal only inside the pinned reconstruction window."""
    pending = getattr(client, '_native_checkpoint_pending', None)
    if pending is None or not pending['installing']:
        return False
    _check_reinstallation(client, pending)
    return True


@contextmanager
def checkpoint_reinstallation(assembly):
    """Rebuild original applications; release business requests only on exact match.

    Constructors may read retained tasks and verify existing metadata, but cannot
    alter the journal. A failed reconstruction leaves the point unconsumed and
    requests blocked; close this client before retrying with fresh components.
    """
    client = assembly.client
    pending = getattr(client, '_native_checkpoint_pending', None)
    window = {}
    if pending is None:
        yield window
        return
    with client._lock:
        if pending['installing']:
            raise TaskConflict('Checkpoint reinstallation cannot be nested')
        _check_reinstallation(client, pending)
        pending['installing'] = True
        try:
            yield window
            assembly._validate_components()
            _check_reinstallation(client, pending)
            if (_binding_manifest(assembly.engine, client) != pending['payload']['runtime_binding']
                    or _sources() != pending['payload']['identity']['sources']):
                raise TaskConflict('Restored applications changed original handlers, versions, observers or source')
            authority = pending['payload']['authority']
            guard = window.get('read_guard')
            owner = getattr(guard, '__self__', None)
            # Constructors check the pinned initial configuration with business
            # requests blocked. Restore current authority before releasing any
            # history, request or caller-visible extension.
            with guard() if authority is not None and callable(guard) else nullcontext():
                original_authority = _restore_authority(client, authority, guard)
                try:
                    with client.tasks._transaction():
                        _check_reinstallation(client, pending)
                        _consume(client, pending['payload'])
                except BaseException:
                    if original_authority is not None:
                        vars(owner.organizations).update(original_authority)
                    raise
            _restore_client_history(client, pending['client_state'])
            client._native_checkpoint_pending = None
        finally:
            pending['installing'] = False


@contextmanager
def _guard(client, read_guard):
    if (not callable(read_guard)
            or not isinstance(getattr(client, '_native_engine_lease', None), NativeEngineLease)
            or client._native_engine_lease._file.closed):
        raise TaskConflict('Checkpoint requires its live engine lease and explicit shared writer guard')
    with read_guard(), client._lock, client.inbox._lock, client.tasks._transaction():
        yield _authority_state(client, read_guard)


def _authority_registry(snapshot):
    from src.organization.registry import OrganizationRegistry, OrganizationSnapshot
    state = OrganizationSnapshot.model_validate(snapshot)
    if state.schema_version != 'organization.v2':
        raise TaskConflict('Checkpoint authority requires its closed current organization snapshot')
    registry = OrganizationRegistry(state.run_id)
    for organization in state.organizations:
        registry.register(organization)
    for grant in state.authorizations:
        registry.authorize(grant)
    for ref in state.inactive_authorization_refs:
        registry.revoke(ref)
    return registry


def _authority_snapshot(registry):
    from src.organization.registry import OrganizationRegistry
    fields = {'run_id', '_organizations', '_actors', '_authorizations', '_inactive_authorizations'}
    if (type(registry) is not OrganizationRegistry or set(vars(registry)) != fields
            or not registry._inactive_authorizations <= registry._authorizations.keys()):
        raise TaskConflict('Checkpoint authority changes its supported registry fields or revocation history')
    snapshot = {'schema_version': 'organization.v2', 'run_id': registry.run_id,
        'organizations': [v.model_dump(mode='json') for v in registry._organizations.values()],
        'authorizations': [v.model_dump(mode='json') for v in registry._authorizations.values()],
        'inactive_authorization_refs': [registry._authorizations[k].ref.model_dump(mode='json')
                                       for k in sorted(registry._inactive_authorizations)]}
    rebuilt = _authority_registry(snapshot)
    if vars(rebuilt) != vars(registry):
        raise TaskConflict('Checkpoint authority has inconsistent original organizations, actors or grants')
    return snapshot


def _authority_state(client, read_guard):
    from integration.contractor_tender_authority_runtime import ContractorTenderAuthorityRuntime
    owner = getattr(read_guard, '__self__', None)
    if type(owner) is not ContractorTenderAuthorityRuntime:
        if getattr(getattr(owner, 'settings', None), 'organization_snapshot', None) is not None:
            raise TaskConflict('Checkpoint authority requires its original supported runtime and guard')
        return None
    owner._check()
    if owner.assembly.client is not client or read_guard != owner.read_guard:
        raise TaskConflict('Checkpoint authority changes its original client or guard')
    registry = owner.organizations
    snapshot = _authority_snapshot(registry)
    owner._publish_authority_epoch(snapshot=snapshot)
    runtime, initial = _binding_manifest(owner.assembly.engine, client), client._native_initial_binding
    if runtime['versions'] == initial['versions'] and runtime['implementation'] == initial['implementation']:
        # Manual installations have no verified extension-reconstruction window.
        expected = owner.settings.organization_snapshot.model_dump(mode='json')
        expected['schema_version'] = 'organization.v2'
        if vars(_authority_registry(expected)) != vars(registry):
            raise TaskConflict('Changed organization or authorization requires configured host reinstallation')
        return None
    return {'declaration': owner._declared, 'snapshot': snapshot}


def _restore_authority(client, saved, read_guard):
    if saved is None:
        return None
    from integration.contractor_tender_authority_runtime import ContractorTenderAuthorityRuntime
    owner = getattr(read_guard, '__self__', None)
    if (type(owner) is not ContractorTenderAuthorityRuntime or owner.assembly.client is not client
            or read_guard != owner.read_guard or set(saved) != {'declaration', 'snapshot'}
            or saved['declaration'] != owner._declared):
        raise TaskConflict('Checkpoint authority changes its original runtime, initial configuration or writer guard')
    restored = _authority_registry(saved['snapshot'])
    if restored.run_id != client.run_id:
        raise TaskConflict('Checkpoint authority changes its original run')
    owner._validate_authority_epoch(saved['snapshot'])
    original = dict(vars(owner.organizations))
    try:
        # Preserve the actual registry object shared by every source and worker.
        vars(owner.organizations).update(vars(restored))
        owner._check()
    except BaseException:
        vars(owner.organizations).update(original)
        raise
    return original


def save_native_checkpoint(assembly, *, request, path, read_guard):
    """Save under the same reentrant guard used for original engine advancement.

    This is an immutable whole-engine checkpoint, not an authority for a new
    business operation. Keep the original task/inbox files and source inputs.
    """
    engine, client = assembly.engine, assembly.client
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _guard(client, read_guard) as authority:
        client._assert_runtime_ready()
        assembly._validate_components()
        _quiescent(engine)
        anchors = _anchors(engine, client)
        inventory = _inventories(anchors)
        bus = anchors['bus']
        sessions = anchors['sessions']._sessions
        if any(e.session_id not in sessions for e in bus._log):
            raise TaskConflict('Native message bus contains another engine or unsupported session')
        codec = _Graph(anchors)
        states = {name: {field: codec.encode(getattr(obj, field)) for field in inventory[name]}
                  for name, obj in anchors.items()}
        # perf_counter has a process-local origin. Store its age, not an absolute
        # value; the wall-clock pause counts toward the original model interval.
        last_start = anchors['scheduler']._last_model_start
        payload = {'schema_version': SCHEMA, 'identity': _identity(client, request),
                   'authority': authority,
                   'runtime_binding': _binding_manifest(engine, client),
                   'journal': _journal(client), 'external_storage': _external_storage(),
                   'saved_at': time.time(), 'last_model_start_age': time.perf_counter() - last_start if last_start else None,
                   'components': {k: type(v).__module__ + ':' + type(v).__qualname__ for k, v in anchors.items()},
                   'inventory': inventory, 'states': states,
                   'client_state': codec.encode({'calls': client._calls, 'request_hashes': client._request_hashes,
                       'cache': client._cache, 'route_calls': client.native_routes._calls}),
                   'nodes': codec.nodes, 'simulation_id': engine.simulation_id, 'tick': engine.current_tick,
                   'boundary': 'Original completed tick only; reinstall original application components; no business replay.'}
        payload['checkpoint_sha256'] = task_digest(payload)
        # Exclusive creation preserves previous and failed artifacts.
        with path.open('x', encoding='utf-8', newline='\n') as out:
            out.write(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
            out.flush()
            os.fsync(out.fileno())
    return {'path': str(path.resolve()), 'checkpoint_sha256': payload['checkpoint_sha256'],
            'simulation_id': engine.simulation_id, 'tick': engine.current_tick}


def restore_native_checkpoint(engine, client, *, request, path):
    """Called only by build_module_engine before original client attachment."""
    if engine.current_tick != 0 or client.simulation_id is not None or client._calls:
        raise TaskConflict('Native restore requires fresh original components before client attachment')
    _, payload = read_json_object(path)
    if (payload.get('schema_version') != SCHEMA
            or 'authority' not in payload
            or payload.get('checkpoint_sha256') != task_digest({k: v for k, v in payload.items() if k != 'checkpoint_sha256'})
            or payload.get('identity') != _identity(client, request)):
        raise TaskConflict('Native checkpoint source, request, routes, runtime or client identity changed')
    anchors = _anchors(engine, client)
    inventory = _inventories(anchors)
    components = {k: type(v).__module__ + ':' + type(v).__qualname__ for k, v in anchors.items()}
    if payload['components'] != components or payload['inventory'] != inventory:
        raise TaskConflict('Native checkpoint component topology changed')
    # A fresh process has an empty default bus. Never replace another live
    # simulation's messages in a shared process.
    with client._lock, client.inbox._lock, client.tasks._transaction():
        if payload['journal'] != _journal(client) or payload['external_storage'] != _external_storage():
            raise TaskConflict('Original tasks, inbox or native cognition storage advanced since checkpoint')
        if anchors['bus']._log or any(anchors['bus']._queues.values()):
            raise TaskConflict('Native restore requires a fresh, empty original message bus')
        codec = _Graph(anchors)
        codec.nodes = payload['nodes']
        if set(payload['states']) != set(anchors):
            raise TaskConflict('Native checkpoint component states changed')
        decoded = {}
        for name, state in payload['states'].items():
            if set(state) != set(inventory[name]):
                raise TaskConflict('Native checkpoint state fields changed')
            decoded[name] = {k: codec.decode(v) for k, v in state.items()}
            for field, value in decoded[name].items():
                old = getattr(anchors[name], field)
                if id(old) in codec.anchor_ids and value is not old:
                    raise TaskConflict('Native checkpoint substitutes original service wiring')
        client_state = codec.decode(payload['client_state'])
        for obj in codec.decoded.values():
            if isinstance(obj, BaseModel):
                type(obj).model_validate(obj.model_dump(mode='python'))
        original = {name: {k: getattr(anchors[name], k) for k in state} for name, state in decoded.items()}
        try:
            for name, state in decoded.items():
                vars(anchors[name]).update(state)
            _quiescent(engine)
            if engine.current_tick != payload['tick'] or engine.simulation_id != payload['simulation_id']:
                raise TaskConflict('Native checkpoint tick or simulation mismatch')
            # Verify aliases and field inventories after binding decoded data.
            if _inventories(_anchors(engine, client)) != inventory:
                raise TaskConflict('Native checkpoint changes component wiring')
            age = payload['last_model_start_age']
            anchors['scheduler']._last_model_start = (time.perf_counter() - age
                - max(0, time.time() - payload['saved_at'])) if age is not None else 0.0
            runtime = payload['runtime_binding']
            initial = client._native_initial_binding
            deferred = runtime['versions'] != initial['versions'] or runtime['implementation'] != initial['implementation']
            if payload['authority'] is not None and not deferred:
                raise TaskConflict('Saved current authority requires original configured host reinstallation')
            if not deferred:
                _consume(client, payload)
        except BaseException:
            for name, state in original.items():
                vars(anchors[name]).update(state)
            raise
        if deferred:
            client._native_checkpoint_pending = {'payload': payload, 'engine': engine,
                'client_state': client_state, 'installing': False}
        else:
            _restore_client_history(client, client_state)
        client._native_checkpoint_origin = {'checkpoint_sha256': payload['checkpoint_sha256'],
            'tick': engine.current_tick, 'simulation_id': engine.simulation_id}
    return {'checkpoint_sha256': payload['checkpoint_sha256'], 'tick': engine.current_tick,
            'simulation_id': engine.simulation_id}
