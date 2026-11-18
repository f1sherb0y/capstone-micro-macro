"""Explicit local action entry point; produces decisions and audits, no macro receipts."""
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from integration.module_host import module_factory_descriptor
from integration.sessions import atomic_json
from integration.scenario_v2 import read_input_json
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.actions.runner import ActionRunner, JsonlActionAuditSink
from src.coordination.tasks import TaskConflict, task_digest


class RoleContractInvocation(StrictRecord):
    schema_version: Literal['role-contract-invocation.v1']
    context: ActionContext
    action_input: dict
    execution_path: Literal['deterministic', 'single_agent', 'organization_discussion'] | None = None


class RoleContractHostConfiguration(StrictRecord):
    schema_version: Literal['role-contract-host-config.v1']
    host_id: TextId
    version: TextId
    settings: dict


@dataclass(frozen=True)
class RoleContractExecution:
    """Original action result plus evidence from an explicit durable executor."""
    result: object
    evidence: dict

    def __post_init__(self):
        if not isinstance(self.evidence, dict):
            raise ValueError('Role contract execution evidence must be an object')


@dataclass(frozen=True)
class RoleContractHost:
    """Host owns actual authorized snapshots, processors, strategies and cleanup."""
    runner: ActionRunner
    version: str
    close: Callable
    evidence: dict = field(default_factory=dict)
    execute: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.runner, ActionRunner) or not isinstance(self.version, str)
                or not self.version.strip() or not callable(self.close) or not isinstance(self.evidence, dict)
                or self.execute is not None and not callable(self.execute)):
            raise ValueError('Role contract host requires the original runner, explicit version and cleanup')


def _load_role_json(path):
    _, data = read_input_json(path)
    return data


def load_role_contract_invocation(path):
    return RoleContractInvocation.model_validate(_load_role_json(path))


def load_role_contract_host_configuration(path):
    return RoleContractHostConfiguration.model_validate(_load_role_json(path))


def prepare_role_contract_options(*, model_host, prepared):
    """Called under the role's original read guard, before task execution.

    A separate reading preserves the prepared invocation's original evidence
    digest. It retains the actual method registry for source fingerprints, with
    method execution disabled until the original full action processor runs.
    """
    if model_host is None:
        return None
    from integration.action_model_host import ActionModelHost

    runner, context = prepared.runner, prepared.context
    if (not isinstance(model_host, ActionModelHost) or model_host.registry is not runner.registry
            or model_host.store.run_id != context.run_id or runner.run_id != context.run_id):
        raise TaskConflict('Option preparation must use the original role runner, registry and journal run')
    registration = runner.registry.get(context.contract_ref.id)
    source = model_host._source(registration)
    if source.prepare_invocation is None:
        return None
    if (context.execution_mode != 'llm' or runner.references is not prepared.reading._resolver
            or runner.organizations is not prepared.reading._organizations
            or not any(runner.decision_strategies.get(registration.strategy) is binding
                for binding in model_host.bindings)):
        raise TaskConflict('Option preparation changed the original model strategy or authorized source boundary')
    def original_identity():
        return (task_digest(context.model_dump(mode='json')),
            task_digest(prepared.action_input.model_dump(mode='json')),
            task_digest(prepared.reading.evidence()))
    expected = (prepared.context_sha256, prepared.input_sha256, prepared.reading_sha256)
    if original_identity() != expected:
        raise TaskConflict('Option preparation requires the unchanged original prepared invocation')
    prepared.reading.check_method_context(context, registration.action_id)
    prepared.reading.recheck()
    try:
        return runner.prepare_decision(context=context, action_input=prepared.action_input, reading=prepared.reading)
    finally:
        prepared.reading.recheck()
        if original_identity() != expected:
            raise TaskConflict('Option preparation changed the original invocation or prepared source evidence')


