"""Build the original tender source bundle from explicit application bindings."""
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Callable

from integration.action_model_host import ActionModelHost
from integration.bindings.gba_v1 import GbaV1Assembly
from integration.contractor_tender_host import ContractorTenderHostCallbacks
from integration.contractor_tender_module_host import (
    ContractorTenderSources, ContractorTenderSourceValidators, _load_source_factory,
)
from integration.contractor_tender_snapshot_sources import ContractorTenderSnapshotSettings, build_snapshot_reader
from integration.contractor_tender_task_selection import ContractorTenderTaskSelector
from integration.contractor_tender_current_validation import ContractorTenderCurrentValidator
from integration.contractor_tender_native_publication import validate_native_publication
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import OrganizationRegistry


class ContractorTenderSelectorSettings(StrictRecord):
    selector_id: TextId
    version: TextId


class ContractorTenderCurrentValidationSettings(StrictRecord):
    validator_id: TextId
    version: TextId


class ContractorTenderNativePublicationSettings(StrictRecord):
    project_ids: dict[TextId, TextId]


class ContractorTenderSourceFactorySettings(StrictRecord):
    version: TextId
    application_factory: TextId
    application_version: TextId
    application_settings: dict
    snapshots: ContractorTenderSnapshotSettings
    quantity_snapshots: ContractorTenderSnapshotSettings
    task_selector: ContractorTenderSelectorSettings | None = None
    current_validation: ContractorTenderCurrentValidationSettings | None = None
    native_publication: ContractorTenderNativePublicationSettings | None = None


@dataclass(frozen=True)
class ContractorTenderApplicationBindings:
    """Actual application owns authority, shared writer guard and business checks.

    Its factory owns partial resources until returning this bundle. Validators
    must independently check professional facts and native receipt relationships;
    source-file hashes are not an alternative to those business checks.
    attach_host supplies exact task selection after original routes are installed.
    """
    version: str
    registry: ActionRegistry
    organizations: OrganizationRegistry
    read_guard: Callable
    validators: ContractorTenderSourceValidators
    tender_callbacks: ContractorTenderHostCallbacks
    attach_host: Callable
    evidence: Callable
    close: Callable
    model_host: ActionModelHost | None = None
    methods: object = None
    attach_task_selector: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.validators, ContractorTenderSourceValidators)
                or not isinstance(self.tender_callbacks, ContractorTenderHostCallbacks)
                or not all(callable(callback) for callback in
                    (self.read_guard, self.attach_host, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)
                or self.attach_task_selector is not None and not callable(self.attach_task_selector)):
            raise ValueError('Tender application requires original authority, shared guard and actual business callbacks')


def _binding_descriptors(application):
    callbacks = {item.name: getattr(application.validators, item.name) for item in fields(application.validators)}
    callbacks.update({item.name: getattr(application.tender_callbacks, item.name)
        for item in fields(application.tender_callbacks)})
    callbacks.update(read_guard=application.read_guard, attach_host=application.attach_host,
        evidence=application.evidence, close=application.close,
        attach_task_selector=application.attach_task_selector)
    return {name: module_factory_descriptor(callback, name) if callback is not None else None
        for name, callback in callbacks.items()}


