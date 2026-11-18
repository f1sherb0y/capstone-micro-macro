"""Load PLAN V1–V7 acceptance configurations without executing any scenario."""
import ast
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter, model_validator

from integration.scenario_v2 import read_input_json
from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import task_digest


Digest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
ModuleName = Annotated[str, StringConstraints(pattern=r'^integration\.[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$')]
CallableName = Annotated[str, StringConstraints(pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')]

_V4_ENTRY_LINKS = (
    'order_registration_binding', 'order_connection_assembler', 'purchase_chain_entry',
    'purchase_reconciliation_entry', 'planning_request_entries', 'revised_planning_entry',
    'mixed_planning_entry', 'mixed_chain_entry', 'mixed_task_registration',
    'purchase_planning_entry', 'purchase_registration_binding', 'order_material_chain_entry',
    'planning_material_chain_entry', 'planning_registration_binding', 'planning_connection_assembler',
    'planning_entry', 'material_connection_entry', 'logistics_connection_entry',
    'logistics_registration_entry', 'logistics_material_chain_entry', 'quality_connection_entry',
    'quality_registration_entry', 'quality_logistics_material_chain_entry',
    'production_connection_entry', 'production_registration_entry', 'production_material_chain_entry',
)
_V4_SOURCE_LINKS = ('quality_dispatch_source', 'production_quality_source')


class LifecycleEntryLink(StrictRecord):
    module: ModuleName
    callable: CallableName
    status: Literal['implemented_unverified']
    action_id: TextId | None = None
    choice: TextId | None = None
    input: TextId | None = None
    inputs: dict[TextId, TextId] = Field(default_factory=dict)
    seed: TextId | None = None
    order_seed: TextId | None = None
    planning_seed: TextId | None = None
    production_seed: TextId | None = None
    purchase_seed: TextId | None = None
    quality_seed: TextId | None = None
    logistics_seed: TextId | None = None
    pending_production_input: TextId | None = None
    pending_purchase_input: TextId | None = None
    default_mode: Literal['plan_only'] | None = None
    mode: Literal['configuration_only', 'binding_only'] | None = None
    seed_status: Literal['input_prepared_execution_pending'] | None = None
    requires: list[TextId] = Field(default_factory=list)
    scope: TextId | None = None


class LifecycleSourceLink(StrictRecord):
    factory: TextId
    version: TextId
    status: Literal['implemented_unverified']
    requires: list[TextId] = Field(default_factory=list)


class LifecycleChronologicalInputs(StrictRecord):
    origin: Literal['synthetic']
    status: Literal['input_prepared_execution_pending']
    production: TextId
    quality: TextId
    logistics: TextId
    receiving: TextId
    quality_seed: TextId
    logistics_seed: TextId
    material_seed: TextId
    production_receipt_seed: TextId
    timeline: dict[TextId, Annotated[int, Field(strict=True, ge=0)]]

# Explicitly supported input formats; a new filename/prefix cannot silently
# declare another scenario or action. These are input links, not passing cases.
_SPECIALIZED_CASE_ACTIONS = {
    ('V5', 'lifecycle-v5-credit-input-case.v1'): 'BANK-A03',
    ('V5', 'lifecycle-v5-quote-input-case.v1'): 'BANK-A04',
    ('V5', 'lifecycle-v5-owner-accept-input-case.v1'): 'OWN-A05',
    ('V5', 'lifecycle-v5-arrangement-input-case.v1'): 'BANK-A05',
    ('V5', 'lifecycle-v5-owner-draw-input-case.v1'): 'OWN-A06',
    ('V5', 'lifecycle-v5-draw-input-case.v1'): 'BANK-A06',
    ('V5', 'lifecycle-v5-execution-input-case.v1'): 'BANK-A07',
    ('V5', 'lifecycle-v5-reconcile-input-case.v1'): 'BANK-A07',
    ('V5', 'lifecycle-v5-owner-reconcile-input-case.v1'): 'OWN-A06',
    ('V5', 'lifecycle-v5-owner-payment-input-case.v1'): 'OWN-A06',
    ('V5', 'lifecycle-v5-qs-payment-calculation-input-case.v1'): 'QS-A08',
    ('V5', 'lifecycle-v5-qs-payment-verify-input-case.v1'): 'QS-A08',
    ('V5', 'lifecycle-v5-qs-payment-calculation-input-case.v2'): 'QS-A08',
    ('V5', 'lifecycle-v5-qs-payment-verify-input-case.v2'): 'QS-A08',
    ('V5', 'lifecycle-v5-qs-certification-input-case.v1'): 'QS-A08',
    ('V7', 'lifecycle-v7-bank-shortfall-input-case.v1'): 'BANK-A07',
}


class LifecycleActionRequirement(StrictRecord):
    action_id: TextId
    source_sha256: Digest
    required_choices: Annotated[list[TextId], Field(min_length=1)]
    required_checks: Annotated[list[TextId], Field(min_length=1)]
    fixture_candidates: list[TextId]


class LifecycleScenario(StrictRecord):
    scenario_id: Literal['V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7']
    title: TextId
    requirements: Annotated[list[LifecycleActionRequirement], Field(min_length=1)]
    acceptance_behaviors: Annotated[list[TextId], Field(min_length=1)]
    input_cases: list[TextId] = Field(default_factory=list)
    limitations: str
    entry_links: dict[TextId, LifecycleEntryLink] = Field(default_factory=dict)
    source_links: dict[TextId, LifecycleSourceLink] = Field(default_factory=dict)
    connection_seeds: list[TextId] = Field(default_factory=list)
    chronological_input_set: LifecycleChronologicalInputs | None = None

    @model_validator(mode='before')
    @classmethod
    def legacy_v4_links(cls, value):
        """Normalize only the existing named declarations; unknown fields fail."""
        if not isinstance(value, dict):
            return value
        result = dict(value)
        for field, names in (('entry_links', _V4_ENTRY_LINKS), ('source_links', _V4_SOURCE_LINKS)):
            present = [name for name in names if name in result]
            if not present:
                continue
            if result.get('scenario_id') != 'V4':
                raise ValueError('Legacy V4 links require their original V4 scenario')
            links = dict(result.get(field, {}))
            for name in present:
                if name in links:
                    raise ValueError('Lifecycle declaration repeats a normalized entry link')
                links[name] = result.pop(name)
            result[field] = links
        return result


class LifecycleScenarioCatalogue(StrictRecord):
    schema_version: Literal['plan-lifecycle-scenarios.v1']
    status: Literal['configured_unverified']
    scenarios: Annotated[list[LifecycleScenario], Field(min_length=7, max_length=7)]


def load_lifecycle_scenarios(path: Path, *, root: Path) -> dict:
    """Validate source-card/branch links and list still-needed scenario inputs.

    Candidate fixtures are existing independent inputs, not a connected business
    chain. Source CHECK IDs remain requirements, never inferred passing evidence.
    This does not instantiate an action registry, schema factory, worker or model.
    """
    root = Path(root).resolve()
    text, _ = read_input_json(path)
    catalogue = LifecycleScenarioCatalogue.model_validate_json(text)
    if {row.scenario_id for row in catalogue.scenarios} != {'V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7'}:
        raise ValueError('Lifecycle catalogue requires each PLAN V1–V7 scenario exactly once')
    _, inventory = read_input_json(root / 'config/action_registry.json')
    actions = {row['action_id']: row for row in inventory['actions']}
    fixture_cache, module_cache = {}, {}

    def fixture_snapshot(name):
        if name not in fixture_cache:
            fixture = (root / name).resolve()
            if Path(name).is_absolute() or not fixture.is_relative_to(root / 'tests/fixtures/roles'):
                raise ValueError('Lifecycle input must stay in the original role-fixture directory')
            _, payload = read_input_json(fixture)
            fixture_cache[name] = (payload, {'path': name, 'content_sha256': task_digest(payload)})
        return fixture_cache[name]

    def entry_source(module, function):
        TypeAdapter(ModuleName).validate_python(module)
        TypeAdapter(CallableName).validate_python(function)
        if module not in module_cache:
            path = (root / (module.replace('.', '/') + '.py')).resolve()
            if not path.is_relative_to(root / 'integration'):
                raise ValueError('Lifecycle entry source escapes the integration directory')
            raw = path.read_bytes()
            tree = ast.parse(raw, filename=str(path))
            names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            module_cache[module] = (names, {'path': path.relative_to(root).as_posix(),
                'source_sha256': hashlib.sha256(raw).hexdigest()})
        names, snapshot = module_cache[module]
        if function not in names:
            raise ValueError('Lifecycle entry lacks its declared original top-level function')
        return dict(snapshot)

    result = []
    for scenario in catalogue.scenarios:
        ids = [row.action_id for row in scenario.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError('Lifecycle scenario repeats an action requirement')
        requirements = []
        for requirement in scenario.requirements:
            original = actions.get(requirement.action_id)
            if (original is None or original['source_sha256'] != requirement.source_sha256
                    or len(set(requirement.required_choices)) != len(requirement.required_choices)
                    or set(requirement.required_choices) != set(original['choices'])
                    or len(set(requirement.required_checks)) != len(requirement.required_checks)
                    or set(requirement.required_checks) != set(original['checks'] + original['role_checks'])):
                raise ValueError('Lifecycle requirement changes the original action source, branches or CHECK set')
            fixtures = []
            for name in requirement.fixture_candidates:
                _, snapshot = fixture_snapshot(name)
                fixtures.append({**snapshot,
                    'status': 'candidate_not_connected_or_validated'})
            requirements.append({'action_id': requirement.action_id,
                'required_choices': requirement.required_choices, 'required_checks': requirement.required_checks,
                'fixture_candidates': fixtures, 'connected_input_status': 'missing',
                'branch_validation_status': 'pending', 'native_binding_status': 'unverified'})
        input_cases = []
        for name in scenario.input_cases:
            case, snapshot = fixture_snapshot(name)
            schema = case.get('schema_version')
            specialized_action = _SPECIALIZED_CASE_ACTIONS.get((scenario.scenario_id, schema))
            if (schema != 'lifecycle-input-case.v1' and specialized_action is None
                    or case.get('scenario_id') != scenario.scenario_id or case.get('origin') != 'synthetic'
                    or not isinstance(case.get('steps'), list) or not case['steps']
                    or any(not isinstance(step, dict) for step in case['steps'])):
                raise ValueError('Lifecycle input case requires explicit matching synthetic scenario steps')
            if any(step.get('action_id') not in ids for step in case['steps']):
                raise ValueError('Lifecycle input case refers to an action outside its declared scenario')
            if specialized_action is not None and any(step.get('action_id') != specialized_action for step in case['steps']):
                raise ValueError('Specialized lifecycle input format changes its declared original action')
            input_cases.append({**snapshot,
                'schema_version': schema, 'action_ids': sorted({step['action_id'] for step in case['steps']}),
                'status': 'input_prepared_execution_pending'})
        row = {'scenario_id': scenario.scenario_id, 'title': scenario.title,
            'requirements': requirements, 'acceptance_behaviors': scenario.acceptance_behaviors,
            'input_cases': input_cases,
            'status': 'scenario_inputs_and_execution_pending'}
        if scenario.entry_links:
            row['entry_links'] = {}
            for name, link in scenario.entry_links.items():
                if link.action_id is not None and link.action_id not in ids:
                    raise ValueError('Lifecycle entry action is outside its original scenario')
                choice_actions = [link.action_id] if link.action_id is not None else ids
                if any(not any(choice in actions[action_id]['choices'] for action_id in choice_actions)
                        for choice in ([link.choice] if link.choice is not None else []) + list(link.inputs)):
                    raise ValueError('Lifecycle entry declares a branch outside its scenario action requirements')
                paths = [getattr(link, key) for key in ('input', 'seed', 'order_seed', 'planning_seed',
                    'production_seed', 'purchase_seed', 'quality_seed', 'logistics_seed',
                    'pending_production_input', 'pending_purchase_input') if getattr(link, key) is not None]
                paths.extend(link.inputs.values())
                row['entry_links'][name] = {'declaration': link.model_dump(mode='json', exclude_none=True),
                    'source': entry_source(link.module, link.callable),
                    'linked_inputs': [dict(fixture_snapshot(path)[1]) for path in dict.fromkeys(paths)],
                    'status': 'implemented_unverified'}
        if scenario.source_links:
            row['source_links'] = {}
            for name, link in scenario.source_links.items():
                parts = link.factory.split(':')
                if len(parts) != 2:
                    raise ValueError('Lifecycle factory requires its explicit module:callable')
                row['source_links'][name] = {'declaration': link.model_dump(mode='json'),
                    'source': entry_source(*parts), 'status': 'implemented_unverified'}
        if scenario.connection_seeds:
            if len(set(scenario.connection_seeds)) != len(scenario.connection_seeds):
                raise ValueError('Lifecycle connection seed is repeated')
            row['connection_seeds'] = [dict(fixture_snapshot(name)[1]) for name in scenario.connection_seeds]
        if scenario.chronological_input_set is not None:
            chronology = scenario.chronological_input_set.model_dump(mode='json')
            row['chronological_input_set'] = {'declaration': chronology,
                'linked_inputs': [dict(fixture_snapshot(name)[1]) for key, name in chronology.items()
                    if key not in {'origin', 'status', 'timeline'}],
                'status': 'input_prepared_execution_pending'}
        result.append(row)
    report = {'schema_version': 'plan-lifecycle-scenario-inventory.v1',
        'status': 'configured_unverified', 'catalogue_sha256': task_digest(catalogue.model_dump(mode='json')),
        'scenarios': result,
        'limitations': 'Representative lifecycle scenario requirements; all 106 actions remain in PLAN scope. No fixture is promoted to a connected chain, passed CHECK, native effect or execution evidence.'}
    report['record_sha256'] = task_digest(report)
    return report
