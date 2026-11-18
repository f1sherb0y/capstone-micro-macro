"""Explicit synthetic Supplier A08 sources for the original durable host."""
from integration.supplier_role_contract_host import (
    SupplierRoleContractSources, SupplierSourceValidators, _ACTIONS,
)
from integration.role_contract_fixture_sources import RoleFixtureApplication, RoleFixtureSourceSettings
from integration.role_contract_host import RoleContractInvocation


class SupplierLogisticsFixtureSettings(RoleFixtureSourceSettings):
    """Caller supplies dispatchable batches, receiving windows and transport reservations."""


class _SupplierLogisticsFixtureApplication(RoleFixtureApplication):
    VERSION = 'configured-supplier-logistics-fixture-sources.v1'
    ROLE = 'Supplier'
    ACTIONS = {'SUPPLIER-A08': _ACTIONS['SUPPLIER-A08']}
    MODULE_PREFIX = 'supplier'
    ASSEMBLER_PREFIX = 'Supplier'


def build_sources(*, request, output_directory, offline, settings):
    """Bind declared fixtures without physical dispatch, arrival, receipt or model calls."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = SupplierLogisticsFixtureSettings.model_validate(settings).model_copy(deep=True)
    snapshot = settings.organization_snapshot
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or settings.action_id != 'SUPPLIER-A08'
            or request.context.contract_ref.id != settings.action_id
            or snapshot.run_id != request.context.run_id
            or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
            or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
        raise ValueError('Logistics fixture requires original offline Supplier A08 and organization snapshot')
    projection = settings.source_projection
    if (set(projection) != {'run_id', 'macro_version', 'state_version', 'read_token',
            'business_time', 'organization_id', 'objects'}
            or projection['run_id'] != request.context.run_id
            or projection['read_token'] != request.context.read_token
            or projection['business_time'] != request.context.business_time.model_dump(mode='json')
            or not isinstance(projection['objects'], list) or not projection['objects']):
        raise ValueError('Logistics fixture requires a nonempty supplied projection at the original read point')
    for item in projection['objects']:
        if not isinstance(item, dict) or set(item) != {'ref', 'value'}:
            raise ValueError('Logistics fixture projections require original ref/value records')
        if (isinstance(item['ref'], dict) and item['ref'].get('kind') == 'Evidence'
                and (not isinstance(item['value'], dict) or item['value'].get('source_kind') != 'synthetic')):
            raise ValueError('Logistics fixture evidence must explicitly identify its synthetic origin')
    application = _SupplierLogisticsFixtureApplication(request, settings)
    try:
        return SupplierRoleContractSources(version=application.VERSION, registry=application.registry,
            organizations=application.organizations, store=application.store, provider=application,
            read_guard=application.read_guard, validators=SupplierSourceValidators(
                invocation=application.validate_invocation, wait=application.validate_wait,
                recovery=application.validate_recovery), evidence=application.evidence, close=application.close)
    except Exception:
        application.close()
        raise
