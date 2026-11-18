"""Explicit V7 source factory that reopens a declared original Engineer application."""
from integration.engineer_formal_application import (
    EngineerFormalApplication, EngineerFormalApplicationDependencies, EngineerFormalApplicationSettings,
)
from integration.engineer_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class EngineerFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: EngineerFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = EngineerFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='Engineer', action_ids=frozenset({'ENGINEER-A02', 'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A07',
            'ENGINEER-A08', 'ENGINEER-A09', 'ENGINEER-A10', 'ENGINEER-A11', 'ENGINEER-A12', 'ENGINEER-A13'}),
        application_type=EngineerFormalApplication, dependencies_type=EngineerFormalApplicationDependencies,
        load_factory=_load_factory, metadata_namespace='engineer_formal_application:')
