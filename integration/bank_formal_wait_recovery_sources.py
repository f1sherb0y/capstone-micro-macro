"""Explicit V7 source factory that reopens a declared original Bank application."""
from integration.bank_formal_application import (
    BankFormalApplication, BankFormalApplicationDependencies, BankFormalApplicationSettings,
)
from integration.bank_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class BankFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: BankFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = BankFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='Bank', action_ids=frozenset({'BANK-A06', 'BANK-A07', 'BANK-A08', 'BANK-A09', 'BANK-A10', 'BANK-A11', 'BANK-A12'}),
        application_type=BankFormalApplication, dependencies_type=BankFormalApplicationDependencies,
        load_factory=_load_factory, metadata_namespace='bank_formal_application:')
