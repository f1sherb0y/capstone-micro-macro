"""Explicit synthetic Contractor A02 sources for the original durable role host."""
from typing import Literal

from integration.contractor_bid_results import ContractorBidResultWorker
from integration.contractor_role_contract_host import (
    ContractorRoleContractSources, ContractorSourceValidators, _ACTIONS,
)
from integration.role_contract_fixture_sources import RoleFixtureApplication, RoleFixtureSourceSettings
from integration.role_contract_host import RoleContractInvocation


class ContractorBidFixtureSettings(RoleFixtureSourceSettings):
    """Caller supplies original package, quantity, cost, programme and capacity views."""
    # Original A02 records lack the full source_reading used by the shared
    # fixture recovery validator. Do not grant recovery without that witness.
    allow_saved_recovery: Literal[False] = False


class _ContractorBidFixtureApplication(RoleFixtureApplication):
    VERSION = 'configured-contractor-bid-fixture-sources.v1'
    ROLE = 'Contractor'
    ACTIONS = {'CONTRACTOR-A02': _ACTIONS['CONTRACTOR-A02']}
    MODULE_PREFIX = 'contractor'
    ASSEMBLER_PREFIX = 'Contractor'
    WAIT_KIND = ContractorBidResultWorker.WAIT_KIND


def build_sources(*, request, output_directory, offline, settings):
    """Bind supplied offline facts; create no model client, publication or receipt."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = ContractorBidFixtureSettings.model_validate(settings).model_copy(deep=True)
    snapshot = settings.organization_snapshot
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or settings.action_id != 'CONTRACTOR-A02'
            or request.context.contract_ref.id != settings.action_id
            or snapshot.run_id != request.context.run_id
            or snapshot.schema_version not in {'organization.v1', 'organization.v2'}
            or snapshot.schema_version == 'organization.v1' and snapshot.inactive_authorization_refs):
        raise ValueError('Bid fixture requires explicit offline Contractor A02 and its organization snapshot')
    projection = settings.source_projection
    if (set(projection) != {'run_id', 'macro_version', 'state_version', 'read_token',
            'business_time', 'organization_id', 'objects'}
            or projection['run_id'] != request.context.run_id
            or projection['read_token'] != request.context.read_token
            or projection['business_time'] != request.context.business_time.model_dump(mode='json')
            or not isinstance(projection['objects'], list) or not projection['objects']):
        raise ValueError('Bid fixture requires a nonempty supplied projection at the original read point')
    for item in projection['objects']:
        if not isinstance(item, dict) or set(item) != {'ref', 'value'}:
            raise ValueError('Bid fixture projections require original ref/value records')
        if (isinstance(item['ref'], dict) and item['ref'].get('kind') == 'Evidence'
                and (not isinstance(item['value'], dict) or item['value'].get('source_kind') != 'synthetic')):
            raise ValueError('Bid fixture evidence must explicitly identify its synthetic origin')
    application = _ContractorBidFixtureApplication(request, settings)
    try:
        return ContractorRoleContractSources(version=application.VERSION, registry=application.registry,
            organizations=application.organizations, store=application.store, provider=application,
            read_guard=application.read_guard, validators=ContractorSourceValidators(
                invocation=application.validate_invocation, wait=application.validate_wait,
                recovery=application.validate_recovery), evidence=application.evidence, close=application.close)
    except Exception:
        application.close()
        raise
