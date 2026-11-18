"""Explicit V7 source factory that reopens a declared original Architect application."""
from integration.architect_formal_application import (
    ArchitectFormalApplication, ArchitectFormalApplicationDependencies, ArchitectFormalApplicationSettings,
)
from integration.architect_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class ArchitectFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: ArchitectFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = ArchitectFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='Architect', action_ids=frozenset({'ARCHITECT-A02', 'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A07',
            'ARCHITECT-A10', 'ARCHITECT-A11', 'ARCHITECT-A12', 'ARCHITECT-A13'}),
        application_type=ArchitectFormalApplication, dependencies_type=ArchitectFormalApplicationDependencies,
        load_factory=_load_factory, metadata_namespace='architect_formal_application:')
