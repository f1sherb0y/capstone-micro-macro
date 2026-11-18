"""Configured synthetic bank sources with a persistent local task journal."""
from integration.bank_role_contract_host import BankRoleContractSources, BankSourceValidators, _ACTIONS
from integration.role_contract_fixture_sources import RoleFixtureApplication, RoleFixtureSourceSettings
from integration.role_contract_host import RoleContractInvocation


class BankFixtureSourceSettings(RoleFixtureSourceSettings):
    """Preserve the original explicit Bank source configuration fields."""


class _BankFixtureApplication(RoleFixtureApplication):
    VERSION = 'configured-bank-fixture-sources.v1'
    ROLE = 'Bank'
    ACTIONS = _ACTIONS
    MODULE_PREFIX = 'bank'
    ASSEMBLER_PREFIX = 'Bank'


def build_sources(*, request, output_directory, offline, settings):
    """Supply only explicit offline facts; do not import tests or run business actions."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankFixtureSourceSettings.model_validate(settings).model_copy(deep=True)
    snapshot = settings.organization_snapshot
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'} or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id or snapshot.run_id != request.context.run_id
            or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
            or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
        raise ValueError('Bank fixture requires its explicit synthetic offline action/run and organization snapshot')
    application = _BankFixtureApplication(request, settings)
    try:
        return BankRoleContractSources(version=application.VERSION, registry=application.registry,
            organizations=application.organizations, store=application.store, provider=application,
            read_guard=application.read_guard, validators=BankSourceValidators(
                invocation=application.validate_invocation, wait=application.validate_wait,
                recovery=application.validate_recovery), evidence=application.evidence, close=application.close)
    except Exception:
        application.close()
        raise
