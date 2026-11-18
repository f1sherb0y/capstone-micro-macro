"""Build a deterministic local host from explicitly supplied synthetic authorized facts."""
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path

from integration.macro_views import AuthorizedMacroViewAssembler
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractHost, RoleContractHostConfiguration, RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.contracts.references import ReferenceSchemaRegistry
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.registry import OrganizationRegistry, OrganizationSnapshot


class OfflineRoleContractSettings(StrictRecord):
    action_id: TextId
    schema_factory: TextId
    source_note: TextId
    organization_snapshot: OrganizationSnapshot
    source_projection: dict


class _FixtureProjectionProvider:
    def __init__(self, projection):
        self._projection = deepcopy(projection)

    def project(self, *, context, organization_id, grants):
        # The original assembler checks run/token/time/recipient and authorization.
        return deepcopy(self._projection)


def _load_schema_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Fixture schema factory requires explicit module:callable syntax')
    module_name, name = specification.split(':')
    if (not module_name.startswith(('src.actions.contracts.', 'integration.'))
            or not name.isidentifier()):
        raise ValueError('Fixture schema factory must be an explicit original project schema function')
    factory = getattr(importlib.import_module(module_name), name, None)
    if not callable(factory):
        raise ValueError('Fixture schema factory is not callable')
    return factory


def build_role_host(*, request, output_directory, offline, configuration):
    """No credentials, models, database, inferred facts or generated authorizations."""
    if offline is not True:
        raise ValueError('Configured fixture role host supports only explicit offline mode')
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = OfflineRoleContractSettings.model_validate(config.settings)
    context = request.context
    snapshot = settings.organization_snapshot
    if (context.execution_mode != 'offline_fixture' or request.execution_path not in {None, 'deterministic'}
            or settings.action_id != context.contract_ref.id or snapshot.run_id != context.run_id
            or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
            or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
        raise ValueError('Fixture role host requires the explicit original action/run and synthetic offline context')
    organizations = OrganizationRegistry(context.run_id)
    for organization in snapshot.organizations:
        organizations.register(organization)
    for authorization in snapshot.authorizations:
        organizations.authorize(authorization)
    for ref in snapshot.inactive_authorization_refs:
        organizations.revoke(ref)
    registry = register_representative_processors(ActionRegistry())
    registration = registry.get(settings.action_id)
    if not registration.implemented or registration.skill is None:
        raise ValueError('Fixture host requires the original implemented action and Skill')
    factory = _load_schema_factory(settings.schema_factory)
    descriptor = module_factory_descriptor(factory, settings.schema_factory)
    schemas = factory()
    if not isinstance(schemas, ReferenceSchemaRegistry):
        raise ValueError('Explicit fixture schema factory must return the original ReferenceSchemaRegistry')
    if module_factory_descriptor(factory, settings.schema_factory) != descriptor:
        raise ValueError('Fixture schema factory source changed during schema construction')
    source = settings.source_projection
    macro_version = source.get('macro_version')
    assembler = AuthorizedMacroViewAssembler(organizations, _FixtureProjectionProvider(source), schemas,
        macro_version=macro_version, source_mode='fixture')
    resolver = assembler.build_resolver(context, settings.action_id, registration.role)
    runner = ActionRunner(registry, organizations=organizations, references=resolver,
        model_version='offline-fixture-no-model.v1')
    evidence = {'schema_version': 'role-contract-fixture-host.v1', 'action_id': settings.action_id,
        'host_id': config.host_id, 'configuration_version': config.version,
        'source_mode': 'fixture', 'source_note': settings.source_note, 'schema_factory': descriptor,
        'organization_snapshot_sha256': task_digest(snapshot.model_dump(mode='json')),
        'source_projection_sha256': task_digest(source), 'read_token': context.read_token,
        'processor_id': registration.processor_id,
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    # This host has only in-memory registries and snapshots; no resource handles.
    return RoleContractHost(runner=runner, version='configured-role-fixture-host.v1',
        close=lambda: None, evidence=evidence)
