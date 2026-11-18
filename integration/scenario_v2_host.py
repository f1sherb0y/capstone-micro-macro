"""Pass checked frozen initial inputs to an explicitly selected native host."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import StringConstraints

from integration.action_catalog import write_new
from integration.scenario_v2_bootstrap import (
    ScenarioBootstrapCapabilities, prepare_scenario_v2_bootstrap,
    scenario_callback_descriptor, scenario_bootstrap_callback_descriptors,
)
from src.actions.contracts.common import EvidenceRecord, StrictRecord, TextId
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest


Digest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class ScenarioInitialConsumption(StrictRecord):
    """Native consumption lineage, independently checked against actual objects."""
    run_id: TextId
    binding_id: TextId
    binding_version: TextId
    macro_version: TextId
    snapshot_digest: Digest
    inputs_sha256: Digest
    macro_input_sha256: Digest
    organization_input_sha256s: dict[TextId, Digest]
    native_source_sha256: Digest
    native_evidence: EvidenceRecord


@dataclass(frozen=True)
class ScenarioV2Application:
    """Original native runtime and micro recipients; close remains caller-owned."""
    run_id: str
    macro_version: str
    native_runtime: object
    micro_components: dict
    store: TaskStore
    describe_consumption: Callable
    close: Callable

    def __post_init__(self):
        if (not isinstance(self.run_id, str) or not self.run_id.strip()
                or not isinstance(self.macro_version, str) or not self.macro_version.strip()
                or self.native_runtime is None or not isinstance(self.micro_components, dict)
                or not isinstance(self.store, TaskStore)
                or not callable(self.describe_consumption) or not callable(self.close)):
            raise ValueError('Scenario v2 application requires original runtime, recipients, journal, evidence and cleanup')


def build_scenario_v2_application(snapshot, *, organization_ids, callbacks, factory, specification,
        output_directory: Path, validate_consumption):
    """Explicit initialization boundary, never called automatically by preparation.

    The caller holds its actual bootstrap/source guards. The selected factory
    receives original initial_inputs and native binding metadata without any
    legacy conversion or second ledger. validate_consumption must check exact
    native identities, values/unknowns/units, recipient routing and source
    evidence using the returned actual application. It returns True.
    A new directory and immutable intent prohibit reinitialization on re-entry.
    """
    prepared = prepare_scenario_v2_bootstrap(snapshot, organization_ids=organization_ids, callbacks=callbacks)
    if prepared['status'] == 'blocked':
        return {'kind': 'blocked', 'preparation': prepared}
    if not callable(factory) or not callable(validate_consumption):
        raise TaskConflict('Scenario initialization requires explicit native factory and independent actual consumption gate')
    factory_descriptor = scenario_callback_descriptor(factory, specification)
    verifier_descriptor = scenario_callback_descriptor(validate_consumption, 'scenario_v2.actual_consumption')
    if any(item['source_sha256'] is None for item in (factory_descriptor, verifier_descriptor)):
        raise TaskConflict('Scenario initialization requires locatable original factory and verifier code')
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    intent = {'schema_version': 'scenario-v2-host-intent.v2', 'status': 'initialization_requested',
        'run_id': snapshot.run_id, 'snapshot_digest': prepared['snapshot_digest'],
        'preparation_sha256': prepared['record_sha256'], 'factory': factory_descriptor,
        'actual_consumption_gate': verifier_descriptor}
    intent['record_sha256'] = task_digest(intent)
    write_new(directory / 'intent.json', intent)
    app = None
    try:
        app = factory(initial_inputs=deepcopy(prepared['inputs']),
            binding=deepcopy(prepared['capabilities']), output_directory=directory)
        if not isinstance(app, ScenarioV2Application):
            raise TaskConflict('Initial-input factory must return its explicit original ScenarioV2Application')
        recipients = set(prepared['inputs']['organization_inputs'])
        if (app.run_id != snapshot.run_id or app.macro_version != snapshot.manifest.macro_version
                or app.store.run_id != app.run_id or app.store.path is None
                or not app.store.path.resolve().is_relative_to(directory)
                or set(app.micro_components) != recipients or set(app.store.organization_ids) != recipients):
            raise TaskConflict('Scenario application changes the original run, macro version, selected recipients or own persistent journal')
        component_ids = (app.native_runtime, app.micro_components, app.store, app.describe_consumption, app.close)
        application_callbacks = {
            'describe_consumption': scenario_callback_descriptor(app.describe_consumption, 'scenario_v2.describe_consumption'),
            'close': scenario_callback_descriptor(app.close, 'scenario_v2.close')}
        micro_components = dict(app.micro_components)
        store_run_id = app.store.run_id
        store_path = app.store.path.resolve()
        store_recipients = frozenset(app.store.organization_ids)
        store_connection = app.store._db

        def check_original_application():
            if (app.run_id != snapshot.run_id or app.macro_version != snapshot.manifest.macro_version
                    or any(left is not right for left, right in zip(component_ids,
                        (app.native_runtime, app.micro_components, app.store, app.describe_consumption, app.close)))
                    or any(scenario_callback_descriptor(getattr(app, name), 'scenario_v2.' + name) != descriptor
                        for name, descriptor in application_callbacks.items())
                    or set(app.micro_components) != set(micro_components)
                    or any(app.micro_components[key] is not value for key, value in micro_components.items())
                    or app.store.run_id != store_run_id or app.store.path is None
                    or app.store.path.resolve() != store_path
                    or not store_path.is_relative_to(directory)
                    or app.store.organization_ids != store_recipients
                    or app.store._db is not store_connection):
                raise TaskConflict('Scenario application changed its original components, journal run, path, recipients or database connection')

        consumption = ScenarioInitialConsumption.model_validate(app.describe_consumption())
        check_original_application()
        expected = {'run_id': app.run_id, 'binding_id': prepared['capabilities']['binding_id'],
            'binding_version': prepared['capabilities']['binding_version'], 'macro_version': app.macro_version,
            'snapshot_digest': prepared['snapshot_digest'], 'inputs_sha256': prepared['inputs_sha256'],
            'macro_input_sha256': task_digest(prepared['inputs']['macro_input']),
            'organization_input_sha256s': {key: task_digest(value) for key, value in prepared['inputs']['organization_inputs'].items()}}
        if (any(getattr(consumption, key) != value for key, value in expected.items())
                or consumption.native_evidence.basis_kind != 'observed'
                or consumption.native_evidence.content_hash != consumption.native_source_sha256
                or not snapshot.fixture and consumption.native_evidence.source_kind == 'synthetic'):
            raise TaskConflict('Native consumption lost original macro/micro inputs, versions or independent observed source evidence')
        if validate_consumption(application=app, preparation=deepcopy(prepared),
                consumption=consumption.model_copy(deep=True)) is not True:
            raise TaskConflict('Original native state, recipient inputs and actual consumption lineage did not verify')
        check_original_application()
        current_consumption = ScenarioInitialConsumption.model_validate(app.describe_consumption())
        current_capabilities = ScenarioBootstrapCapabilities.model_validate(callbacks.describe_current())
        # Describing consumption is also application code: check the journal
        # after this final callback before committing any metadata to it.
        check_original_application()
        if (snapshot.digest != prepared['snapshot_digest']
                or current_consumption != consumption
                or current_capabilities.model_dump(mode='json') != prepared['capabilities']
                or scenario_bootstrap_callback_descriptors(callbacks) != prepared['actual_callbacks']
                or scenario_callback_descriptor(factory, specification) != factory_descriptor
                or scenario_callback_descriptor(validate_consumption, 'scenario_v2.actual_consumption') != verifier_descriptor):
            raise TaskConflict('Original snapshot, native consumption or host/gate runtime changed during initialization')
        evidence = {'schema_version': 'scenario-v2-host-assembly.v2',
            'status': 'initial_consumption_checked_runtime_unverified',
            'preparation_sha256': prepared['record_sha256'], 'intent_sha256': intent['record_sha256'],
            'factory': factory_descriptor, 'actual_consumption_gate': verifier_descriptor,
            'application_callbacks': application_callbacks,
            'consumption': consumption.model_dump(mode='json'),
            'limitations': 'Initial input consumption only; no action, model, business execution/receipt or dynamic lifecycle closure is inferred.'}
        evidence['record_sha256'] = task_digest(evidence)
        key = 'scenario_v2_initial_consumption:' + prepared['capabilities']['binding_id']
        with app.store._transaction():
            prior = app.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if prior is not None and json.loads(prior[0]) != evidence:
                raise TaskConflict('Original scenario initial-consumption metadata changed; no silent rebootstrap')
            if prior is None:
                app.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(evidence)))
        write_new(directory / 'initial_consumption.json', evidence)
        return {'kind': 'prepared', 'application': app, 'preparation': prepared, 'evidence': evidence}
    except Exception:
        if isinstance(app, ScenarioV2Application):
            app.close()
        # Keep intent/native state intact; never reset, compensate or retry here.
        raise