def build_sources(*, assembly, request, output_directory, offline, settings, authority=None):
    """Actual source_factory entry point for ContractorTenderModuleSettings.

    Build both explicitly configured snapshot providers and return the original
    ContractorTenderSources. No native read, model client construction, action
    execution or submission is performed by this factory. Actual application
    bindings and independent source files must be supplied; none are invented.
    """
    if not isinstance(assembly, GbaV1Assembly) or type(offline) is not bool:
        raise ValueError('Tender source factory requires its actual GBA assembly and explicit model mode')
    assembly._validate_components()
    config = ContractorTenderSourceFactorySettings.model_validate(settings).model_copy(deep=True)
    if config.current_validation is not None and config.task_selector is None:
        raise ValueError('Concrete tender current validation requires the configured persistent task selector')
    factory = _load_source_factory(config.application_factory)
    if factory is build_sources:
        raise ValueError('Tender application factory cannot recursively select this source factory')
    descriptor = module_factory_descriptor(factory, config.application_factory)
    application = factory(assembly=assembly, request=request.model_copy(deep=True),
        output_directory=Path(output_directory), offline=offline, settings=deepcopy(config.application_settings),
        **({'authority':authority} if authority is not None else {}))
    if not isinstance(application, ContractorTenderApplicationBindings):
        raise ValueError('Tender application factory must return ContractorTenderApplicationBindings')
    closed = False

    def close():
        nonlocal closed
        if not closed:
            closed = True
            application.close()

    try:
        if authority is not None and (authority.assembly is not assembly
                or application.registry is not authority.registry or application.organizations is not authority.organizations
                or application.read_guard != authority.read_guard):
            raise TaskConflict('Tender source factory must borrow the original shared authority and writer guard')
        original = (assembly.engine, assembly.client, assembly.client.tasks,
            application.registry, application.organizations, application.model_host, application.methods)
        if (application.version != config.application_version
                or application.organizations.run_id != assembly.client.run_id
                or module_factory_descriptor(factory, config.application_factory) != descriptor):
            raise TaskConflict('Tender application changed its original version, run or factory')
        if (config.task_selector is None) != (application.attach_task_selector is None):
            raise ValueError('Configured tender task selector requires its explicit application attachment callback')
        registration = application.registry.get('CONTRACTOR-A02')
        if registration.role != 'Contractor' or not registration.implemented or registration.skill is None:
            raise ValueError('Tender source factory requires the original A02 processor and Skill')
        model = application.model_host
        model_version = assembly.client.versions['model']
        if offline:
            if model is not None:
                raise ValueError('Offline tender sources must not receive a model host')
        elif (model is None or model.store is not assembly.client.tasks or model.registry is not application.registry
                or model.model_version != model_version
                or not any('CONTRACTOR-A02' in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Tender model host must retain the original A02 strategy and same-journal budget')
        provider = build_snapshot_reader(assembly=assembly, organizations=application.organizations,
            read_guard=application.read_guard, settings=config.snapshots)
        quantities = build_snapshot_reader(assembly=assembly, organizations=application.organizations,
            read_guard=application.read_guard, settings=config.quantity_snapshots)
        selector = current_validator = None
        selector_attached = False
        tender_callbacks = application.tender_callbacks
        if tender_callbacks.prepare_request is not None and config.task_selector is None:
            raise ValueError('Request-driven tender preparation requires an explicit persistent task selector')
        if config.task_selector is not None:
            selector = ContractorTenderTaskSelector(store=assembly.client.tasks, registry=application.registry,
                selector_id=config.task_selector.selector_id, version=config.task_selector.version,
                read_guard=application.read_guard)
            tender_callbacks = ContractorTenderHostCallbacks(select_current=selector.select_current,
                revalidate=application.tender_callbacks.revalidate,
                validate_current=application.tender_callbacks.validate_current,
                prepare_request=application.tender_callbacks.prepare_request,
                recover_request=application.tender_callbacks.recover_request,
                validate_mapping=application.tender_callbacks.validate_mapping)
        if config.current_validation is not None:
            current_validator = ContractorTenderCurrentValidator(selector=selector,
                validator_id=config.current_validation.validator_id, version=config.current_validation.version)

            def revalidate(**kwargs):
                if application.tender_callbacks.revalidate(**kwargs) is not None:
                    raise TaskConflict('Application tender exposure validation must explicitly succeed')
                current_validator.revalidate(**kwargs)

            def validate_current(**kwargs):
                if application.tender_callbacks.validate_current(**kwargs) is not None:
                    raise TaskConflict('Application tender final validation must explicitly succeed')
                current_validator.validate_current(**kwargs)

            tender_callbacks = ContractorTenderHostCallbacks(select_current=selector.select_current,
                revalidate=revalidate, validate_current=validate_current,
                prepare_request=application.tender_callbacks.prepare_request,
                recover_request=application.tender_callbacks.recover_request,
                validate_mapping=application.tender_callbacks.validate_mapping)
        callbacks = _binding_descriptors(application)
        validators = application.validators
        if config.native_publication is not None:
            def publication(prepared, context):
                if application.validators.publication(deepcopy(prepared), context.model_copy(deep=True)) is not None:
                    raise TaskConflict('Application source publication validation must explicitly succeed')
                validate_native_publication(assembly=assembly, organizations=application.organizations,
                    prepared=prepared, context=context,
                    project_id=config.native_publication.project_ids.get(context.operation_id))

            validators = replace(application.validators, publication=publication)
        declared = {'schema_version': 'contractor-tender-source-factory.v1', 'run_id': assembly.client.run_id,
            'simulation_id': assembly.client.simulation_id, 'version': config.version,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'application_factory': descriptor, 'application_version': application.version,
            'source_factory': module_factory_descriptor(build_sources, 'build_sources'),
            'reader_factory': module_factory_descriptor(build_snapshot_reader, 'build_snapshot_reader'),
            'reader': module_factory_descriptor(provider.project, 'snapshot_reader.project'),
            'callbacks': callbacks, 'model_version': model_version,
            'model_configuration_sha256': model.configuration_sha256 if model is not None else None}
        if config.native_publication is not None:
            declared['native_publication_validator'] = module_factory_descriptor(
                validate_native_publication, 'validate_native_publication')
        if selector is not None:
            declared['task_selector_configuration_sha256'] = task_digest(selector._declared)
            declared['task_selector_attachment'] = module_factory_descriptor(selector.attach_host, 'selector.attach_host')
        if current_validator is not None:
            declared['current_validator_configuration_sha256'] = task_digest(current_validator._declared)
            declared['current_validator_callbacks'] = {
                name: module_factory_descriptor(callback, name) for name, callback in
                (('revalidate', current_validator.revalidate), ('validate_current', current_validator.validate_current))}
        config_sha256 = task_digest(config.model_dump(mode='json'))

        def attach_host(host):
            nonlocal selector_attached
            if closed:
                raise TaskConflict('Cannot attach a host to closed tender sources')
            if selector is not None:
                selector.attach_host(host)
                selector_attached = True
            if application.attach_host(host) is not None:
                raise TaskConflict('Tender application host attachment must not return a substitute component')
            if selector is not None:
                if application.attach_task_selector(selector) is not None:
                    raise TaskConflict('Tender application selector attachment must not return a substitute component')
                selector._check()

        def evidence():
            actual = (assembly.engine, assembly.client, assembly.client.tasks,
                application.registry, application.organizations, application.model_host, application.methods)
            if (closed or any(value is not expected for value, expected in zip(actual, original))
                    or application.version != config.application_version
                    or application.organizations.run_id != assembly.client.run_id
                    or task_digest(config.model_dump(mode='json')) != config_sha256
                    or module_factory_descriptor(_load_source_factory(config.application_factory),
                        config.application_factory) != descriptor
                    or module_factory_descriptor(build_sources, 'build_sources') != declared['source_factory']
                    or module_factory_descriptor(build_snapshot_reader, 'build_snapshot_reader') != declared['reader_factory']
                    or _binding_descriptors(application) != callbacks
                    or assembly.client.versions['model'] != model_version
                    or model is not None and (model.store is not assembly.client.tasks
                        or model.registry is not application.registry or model.model_version != model_version
                        or model.configuration_sha256 != declared['model_configuration_sha256'])):
                raise TaskConflict('Tender source factory changed its original application or execution configuration')
            provider._check()
            quantities._check()
            if (config.native_publication is not None
                    and module_factory_descriptor(validate_native_publication, 'validate_native_publication')
                        != declared['native_publication_validator']):
                raise TaskConflict('Tender native publication validator code changed')
            if selector is not None:
                selector._check(bound=selector_attached)
                if (task_digest(selector._declared) != declared['task_selector_configuration_sha256']
                        or module_factory_descriptor(selector.attach_host, 'selector.attach_host')
                            != declared['task_selector_attachment']):
                    raise TaskConflict('Tender source factory changed its configured task selector')
            if current_validator is not None:
                current_validator._check(bound=selector_attached)
                actual_callbacks = {name: module_factory_descriptor(callback, name) for name, callback in
                    (('revalidate', current_validator.revalidate), ('validate_current', current_validator.validate_current))}
                if (current_validator.selector is not selector
                        or task_digest(current_validator._declared) != declared['current_validator_configuration_sha256']
                        or actual_callbacks != declared['current_validator_callbacks']):
                    raise TaskConflict('Tender source factory changed its original concrete current validator')
            if (module_factory_descriptor(provider.project, 'snapshot_reader.project') != declared['reader']
                    or module_factory_descriptor(quantities.project, 'snapshot_reader.project') != declared['reader']):
                raise TaskConflict('Tender source snapshot reader code changed')
            actual_evidence = application.evidence()
            if not isinstance(actual_evidence, dict):
                raise ValueError('Tender application evidence must be an explicit object')
            return {'configuration': deepcopy(declared), 'status': 'configured_unverified',
                'application': deepcopy(actual_evidence),
                'task_selector_attached': selector_attached,
                'current_validation_configured': current_validator is not None,
                'native_publication_validation_configured': config.native_publication is not None,
                'limitations': ['Snapshot configuration is not native source health or professional validation.',
                    'Actual application callbacks, source files and endpoint behavior require independent verification.']}

        return ContractorTenderSources(version=config.version, registry=application.registry,
            organizations=application.organizations, provider=provider, quantity_provider=quantities,
            read_guard=application.read_guard, validators=validators,
            tender_callbacks=tender_callbacks, attach_host=attach_host if selector is not None else application.attach_host,
            evidence=evidence, close=close, model_host=model, methods=application.methods)
    except Exception:
        close()
        raise
