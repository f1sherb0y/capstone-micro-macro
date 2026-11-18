"""Explicit synthetic Supplier A11 sources for the original durable host."""
from integration.supplier_role_contract_host import (
    SupplierRoleContractSources, SupplierSourceValidators, _ACTIONS,
)
from integration.role_contract_fixture_sources import RoleFixtureApplication, RoleFixtureSourceSettings
from integration.role_contract_host import RoleContractInvocation


class SupplierRemedyFixtureSettings(RoleFixtureSourceSettings):
    """Caller supplies order lines, installed use and explicit remedy proposals."""


class _SupplierRemedyFixtureApplication(RoleFixtureApplication):
    VERSION = 'configured-supplier-remedy-fixture-sources.v1'
    ROLE = 'Supplier'
    ACTIONS = {'SUPPLIER-A11': _ACTIONS['SUPPLIER-A11']}
    MODULE_PREFIX = 'supplier'
    ASSEMBLER_PREFIX = 'Supplier'


def build_sources(*, request, output_directory, offline, settings):
    """Bind declared fixtures without native disposition, refunds or model calls."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = SupplierRemedyFixtureSettings.model_validate(settings).model_copy(deep=True)
    snapshot = settings.organization_snapshot
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or settings.action_id != 'SUPPLIER-A11'
            or request.context.contract_ref.id != settings.action_id
            or snapshot.run_id != request.context.run_id
            or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
            or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
        raise ValueError('Remedy fixture requires original offline Supplier A11 and organization snapshot')
    projection = settings.source_projection
    if (set(projection) != {'run_id', 'macro_version', 'state_version', 'read_token',
            'business_time', 'organization_id', 'objects'}
            or projection['run_id'] != request.context.run_id
            or projection['read_token'] != request.context.read_token
            or projection['business_time'] != request.context.business_time.model_dump(mode='json')
            or not isinstance(projection['objects'], list) or not projection['objects']):
        raise ValueError('Remedy fixture requires a nonempty supplied projection at the original read point')
    for item in projection['objects']:
        if not isinstance(item, dict) or set(item) != {'ref', 'value'}:
            raise ValueError('Remedy fixture projections require original ref/value records')
        if (isinstance(item['ref'], dict) and item['ref'].get('kind') == 'Evidence'
                and (not isinstance(item['value'], dict) or item['value'].get('source_kind') != 'synthetic')):
            raise ValueError('Remedy fixture evidence must explicitly identify its synthetic origin')
    application = _SupplierRemedyFixtureApplication(request, settings)
    try:
        return SupplierRoleContractSources(version=application.VERSION, registry=application.registry,
            organizations=application.organizations, store=application.store, provider=application,
            read_guard=application.read_guard, validators=SupplierSourceValidators(
                invocation=application.validate_invocation, wait=application.validate_wait,
                recovery=application.validate_recovery), evidence=application.evidence, close=application.close)
    except Exception:
        application.close()
        raise
