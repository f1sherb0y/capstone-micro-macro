"""Offline fixture reception using the shared complete original command lineage checks."""
from dataclasses import replace
from pathlib import Path

from integration.bank_execution_reception import BankExecutionReceptionSettings, _ExecutionReception as _Reception
from integration.bank_execution_results import BankExecutionResultWorker
from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.role_contract_host import RoleContractInvocation
from src.coordination.invocations import InvocationSnapshotStore


class BankExecutionReceiptFixtureSettings(BankFixtureSourceSettings):
    execution_reception: BankExecutionReceptionSettings


class _ExecutionReception(_Reception):
    def __init__(self, request, settings, sources):
        identity = settings.execution_reception.identity
        worker = BankExecutionResultWorker(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
            registry=sources.registry, client_version=identity.versions['client'], model_version=identity.versions['model'],
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)
        super().__init__(request, settings, sources, worker)


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankExecutionReceiptFixtureSettings.model_validate(settings).model_copy(deep=True)
    identity = settings.execution_reception.identity
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or settings.action_id != 'BANK-A07' or request.context.contract_ref.id != 'BANK-A07'
            or request.action_input.get('operation_context', {}).get('kind') != 'existing'
            or identity.action_id != 'BANK-A07' or identity.role != 'Bank' or identity.run_id != request.context.run_id
            or identity.organization_id != settings.source_projection['organization_id']
            or identity.request_id == request.context.operation_id or not Path(settings.journal_path).is_file()):
        raise ValueError('Execution receipt fixture requires an existing same-Bank journal and a distinct explicit existing task')
    sources = build_bank_sources(request=request, output_directory=output_directory, offline=offline,
        settings=BankFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'execution_reception'})))
    try:
        reception = _ExecutionReception(request, settings, sources)
        return replace(sources, version=reception.VERSION, prepare_execution_reception=reception.prepare, evidence=reception.evidence)
    except Exception:
        sources.close()
        raise
