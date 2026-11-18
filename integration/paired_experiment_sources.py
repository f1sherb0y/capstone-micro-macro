"""Check original paired action inputs and journals without running strategies."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from integration.paired_experiments import (
    PairedActionBasis, PairedExperimentConfiguration, prepare_paired_experiment,
)
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView
from src.actions.implementation import callable_implementation
from src.actions.model_strategy import ActionDecisionOption
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskStore, task_digest


@dataclass(frozen=True)
class PairedActionSources:
    context: ActionContext
    action_input: object
    reading: ActionReadView
    options: tuple[ActionDecisionOption, ...]
    binding_version: str
    supported_choices: tuple[str, ...]


@dataclass(frozen=True)
class PairedArmSources:
    registry: ActionRegistry
    store: TaskStore
    actions: dict[str, PairedActionSources]


def paired_invocation_digest(sources, registration):
    """Keep complete own-run identity in addition to the comparable basis."""
    return task_digest({'context': sources.context.model_dump(mode='json'),
        'input': registration.contract.validate_input(sources.action_input).model_dump(mode='json'),
        'options': [{'option_id': option.option_id,
            'input': registration.contract.validate_input(option.action_input).model_dump(mode='json')}
            for option in sources.options],
        'binding_version': sources.binding_version, 'supported_choices': sources.supported_choices})


def _run_neutral(value, run_id):
    """Normalize only explicit run_id fields, preserving every other fact/ref."""
    if isinstance(value, list):
        return [_run_neutral(item, run_id) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == 'run_id':
                if item != run_id:
                    raise TaskConflict('Paired source contains a foreign run identity')
                result[key] = '<paired-run>'
            else:
                result[key] = _run_neutral(item, run_id)
        return result
    return value


def paired_action_basis(*, registry, action_id, sources):
    """Fingerprint actual authorized snapshots; binding support still needs a gate.

    The caller holds its current source guard. Option inputs are schema checked;
    this function does not execute processors, methods or option callbacks.
    """
    if not isinstance(registry, ActionRegistry) or not isinstance(sources, PairedActionSources):
        raise TaskConflict('Paired sources require original registry and typed invocation sources')
    registration = registry.get(action_id)
    context = ActionContext.model_validate(sources.context).model_copy(deep=True)
    reading = sources.reading
    if (not registration.implemented or registration.skill is None
            or not isinstance(reading, ActionReadView)
            or reading._role != registration.role
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id):
        raise TaskConflict('Paired action requires its implemented original processor, Skill and reading')
    reading.check_method_context(context, action_id)
    before = reading.method_evidence()
    data = registration.contract.validate_input(sources.action_input)
    for ref in walk_references(data):
        reading.resolve(ref)
    candidates = reading.resolve(context.candidate_set_ref)
    if not isinstance(candidates, CandidateSet):
        raise TaskConflict('Paired options lack the original authorized candidate set')
    candidates.check_context(context, registration.contract.choices)
    for candidate in candidates.candidates:
        reading.resolve(candidate.ref)
    if (not isinstance(sources.options, tuple) or not sources.options
            or any(not isinstance(option, ActionDecisionOption) for option in sources.options)
            or len({option.option_id for option in sources.options}) != len(sources.options)):
        raise TaskConflict('Paired action requires distinct original option inputs')
    options = []
    for option in sources.options:
        if not isinstance(option.option_id, str) or not option.option_id.strip():
            raise TaskConflict('Paired option identity must be explicit')
        value = registration.contract.validate_input(option.action_input)
        for ref in walk_references(value):
            reading.resolve(ref)
        options.append({'option_id': option.option_id, 'input': value.model_dump(mode='json')})
    if (not sources.supported_choices or len(set(sources.supported_choices)) != len(sources.supported_choices)
            or not set(sources.supported_choices) <= set(registration.contract.choices)):
        raise TaskConflict('Paired binding must declare supported original branches')
    grants = reading._organizations.grants(context, action_id, registration.role)
    role = registry.role_configurations[registration.role]
    skill = registration.skill
    authorization = {'context': context.model_dump(mode='json', exclude={'operation_id', 'read_token'}),
        'grants': [grant.model_dump(mode='json') for grant in grants],
        'candidate_policy': {
            'required_fields': [[choice, list(fields)] for choice, fields in registration.candidate_fields],
            'collection_fields': [[choice, list(fields)] for choice, fields in registration.candidate_collection_fields],
            'implementation': callable_implementation(registration.check_candidate_permissions),
            'selection_boundary': callable_implementation(CandidateSet.check_selected)}}
    basis = PairedActionBasis(action_id=action_id,
        input_sha256=task_digest(_run_neutral(data.model_dump(mode='json'), context.run_id)),
        authorized_facts_sha256=task_digest(_run_neutral(reading.evidence(), context.run_id)),
        authorizations_sha256=task_digest(_run_neutral(authorization, context.run_id)),
        candidate_options_sha256=task_digest(_run_neutral(options, context.run_id)),
        tools_sha256=task_digest({'role_tools': role.tool_ids, 'skill_tools': skill.manifest.tool_ids}),
        methods_sha256=task_digest({'method_refs': [ref.model_dump(mode='json') for ref in skill.manifest.method_refs],
            'registry_digest': reading._methods.content_digest if reading._methods is not None else None}),
        skill_sha256=task_digest({'manifest': skill.manifest.model_dump(mode='json'),
            'content': skill.content, 'shared_content': skill.shared_content}),
        binding_version=sources.binding_version, supported_choices=list(sources.supported_choices))
    reading.recheck()
    if task_digest(reading.method_evidence()) != task_digest(before):
        raise TaskConflict('Paired source fingerprinting cannot execute a registered method')
    return basis


def validate_paired_experiment_sources(configuration, *, output_root: Path, arms, validate_current):
    """Explicit guarded preflight; create/run no host, client, processor or store.

    validate_current(config, arm, sources, bases) must verify actual frozen
    scenario/model/policy/seed, complete relevant sources, option legality and
    endpoint support under the caller's guards. It returns True and preserves
    the authorized cache and method evidence. Session/cache/cognition isolation
    remains a later assembly gate, separate from these journal checks.
    """
    config = PairedExperimentConfiguration.model_validate(configuration)
    config = PairedExperimentConfiguration.model_validate(config.model_dump(mode='python'))
    plan = prepare_paired_experiment(config, output_root=output_root)
    if not callable(validate_current) or not isinstance(arms, dict) or set(arms) != {arm.strategy for arm in config.arms}:
        raise TaskConflict('Paired preflight requires both actual arms and independent current-source verification')
    stores = []
    paths = []
    checks = []
    originals = []
    gate_implementation = callable_implementation(validate_current)

    def recheck_sources(actual, preserved):
        for action_id, prior in preserved.items():
            sources, reading, evidence, methods, invocation_sha = prior
            if actual.actions.get(action_id) is not sources or sources.reading is not reading:
                raise TaskConflict('Paired source gate substituted its original invocation or reading')
            registration = actual.registry.get(action_id)
            if paired_invocation_digest(sources, registration) != invocation_sha:
                raise TaskConflict('Paired source gate changed original context, input, options or binding support')
            reading.check_method_context(sources.context, action_id)
            reading.recheck()
            expected = next(basis for basis in config.action_basis if basis.action_id == action_id)
            basis = paired_action_basis(registry=actual.registry, action_id=action_id, sources=sources)
            if (basis != expected or task_digest(reading.evidence()) != task_digest(evidence)
                    or task_digest(reading.method_evidence()) != task_digest(methods)):
                raise TaskConflict('Paired source gate changed the frozen comparison basis, cache or method evidence')
        if task_digest(callable_implementation(validate_current)) != task_digest(gate_implementation):
            raise TaskConflict('Paired original source validation implementation changed')
    for arm, run_plan in zip(config.arms, plan['run_plans']):
        actual = arms[arm.strategy]
        if (not isinstance(actual, PairedArmSources) or not isinstance(actual.registry, ActionRegistry)
                or not isinstance(actual.store, TaskStore) or actual.store.run_id != arm.run_id
                or actual.store.path is None or set(actual.actions) != {basis.action_id for basis in config.action_basis}):
            raise TaskConflict('Paired arm requires its original registry, persistent run journal and exact action set')
        path = actual.store.path.resolve()
        if (not path.is_relative_to(Path(run_plan['output_directory'])) or actual.store in stores
                or any(path == previous or path.exists() and previous.exists() and path.samefile(previous) for previous in paths)):
            raise TaskConflict('Paired journals must use distinct files under their own run namespaces')
        stores.append(actual.store)
        paths.append(path)
        bases = []
        preserved = {}
        for expected in config.action_basis:
            sources = actual.actions[expected.action_id]
            registration = actual.registry.get(expected.action_id)
            if (not isinstance(sources, PairedActionSources) or sources.context.run_id != arm.run_id
                    or registration.strategy != arm.strategy
                    or sources.reading.organization_id not in actual.store.organization_ids
                    or len(sources.options) > arm.model_host.max_options
                    or sources.context.execution_mode != 'llm'):
                raise TaskConflict('Paired invocation changes its actual run, recipient or configured model strategy')
            basis = paired_action_basis(registry=actual.registry, action_id=expected.action_id, sources=sources)
            if basis != expected:
                raise TaskConflict('Actual paired input, facts, permissions, options, tools, methods or Skill differs from declared basis')
            bases.append(basis.model_dump(mode='json'))
            preserved[expected.action_id] = (sources, sources.reading,
                sources.reading.evidence(), sources.reading.method_evidence(), paired_invocation_digest(sources, registration))
        originals.append((arm.strategy, actual, actual.registry, actual.store, path, arm.run_id, preserved))
        if validate_current(configuration=config.model_copy(deep=True), arm=arm.model_copy(deep=True),
                sources=actual, bases=deepcopy(bases)) is not True:
            raise TaskConflict('Paired preflight lacks actual scenario, options, model, policy or supported-endpoint verification')
        recheck_sources(actual, preserved)
        checks.append({'run_id': arm.run_id, 'strategy': arm.strategy,
            'task_store_path': path.as_posix(), 'action_basis_sha256': task_digest(bases),
            'invocation_sha256s': {action_id: prior[-1] for action_id, prior in preserved.items()},
            'source_gate_implementation': deepcopy(gate_implementation)})
    # The second arm's validator also receives application-owned objects and
    # can affect the first arm. Recheck both after every gate has returned.
    for strategy, actual, registry, store, path, run_id, preserved in originals:
        if (arms.get(strategy) is not actual or actual.registry is not registry or actual.store is not store
                or store.run_id != run_id or store.path is None or store.path.resolve() != path
                or set(actual.actions) != set(preserved)):
            raise TaskConflict('Paired source gate changed its original arm components or action set')
        recheck_sources(actual, preserved)
    result = {'schema_version': 'paired-experiment-source-check.v1',
        'status': 'sources_checked_runtime_unverified', 'plan_sha256': plan['plan_sha256'], 'arms': checks,
        'limitations': 'Guarded sources and task journals only; actual session/cache/cognition isolation, execution and outcomes remain unverified.'}
    result['record_sha256'] = task_digest(result)
    return result
