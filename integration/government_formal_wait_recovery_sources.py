"""Explicit V7 source factory reopening a declared original Government application."""
from integration.government_formal_application import (
    GovernmentFormalApplication, GovernmentFormalApplicationDependencies, GovernmentFormalApplicationSettings,
)
from integration.government_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class GovernmentFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: GovernmentFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = GovernmentFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='Government', action_ids=frozenset({'GOV-A03', 'GOV-A04', 'GOV-A05', 'GOV-A06', 'GOV-A07', 'GOV-A08', 'GOV-A09', 'GOV-A10', 'GOV-A11', 'GOV-A12'}),
        application_type=GovernmentFormalApplication, dependencies_type=GovernmentFormalApplicationDependencies,
        load_factory=_load_factory, metadata_namespace='government_formal_application:')
