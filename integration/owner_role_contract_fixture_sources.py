"""Configured synthetic Owner sources with an original persistent task journal."""
from integration.owner_role_contract_host import OwnerRoleContractSources, OwnerSourceValidators, _ACTIONS
from integration.role_contract_fixture_sources import RoleFixtureApplication, RoleFixtureSourceSettings
from integration.role_contract_host import RoleContractInvocation


class OwnerFixtureSourceSettings(RoleFixtureSourceSettings):
    """Original supplied Owner projections, snapshot, journal and recovery selection."""


class _OwnerFixtureApplication(RoleFixtureApplication):
    VERSION = 'configured-owner-fixture-sources.v1'
    ROLE = 'Owner'
    ACTIONS = _ACTIONS
    MODULE_PREFIX = 'owner'
    ASSEMBLER_PREFIX = 'Owner'


def build_sources(*, request, output_directory, offline, settings):
    """Supply only explicit offline inputs; neither run actions nor bind native callbacks."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = OwnerFixtureSourceSettings.model_validate(settings).model_copy(deep=True)
    snapshot = settings.organization_snapshot
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'} or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id or snapshot.run_id != request.context.run_id
            or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
            or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
        raise ValueError('Owner fixture requires its explicit synthetic offline action/run and organization snapshot')
    application = _OwnerFixtureApplication(request, settings)
    try:
        return OwnerRoleContractSources(version=application.VERSION, registry=application.registry,
            organizations=application.organizations, store=application.store, provider=application,
            read_guard=application.read_guard, validators=OwnerSourceValidators(
                invocation=application.validate_invocation, wait=application.validate_wait,
                recovery=application.validate_recovery), evidence=application.evidence, close=application.close)
    except Exception:
        application.close()
        raise
