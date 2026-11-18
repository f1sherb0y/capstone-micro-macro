"""Explicit native capability gates for same-snapshot initial input preparation."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import model_validator

from integration.scenario_v2 import ScenarioV2
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Role


class ScenarioBootstrapCapabilities(StrictRecord):
    binding_id: TextId
    binding_version: TextId
    macro_version: TextId
    schema_versions: list[TextId]
    supported_roles: list[Role]

    @model_validator(mode='after')
    def distinct_capabilities(self):
        if (len(set(self.schema_versions)) != len(self.schema_versions)
                or len(set(self.supported_roles)) != len(self.supported_roles)):
            raise ValueError('Initial-input capabilities repeat a schema or role')
        return self


class ScenarioBootstrapBlocker(StrictRecord):
    code: TextId
    detail: str
    organization_id: TextId | None = None


class ScenarioBootstrapDecision(StrictRecord):
    kind: Literal['supported', 'blocked']
    blockers: list[ScenarioBootstrapBlocker]

    @model_validator(mode='after')
    def explicit_blocking(self):
        if (self.kind == 'blocked') != bool(self.blockers):
            raise ValueError('Blocked initial inputs require concrete dependencies; supported inputs have no blockers')
        return self


@dataclass(frozen=True)
class ScenarioBootstrapCallbacks:
    """Actual read-only host callbacks; no bootstrap mutation callback is hidden.

    describe_current returns native capabilities. validate_capabilities checks
    the actual binding/source identity and returns True. validate_inputs checks
    all original seed shapes, units, unknowns, pre-project scope and identities,
    returning a typed supported/blocked decision without rewriting any seed.
    """
    describe_current: Callable
    validate_capabilities: Callable
    validate_inputs: Callable

    def __post_init__(self):
        if not all(callable(callback) for callback in (
                self.describe_current, self.validate_capabilities, self.validate_inputs)):
            raise ValueError('Scenario bootstrap preparation requires every actual capability/input gate')


def scenario_callback_descriptor(callback, specification):
    """Pin supplied source and executable code, without reading callback state."""
    return {'specification': specification, **callable_implementation(callback)}


def scenario_bootstrap_callback_descriptors(callbacks):
    return {name: scenario_callback_descriptor(getattr(callbacks, name), 'scenario_v2.' + name)
        for name in ('describe_current', 'validate_capabilities', 'validate_inputs')}


def prepare_scenario_v2_bootstrap(snapshot, *, organization_ids, callbacks):
    """Check explicit initial-input support under the caller's actual source guard.

    Both macro seeds and selected micro views remain original snapshot outputs.
    Unsupported roles are retained as blockers, never removed or relabelled.
    This function does not construct a host or bootstrap a native ledger.
    """
    if not isinstance(snapshot, ScenarioV2) or not isinstance(callbacks, ScenarioBootstrapCallbacks):
        raise TaskConflict('Scenario bootstrap requires the original frozen v2 snapshot and explicit actual callbacks')
    inputs = snapshot.initial_inputs(organization_ids)
    digest = snapshot.digest
    descriptors = scenario_bootstrap_callback_descriptors(callbacks)
    if any(descriptor['source_sha256'] is None for descriptor in descriptors.values()):
        raise TaskConflict('Scenario bootstrap actual callbacks require locatable original implementation code')
    capabilities = ScenarioBootstrapCapabilities.model_validate(callbacks.describe_current())
    if callbacks.validate_capabilities(snapshot=snapshot.model_copy(deep=True),
            capabilities=capabilities.model_copy(deep=True)) is not True:
        raise TaskConflict('Scenario bootstrap actual native capabilities or source identity did not verify')
    if capabilities.macro_version != snapshot.manifest.macro_version:
        raise TaskConflict('Initial-input binding differs from the original frozen macro version')
    blockers = []
    if snapshot.schema_version not in capabilities.schema_versions:
        blockers.append(ScenarioBootstrapBlocker(code='initial_schema_not_supported',
            detail='Actual native binding does not accept the original scenario.v2 initial-input schema'))
    # Macro input includes all original organizations, even when micro callers
    # explicitly select a smaller set. Do not silently discard any macro seed.
    for organization in snapshot.organizations:
        unsupported = sorted({assignment.role for assignment in organization.assignments}
            - set(capabilities.supported_roles))
        if unsupported:
            blockers.append(ScenarioBootstrapBlocker(code='initial_roles_not_supported',
                organization_id=organization.organization_id,
                detail='Actual native binding lacks original roles: ' + ', '.join(unsupported)))
    if blockers:
        decision = ScenarioBootstrapDecision(kind='blocked', blockers=blockers)
    else:
        decision = ScenarioBootstrapDecision.model_validate(callbacks.validate_inputs(
            inputs=deepcopy(inputs), capabilities=capabilities.model_copy(deep=True)))
        if any(blocker.organization_id is not None
                and blocker.organization_id not in {org.organization_id for org in snapshot.organizations}
                for blocker in decision.blockers):
            raise TaskConflict('Initial-input blockers refer to a foreign organization')
    current_capabilities = ScenarioBootstrapCapabilities.model_validate(callbacks.describe_current())
    if (snapshot.digest != digest or current_capabilities != capabilities
            or scenario_bootstrap_callback_descriptors(callbacks) != descriptors):
        raise TaskConflict('Original initial snapshot or actual capability/input runtime changed during its gate')
    prepared = {'schema_version': 'scenario-v2-bootstrap-preparation.v2',
        'status': 'blocked' if decision.kind == 'blocked' else 'prepared_unverified',
        'run_id': snapshot.run_id, 'snapshot_digest': digest,
        'inputs': inputs, 'inputs_sha256': task_digest(inputs),
        'capabilities': capabilities.model_dump(mode='json'),
        'decision': decision.model_dump(mode='json'), 'actual_callbacks': descriptors,
        'limitations': 'Native input preparation only; no host construction, native bootstrap, receipt or dynamic state is inferred. Blocked roles/schema remain in original inputs.'}
    prepared['record_sha256'] = task_digest(prepared)
    return prepared
