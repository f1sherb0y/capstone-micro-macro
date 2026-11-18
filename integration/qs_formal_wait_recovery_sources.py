"""Explicit V7 source factory reopening configured original QS waits."""
from integration.qs_formal_application import QSFormalApplication, QSFormalApplicationDependencies, QSFormalApplicationSettings
from integration.qs_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class QSFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: QSFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = QSFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='QS', action_ids=frozenset({'QS-A02', 'QS-A03', 'QS-A04', 'QS-A05', 'QS-A06', 'QS-A07', 'QS-A08', 'QS-A09', 'QS-A10', 'QS-A11', 'QS-A12', 'QS-A13'}), application_type=QSFormalApplication,
        dependencies_type=QSFormalApplicationDependencies, load_factory=_load_factory, metadata_namespace='qs_formal_application:')
