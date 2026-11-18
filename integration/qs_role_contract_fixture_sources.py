"""Configured synthetic QS sources using the original persistent role journal."""
from integration.qs_role_contract_host import QSRoleContractSources, QSSourceValidators, _ACTIONS
from integration.role_contract_fixture_sources import RoleFixtureApplication, RoleFixtureSourceSettings
from integration.role_contract_host import RoleContractInvocation


class QSFixtureSourceSettings(RoleFixtureSourceSettings):
    """Explicit QS snapshot, projections, journal and recovery selection."""


class _QSFixtureApplication(RoleFixtureApplication):
    VERSION = 'configured-qs-fixture-sources.v1'
    ROLE = 'QS'
    ACTIONS = _ACTIONS
    MODULE_PREFIX = 'qs'
    ASSEMBLER_PREFIX = 'QS'


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = QSFixtureSourceSettings.model_validate(settings).model_copy(deep=True)
    snapshot = settings.organization_snapshot
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'} or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id or snapshot.run_id != request.context.run_id
            or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
            or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
        raise ValueError('QS fixture requires original offline action/run and independently supplied organization snapshot')
    application = _QSFixtureApplication(request, settings)
    try:
        return QSRoleContractSources(version=application.VERSION, registry=application.registry,
            organizations=application.organizations, store=application.store, provider=application,
            read_guard=application.read_guard, validators=QSSourceValidators(
                invocation=application.validate_invocation, wait=application.validate_wait,
                recovery=application.validate_recovery), evidence=application.evidence, close=application.close)
    except Exception:
        application.close()
        raise
