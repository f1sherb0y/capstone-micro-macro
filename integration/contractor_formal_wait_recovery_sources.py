"""Explicit V7 source factory reopening a declared original Contractor application."""
from integration.contractor_formal_application import (
    ContractorFormalApplication, ContractorFormalApplicationDependencies, ContractorFormalApplicationSettings,
)
from integration.contractor_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class ContractorFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: ContractorFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = ContractorFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='Contractor', action_ids=frozenset({'CONTRACTOR-A03', 'CONTRACTOR-A04', 'CONTRACTOR-A05', 'CONTRACTOR-A06', 'CONTRACTOR-A07', 'CONTRACTOR-A09', 'CONTRACTOR-A10', 'CONTRACTOR-A11', 'CONTRACTOR-A12'}),
        application_type=ContractorFormalApplication, dependencies_type=ContractorFormalApplicationDependencies,
        load_factory=_load_factory, metadata_namespace='contractor_formal_application:')
