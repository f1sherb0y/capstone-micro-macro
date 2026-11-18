"""Generate explicit tender assembly configuration without starting an application."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from integration.contractor_tender_application import (
    ContractorTenderApplicationSettings, TenderProfessionalCallback, TenderProfessionalCallbacks,
)
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings
from integration.contractor_tender_cost_validation import TenderCostValidationSettings
from integration.contractor_tender_exposure_validation import TenderExposureValidationSettings
from integration.contractor_tender_indicators import TenderIndicatorValidationSettings
from integration.contractor_tender_final_validation import TenderFinalValidationSettings
from integration.contractor_tender_handoff_validation import TenderHandoffValidationSettings
from integration.contractor_tender_module_host import ContractorTenderModuleSettings
from integration.contractor_tender_programme_validation import TenderProgrammeValidationSettings
from integration.contractor_tender_publication_validation import TenderPublicationValidationSettings
from integration.contractor_tender_quantity_validation import TenderQuantityValidationSettings
from integration.contractor_tender_snapshot_sources import ContractorTenderSnapshotSettings
from integration.contractor_tender_source_factory import (
    ContractorTenderCurrentValidationSettings, ContractorTenderNativePublicationSettings,
    ContractorTenderSelectorSettings, ContractorTenderSourceFactorySettings,
)
from integration.module_host import GbaModuleHostConfiguration
from src.actions.contracts.common import StrictRecord, TextId


class TenderProfessionalConfiguration(StrictRecord):
    versions: dict[TextId, TextId]
    publication: TenderPublicationValidationSettings
    quantity: TenderQuantityValidationSettings
    cost: TenderCostValidationSettings
    handoff: TenderHandoffValidationSettings
    exposure: TenderExposureValidationSettings | TenderIndicatorValidationSettings
    final: TenderFinalValidationSettings
    programme: TenderProgrammeValidationSettings | None = None
    mapping: TenderExposureValidationSettings | TenderIndicatorValidationSettings | None = None


class TenderModuleConfigurationInput(StrictRecord):
    schema_version: Literal['contractor-tender-configuration-input.v1']
    host_id: TextId
    version: TextId
    source_version: TextId
    application_version: TextId
    macro_version: TextId
    proposal_client_version: TextId
    final_client_version: TextId
    policy_version: TextId
    mode: Literal['offline', 'llm']
    authority: TenderAuthorityRuntimeSettings
    snapshots: ContractorTenderSnapshotSettings
    quantity_snapshots: ContractorTenderSnapshotSettings
    task_selector: ContractorTenderSelectorSettings
    current_validation: ContractorTenderCurrentValidationSettings
    professional: TenderProfessionalConfiguration
    native_publication: ContractorTenderNativePublicationSettings | None = None
    model_host_factory: TextId | None = None
    model_host_settings: dict = Field(default_factory=dict)
    allow_saved_recovery: bool = False
    continue_unstarted_actions_on_error: bool = False
    publish_native_clarification_requests: bool = False
    request_work_factory: TextId | None = None
    request_recovery_factory: TextId | None = None
    request_work_settings: dict = Field(default_factory=dict)


_CALLBACKS = {
    'publication': 'integration.contractor_tender_publication_validation:validate_publication',
    'quantity': 'integration.contractor_tender_quantity_validation:validate_quantity_relation',
    'cost': 'integration.contractor_tender_cost_validation:validate_cost_adoption',
    'handoff': 'integration.contractor_tender_handoff_validation:validate_handoff',
    'exposure': 'integration.contractor_tender_exposure_validation:validate_exposure',
    'final': 'integration.contractor_tender_final_validation:validate_final',
    'programme': 'integration.contractor_tender_programme_validation:validate_programme',
    'mapping': 'integration.contractor_tender_exposure_validation:validate_mapping',
}


def build_configuration(inputs):
    """Bind existing concrete callbacks and mandatory native current validation.

    This validates configuration structure only. It neither reads/creates real
    evidence nor asserts file validity, native capabilities or completed work.
    Building an llm configuration does not instantiate a model or call an API.
    """
    inputs = TenderModuleConfigurationInput.model_validate(inputs).model_copy(deep=True)
    if inputs.proposal_client_version == inputs.final_client_version:
        raise ValueError('Tender proposal and final client versions must be distinct')
    if inputs.mode == 'offline' and (inputs.model_host_factory is not None or inputs.model_host_settings):
        raise ValueError('Offline tender configuration cannot include a model host')
    if inputs.mode == 'llm' and inputs.model_host_factory is None:
        raise ValueError('LLM tender configuration requires an explicit existing model host factory')
    if inputs.model_host_factory is not None:
        parts = inputs.model_host_factory.split(':')
        if len(parts) != 2 or not parts[0] or not parts[1].isidentifier():
            raise ValueError('Model host factory requires explicit module:callable syntax')
    names = {name for name in _CALLBACKS if getattr(inputs.professional, name) is not None}
    if set(inputs.professional.versions) != names:
        raise ValueError('Professional versions must match every configured callback exactly')
    callbacks = {}
    for name in names:
        settings = getattr(inputs.professional, name)
        symbol = _CALLBACKS[name]
        if isinstance(settings, TenderIndicatorValidationSettings):
            symbol = 'integration.contractor_tender_indicators:validate_' + name
        callbacks[name] = TenderProfessionalCallback(symbol=symbol,
            version=inputs.professional.versions[name], settings=settings.model_dump(mode='json'))
    if inputs.request_work_factory is not None and inputs.professional.mapping is None:
        raise ValueError('Request-driven tender configuration requires a pre-selection mapping validator')
    if inputs.professional.final.use_request_trigger and inputs.request_work_factory is None:
        raise ValueError('Trigger-sourced final validation requires an explicitly configured request producer')
    if inputs.request_work_factory == 'integration.contractor_tender_request_sources:build_request_work':
        from integration.contractor_tender_request_sources import TenderRequestSourcesSettings
        from integration.contractor_tender_handoff_validation import TenderHandoffRequestSource

        plans = TenderRequestSourcesSettings.model_validate(inputs.request_work_settings)
        for plan in plans.requests:
            if plan.bid_plan is None:
                continue
            selected = inputs.professional.handoff.handoffs.get(plan.bid_plan.bid_context.operation_id)
            if isinstance(selected, TenderHandoffRequestSource):
                expected_request = f'proposal-tick{plan.tick}-{plan.project_id}-{plan.organization_id}-consider_tender'
                if (plan.handoff_production is None or selected.project_id != plan.project_id
                        or selected.request_id != expected_request):
                    raise ValueError('Request-sourced handoff requires matching runtime production and the same native request')
            elif plan.handoff_production is not None:
                raise ValueError('Runtime handoff production requires the request-sourced handoff validator')
    application = ContractorTenderApplicationSettings(version=inputs.application_version,
        authority=inputs.authority, professional=TenderProfessionalCallbacks(**callbacks),
        model_host_factory=inputs.model_host_factory, model_host_settings=inputs.model_host_settings,
        allow_saved_recovery=inputs.allow_saved_recovery,
        continue_unstarted_actions_on_error=inputs.continue_unstarted_actions_on_error,
        publish_native_clarification_requests=inputs.publish_native_clarification_requests,
        request_recovery_factory=inputs.request_recovery_factory,
        request_work_factory=inputs.request_work_factory, request_work_settings=inputs.request_work_settings)
    sources = ContractorTenderSourceFactorySettings(version=inputs.source_version,
        application_factory='integration.contractor_tender_application:build_application',
        application_version=application.version, application_settings=application.model_dump(mode='json'),
        snapshots=inputs.snapshots, quantity_snapshots=inputs.quantity_snapshots,
        task_selector=inputs.task_selector, current_validation=inputs.current_validation,
        native_publication=inputs.native_publication)
    module = ContractorTenderModuleSettings(source_factory='integration.contractor_tender_source_factory:build_sources',
        source_version=sources.version, source_settings=sources.model_dump(mode='json'),
        macro_version=inputs.macro_version, proposal_client_version=inputs.proposal_client_version,
        final_client_version=inputs.final_client_version, policy_version=inputs.policy_version)
    return GbaModuleHostConfiguration(schema_version='gba-module-host-config.v1',
        host_id=inputs.host_id, version=inputs.version, settings=module.model_dump(mode='json'))


def load_configuration_input(path):
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Tender configuration input repeats a JSON field')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('Tender configuration input requires finite JSON values')

    raw = json.loads(Path(path).read_text(encoding='utf-8-sig'),
        object_pairs_hook=unique_object, parse_constant=reject_constant)
    return TenderModuleConfigurationInput.model_validate_json(json.dumps(raw, allow_nan=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate Contractor tender assembly configuration only')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    configuration = build_configuration(load_configuration_input(args.input))
    data = (json.dumps(configuration.model_dump(mode='json'), ensure_ascii=False, indent=2, allow_nan=False)
        + '\n').encode('utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve existing configurations and evidence; never silently replace one.
    with args.output.open('xb') as destination:
        destination.write(data)
    print(json.dumps({'status': 'configuration_only_unverified', 'path': str(args.output),
        'sha256': hashlib.sha256(data).hexdigest()}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
