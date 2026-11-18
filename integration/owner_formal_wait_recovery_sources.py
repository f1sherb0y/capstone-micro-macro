"""Explicit V7 source factory that reopens a declared original Owner application."""
from integration.owner_formal_application import (
    OwnerFormalApplication, OwnerFormalApplicationDependencies, OwnerFormalApplicationSettings,
)
from integration.owner_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class OwnerFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: OwnerFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = OwnerFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='Owner', action_ids=frozenset({'OWN-A01', 'OWN-A02', 'OWN-A03', 'OWN-A04', 'OWN-A05', 'OWN-A08', 'OWN-A12', 'OWN-A13', 'OWN-A14', 'OWN-A15'}),
        application_type=OwnerFormalApplication, dependencies_type=OwnerFormalApplicationDependencies,
        load_factory=_load_factory, metadata_namespace='owner_formal_application:')
