"""Check actual run-local state adapters before paired model assembly."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from pydantic import model_validator

from integration.module_host import module_factory_descriptor
from integration.paired_experiments import Digest, PairedExperimentConfiguration, prepare_paired_experiment
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, task_digest


class PairedStateSnapshot(StrictRecord):
    """Actual adapter snapshot; the host must check component use and completeness.

    content_sha256 describes initial semantic state with only the explicit own
    run identity normalized. It excludes storage location, not history/facts.
    paths declare stable backing storage locations; their nested files may grow.
    Stateless adapters explicitly declare no state; no placeholder store is made.
    """
    run_id: TextId
    mode: Literal['persistent', 'memory', 'stateless']
    paths: list[TextId]
    content_sha256: Digest

    @model_validator(mode='after')
    def storage_mode(self):
        if (self.mode == 'persistent') != bool(self.paths):
            raise ValueError('Only persistent paired state may declare storage paths, and must provide them')
        if len(set(self.paths)) != len(self.paths):
            raise ValueError('Paired state repeats a storage path')
        if self.mode == 'stateless' and self.content_sha256 != task_digest(None):
            raise ValueError('Stateless paired state cannot hide initial history or cached content')
        return self


@dataclass(frozen=True)
class PairedStateBinding:
    component: object
    version: str
    describe_current: Callable

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version.strip() or not callable(self.describe_current):
            raise ValueError('Paired state binding requires an explicit version and actual read-only descriptor')


@dataclass(frozen=True)
class _OriginalState:
    strategy: str
    kind: str
    binding: PairedStateBinding
    component: object
    describe_current: Callable
    descriptor: dict
    snapshot: PairedStateSnapshot
    resolved_paths: tuple[Path, ...]


def _state_descriptor(binding, kind):
    return {'schema_version': 'paired-state-binding.v2', 'version': binding.version,
        'describe_current': module_factory_descriptor(binding.describe_current, 'paired.' + kind),
        'implementation': callable_implementation(binding.describe_current)}


def _read_original_state(original):
    binding = original.binding

    def check():
        if (binding.component is not original.component or binding.describe_current is not original.describe_current
                or task_digest(_state_descriptor(binding, original.kind)) != task_digest(original.descriptor)):
            raise TaskConflict('Paired state substituted its original component, descriptor or runtime implementation')

    check()
    try:
        return PairedStateSnapshot.model_validate(binding.describe_current(component=original.component))
    finally:
        check()


def _check_storage_isolation(config, plan, source_check, originals, snapshots):
    component_ids = []
    paths_by_arm = []
    for arm, run_plan, checked in zip(config.arms, plan['run_plans'], source_check['arms']):
        root = Path(run_plan['output_directory'])
        task_path = Path(checked['task_store_path']).resolve()
        if not task_path.is_relative_to(root):
            raise TaskConflict('Original checked task journal escapes its arm namespace')
        identities, paths = set(), [task_path]
        for original in originals:
            if original.strategy != arm.strategy:
                continue
            snapshot = snapshots[arm.strategy][original.kind]
            if snapshot.run_id != arm.run_id or snapshot.mode != 'stateless' and original.component is None:
                raise TaskConflict('Paired state lacks its actual own-run component')
            if snapshot.mode != 'stateless':
                identities.add(id(original.component))
            resolved = tuple(Path(name).resolve() for name in snapshot.paths)
            if resolved != original.resolved_paths or any(not path.is_relative_to(root) for path in resolved):
                raise TaskConflict('Paired state backing storage moved or escaped its original arm namespace')
            paths.extend(resolved)
        component_ids.append(identities)
        paths_by_arm.append(paths)
    if component_ids[0] & component_ids[1]:
        raise TaskConflict('Paired runs cannot reuse a stateful session/cache/cognition component')
    for left in paths_by_arm[0]:
        for right in paths_by_arm[1]:
            if (left == right or left.is_relative_to(right) or right.is_relative_to(left)
                    or left.exists() and right.exists() and left.samefile(right)):
                raise TaskConflict('Paired state storage overlaps or uses the same underlying file')


@dataclass(frozen=True)
class PairedRuntimeIsolation:
    """Retain actual adapters, allowing own state content to evolve after use.

    Callers guard the actual state; each describe_current must be read-only and
    use its original storage lock when the caller's source guard does not cover
    it. Rechecks never reset state or rerun the application isolation validator.
    """
    configuration: PairedExperimentConfiguration
    plan: dict
    source_check: dict
    states: dict
    state_maps: tuple
    originals: tuple[_OriginalState, ...]
    validate_current: Callable
    evidence: dict
    record_sha256: str

    def recheck(self, *, output_root, initial=False):
        if type(initial) is not bool:
            raise TaskConflict('Paired state recheck requires an explicit initial/current mode')
        plan = prepare_paired_experiment(self.configuration, output_root=output_root)
        if (plan['plan_sha256'] != self.plan['plan_sha256']
                or self.evidence.get('record_sha256') != self.record_sha256
                or task_digest({key: value for key, value in self.evidence.items() if key != 'record_sha256'}) != self.record_sha256
                or self.evidence.get('plan_sha256') != plan['plan_sha256']
                or self.source_check.get('record_sha256') != self.evidence.get('source_check_sha256')
                or task_digest({key: value for key, value in self.source_check.items() if key != 'record_sha256'})
                    != self.evidence.get('source_check_sha256')
                or task_digest(callable_implementation(self.validate_current))
                    != task_digest(self.evidence['actual_gate']['implementation'])
                or set(self.states) != {arm.strategy for arm in self.configuration.arms}):
            raise TaskConflict('Paired state changed its original evidence, plan, gate or arm set')
        kinds = {'session', 'cache', 'cognition'}
        for strategy, mapping in self.state_maps:
            if self.states.get(strategy) is not mapping or set(mapping) != kinds:
                raise TaskConflict('Paired state substituted its original adapter map or state categories')
        snapshots = {arm.strategy: {} for arm in self.configuration.arms}
        for original in self.originals:
            if self.states[original.strategy][original.kind] is not original.binding:
                raise TaskConflict('Paired state substituted its original adapter binding')
            if (task_digest(original.descriptor)
                    != task_digest(self.evidence['descriptors'][original.strategy][original.kind])
                    or task_digest(original.snapshot.model_dump(mode='json'))
                        != task_digest(self.evidence['snapshots'][original.strategy][original.kind])):
                raise TaskConflict('Paired retained state declaration changed its original evidence')
            snapshot = _read_original_state(original)
            current = snapshot.model_dump(mode='json')
            expected = original.snapshot.model_dump(mode='json')
            # Initial equality is required before host/action construction only.
            # Thereafter content may change independently in each own arm.
            if (initial and task_digest(current) != task_digest(expected)
                    or task_digest({key: value for key, value in current.items() if key != 'content_sha256'})
                        != task_digest({key: value for key, value in expected.items() if key != 'content_sha256'})):
                raise TaskConflict('Paired state changed its original run, mode, storage or guarded initial content')
            snapshots[original.strategy][original.kind] = snapshot
        _check_storage_isolation(self.configuration, plan, self.source_check, self.originals, snapshots)


def bind_paired_runtime_isolation(configuration, *, output_root: Path, source_check, states, validate_current):
    """Check both initial state namespaces through explicitly supplied adapters.

    The caller holds both actual guards. validate_current receives configuration,
    original states and copied snapshots; it must verify actual session/cache/
    cognition routing, run ownership, all nested storage and initial-state hashes.
    No clients, hosts, directories, stores or model calls are created here.
    """
    config = PairedExperimentConfiguration.model_validate(configuration)
    config = PairedExperimentConfiguration.model_validate(config.model_dump(mode='python'))
    plan = prepare_paired_experiment(config, output_root=output_root)
    if (not isinstance(source_check, dict) or set(source_check) != {
            'schema_version', 'status', 'plan_sha256', 'arms', 'limitations', 'record_sha256'}
            or source_check['schema_version'] != 'paired-experiment-source-check.v1'
            or source_check['status'] != 'sources_checked_runtime_unverified'
            or source_check['plan_sha256'] != plan['plan_sha256']
            or source_check['record_sha256'] != task_digest({key: value for key, value in source_check.items() if key != 'record_sha256'})
            or not isinstance(source_check['arms'], list) or len(source_check['arms']) != 2
            or not isinstance(states, dict) or set(states) != {arm.strategy for arm in config.arms}
            or not callable(validate_current)):
        raise TaskConflict('Paired isolation requires its original source-check record and both actual state adapters')
    kinds = {'session', 'cache', 'cognition'}
    snapshots = {}
    descriptors = {}
    originals = []
    state_maps = []
    gate = {'descriptor': module_factory_descriptor(validate_current, 'paired.state_isolation'),
        'implementation': callable_implementation(validate_current)}
    source_check = deepcopy(source_check)
    for arm, run_plan, checked in zip(config.arms, plan['run_plans'], source_check['arms']):
        if (not isinstance(checked, dict) or checked.get('run_id') != arm.run_id
                or checked.get('strategy') != arm.strategy or set(states[arm.strategy]) != kinds):
            raise TaskConflict('Paired state adapters change the original checked arm or omit a state category')
        state_maps.append((arm.strategy, states[arm.strategy]))
        snapshots[arm.strategy] = {}
        descriptors[arm.strategy] = {}
        for kind in sorted(kinds):
            binding = states[arm.strategy][kind]
            if not isinstance(binding, PairedStateBinding):
                raise TaskConflict('Paired state requires its original typed component binding')
            descriptor = _state_descriptor(binding, kind)
            if descriptor['implementation']['source_sha256'] is None:
                raise TaskConflict('Paired state descriptor requires locatable original implementation code')
            component, describe = binding.component, binding.describe_current
            try:
                snapshot = PairedStateSnapshot.model_validate(describe(component=component))
            finally:
                if (binding.component is not component or binding.describe_current is not describe
                        or task_digest(_state_descriptor(binding, kind)) != task_digest(descriptor)):
                    raise TaskConflict('Paired state descriptor changed its original binding during capture')
            snapshots[arm.strategy][kind] = snapshot.model_dump(mode='json')
            descriptors[arm.strategy][kind] = descriptor
            originals.append(_OriginalState(arm.strategy, kind, binding, component, describe,
                descriptor, snapshot.model_copy(deep=True), tuple(Path(name).resolve() for name in snapshot.paths)))
    typed_snapshots = {strategy: {kind: PairedStateSnapshot.model_validate(snapshot)
        for kind, snapshot in values.items()} for strategy, values in snapshots.items()}
    _check_storage_isolation(config, plan, source_check, originals, typed_snapshots)
    left, right = [snapshots[arm.strategy] for arm in config.arms]
    if any(left[kind]['mode'] != right[kind]['mode']
            or left[kind]['content_sha256'] != right[kind]['content_sha256'] for kind in kinds):
        raise TaskConflict('Paired runs require comparable initial session, cache and private cognition state')
    if validate_current(configuration=config.model_copy(deep=True), states=states,
            snapshots=deepcopy(snapshots), source_check=deepcopy(source_check)) is not True:
        raise TaskConflict('Paired isolation lacks actual routing, nested-storage and initial-history verification')
    result = {'schema_version': 'paired-experiment-isolation-check.v2',
        'status': 'isolation_checked_execution_unverified', 'plan_sha256': plan['plan_sha256'],
        'source_check_sha256': source_check['record_sha256'], 'snapshots': snapshots, 'descriptors': descriptors,
        'actual_gate': gate,
        'limitations': 'Initial state and guarded routing only; no host/client construction, model execution, macro outcome or measured advantage.'}
    result['record_sha256'] = task_digest(result)
    bound = PairedRuntimeIsolation(config.model_copy(deep=True), deepcopy(plan), source_check,
        states, tuple(state_maps), tuple(originals), validate_current, deepcopy(result), result['record_sha256'])
    bound.recheck(output_root=output_root, initial=True)
    return bound


def validate_paired_runtime_isolation(configuration, *, output_root: Path, source_check, states, validate_current):
    """Compatibility preflight API; return initial evidence, without a live host."""
    bound = bind_paired_runtime_isolation(configuration, output_root=output_root,
        source_check=source_check, states=states, validate_current=validate_current)
    return deepcopy(bound.evidence)
