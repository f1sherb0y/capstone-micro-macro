"""Explicit V7 source factory reopening a declared original Supplier application."""
from integration.supplier_formal_application import (
    SupplierFormalApplication, SupplierFormalApplicationDependencies, SupplierFormalApplicationSettings,
)
from integration.supplier_role_contract_host import _load_factory
from integration.formal_wait_recovery_sources import build_formal_wait_recovery_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId


class SupplierFormalWaitRecoverySettings(StrictRecord):
    request: RoleContractInvocation
    application: SupplierFormalApplicationSettings
    output_directory: TextId
    application_configuration_sha256: Digest
    source_task_sha256: Digest


def build_sources(*, identity, journal_path, settings):
    config = SupplierFormalWaitRecoverySettings.model_validate(settings).model_copy(deep=True)
    return build_formal_wait_recovery_sources(identity=identity, journal_path=journal_path, config=config,
        role='Supplier', action_ids=frozenset({'SUPPLIER-A01', 'SUPPLIER-A05', 'SUPPLIER-A06', 'SUPPLIER-A07', 'SUPPLIER-A08', 'SUPPLIER-A09', 'SUPPLIER-A10', 'SUPPLIER-A11', 'SUPPLIER-A12'}),
        application_type=SupplierFormalApplication, dependencies_type=SupplierFormalApplicationDependencies,
        load_factory=_load_factory, metadata_namespace='supplier_formal_application:')