def run_role_contract(*, request, factory, specification, output_directory, offline, configuration=None):
    """Execute once in a new directory; interrupted attempts are never silently replayed."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if configuration is not None:
        configuration = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    expected_mode = 'offline_fixture' if offline else 'llm'
    if request.context.execution_mode != expected_mode:
        raise ValueError('Role contract model mode must match the explicit invocation mode')
    if offline and request.execution_path not in {None, 'deterministic'}:
        raise ValueError('Offline role contract execution requires the deterministic path')
    if not offline and request.execution_path == 'deterministic':
        raise ValueError('LLM role contract execution requires an explicitly bound model strategy')
    directory = Path(output_directory)
    descriptor = module_factory_descriptor(factory, specification)
    # Exclusive creation is the local CLI replay guard, including factory failures.
    directory.mkdir(parents=True, exist_ok=False)
    payload = request.model_dump(mode='json')
    attempt = {'schema_version': 'role-contract-attempt.v1', 'run_id': request.context.run_id,
        'operation_id': request.context.operation_id, 'action_id': request.context.contract_ref.id,
        'request_sha256': task_digest(payload), 'factory': descriptor,
        'configuration': {'host_id': configuration.host_id, 'version': configuration.version,
            'sha256': task_digest(configuration.model_dump(mode='json'))} if configuration is not None else None,
        'status': 'started'}
    atomic_json(directory / 'invocation.json', payload)
    atomic_json(directory / 'attempt.json', attempt)
    host = None
    runner = None
    original_sink = None
    try:
        kwargs = {'request': request.model_copy(deep=True), 'output_directory': directory, 'offline': offline}
        if configuration is not None:
            kwargs['configuration'] = configuration.model_copy(deep=True)
        host = factory(**kwargs)
        if not isinstance(host, RoleContractHost):
            raise ValueError('Role contract factory must return RoleContractHost')
        runner = host.runner
        original_sink = runner.audit_sink
        if module_factory_descriptor(factory, specification) != descriptor:
            raise ValueError('Role contract factory source changed during host construction')
        if (runner.run_id != request.context.run_id or runner.organizations is None
                or runner.references is None or runner.references.run_id != request.context.run_id
                or runner.references.source_mode != ('fixture' if offline else 'formal')):
            raise ValueError('Role contract host requires original same-run organizations and authorized source resolver')
        registration = runner.registry.get(request.context.contract_ref.id)
        if not registration.implemented or registration.skill is None:
            raise ValueError('Role contract action requires its implemented processor and original Skill')
        if not offline and registration.strategy not in runner.decision_strategies:
            raise ValueError('Role contract LLM host lacks its explicitly selected action strategy')
        sink = JsonlActionAuditSink(directory / 'actions.jsonl', run_id=request.context.run_id)

        def audit(record):
            sink(record)
            if original_sink is not None:
                original_sink(record)

        runner.audit_sink = audit
        start = len(runner.audit_records)
        execution_evidence = None
        if host.execute is None:
            result = runner.run_action(request.context, request.action_input, execution_path=request.execution_path)
        else:
            execution = host.execute(request.model_copy(deep=True))
            if not isinstance(execution, RoleContractExecution):
                raise ValueError('Role contract executor must return its original result and explicit evidence')
            result = registration.contract.result_adapter.validate_python(execution.result)
            execution_evidence = deepcopy(execution.evidence)
        records = [record.as_dict() for record in runner.audit_records[start:]]
        evidence = {'macro_mode': 'role_contract', 'requested_model_mode': 'offline' if offline else 'llm',
            'run_id': request.context.run_id, 'action_id': registration.action_id,
            'request_sha256': attempt['request_sha256'], 'factory': descriptor,
            'configuration': deepcopy(attempt['configuration']), 'host_evidence': deepcopy(host.evidence),
            'host_version': host.version, 'source_mode': runner.references.source_mode,
            'result': result.model_dump(mode='json'), 'audit': records,
            'macro_execution': 'not_performed',
            'limitations': ['Local action decision only; no macro submission, formal effect or receipt.']}
        if execution_evidence is not None:
            evidence['execution_evidence'] = execution_evidence
        # Preserve the actual result before recording the terminal attempt status.
        atomic_json(directory / 'result.json', evidence)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'result_saved',
            'host_version': host.version, 'result_sha256': task_digest(evidence)})
        return evidence
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise
    finally:
        if runner is not None:
            runner.audit_sink = original_sink
        if isinstance(host, RoleContractHost):
            host.close()
