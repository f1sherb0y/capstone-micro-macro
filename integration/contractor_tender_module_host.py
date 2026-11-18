"""Concrete post-engine construction of the supported Contractor tender host."""
from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
from pathlib import Path
from typing import Callable

from integration.action_model_host import ActionModelHost
from integration.bindings.gba_v1 import GbaV1Assembly
from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore, GbaTenderPublishedViewProvider
from integration.contractor_bid_actions import ContractorBidActionAssembler
from integration.contractor_bid_pipeline import GbaContractorBidPipeline
from integration.contractor_bid_results import ContractorBidResultWorker
from integration.contractor_tender_host import ContractorTenderHostCallbacks, GbaContractorTenderHost
from integration.contractor_tender_snapshot_sources import ContractorTenderSnapshotSettings, build_snapshot_reader
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, module_factory_descriptor
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.registry import ActionRegistry
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import OrganizationRegistry


class ContractorTenderModuleSettings(StrictRecord):
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    proposal_client_version: TextId
    final_client_version: TextId
    policy_version: TextId
    snapshot_sources: ContractorTenderSnapshotSettings | None = None


@dataclass(frozen=True)
class ContractorTenderSourceValidators:
    publication: Callable
    invocation: Callable
    wait: Callable
    recovery: Callable
    quantity: Callable
    cost: Callable
    handoff: Callable
    programme: Callable | None = None

    def __post_init__(self):
        if any(not callable(getattr(self, item.name)) for item in fields(self)
                if item.name != 'programme') or self.programme is not None and not callable(self.programme):
            raise ValueError('Tender source, execution, wait and recovery validators must be explicit')


@dataclass(frozen=True)
class ContractorTenderSources:
    """Application supplies actual authorized readers and callbacks, not fabricated facts.

    attach_host receives the fully installed host so the application's selector
    can explicitly use its pipeline/worker. Construction does not run an action.
    The application owns cleanup until this typed object is returned.
    """
    version: str
    registry: ActionRegistry
    organizations: OrganizationRegistry
    provider: object
    quantity_provider: object
    read_guard: Callable
    validators: ContractorTenderSourceValidators
    tender_callbacks: ContractorTenderHostCallbacks
    attach_host: Callable
    evidence: Callable
    close: Callable
    model_host: ActionModelHost | None = None
    methods: object = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.validators, ContractorTenderSourceValidators)
                or not isinstance(self.tender_callbacks, ContractorTenderHostCallbacks)
                or not callable(getattr(self.provider, 'project', None))
                or not callable(getattr(self.quantity_provider, 'project', None))
                or not all(callable(callback) for callback in
                    (self.read_guard, self.attach_host, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)):
            raise ValueError('Tender sources require actual registries/readers, explicit callbacks and resource ownership')


def _load_source_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Tender source factory requires module:callable syntax')
    module_name, name = specification.split(':')
    if not module_name or not name.isidentifier():
        raise ValueError('Tender source factory requires an explicit module and callable name')
    factory = getattr(importlib.import_module(module_name), name, None)
    if not callable(factory):
        raise ValueError('Configured tender source factory is not callable')
    return factory


def _source_descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update({item.name: getattr(sources.tender_callbacks, item.name) for item in fields(sources.tender_callbacks)})
    callbacks.update({'provider': sources.provider.project, 'quantity_provider': sources.quantity_provider.project,
        'read_guard': sources.read_guard, 'attach_host': sources.attach_host,
        'evidence': sources.evidence, 'close': sources.close})
    return {name: module_factory_descriptor(callback, name) if callback is not None else None
        for name, callback in callbacks.items()}


def configure_assembly(*, assembly, request, output_directory, offline, configuration, authority=None):
    """Build the existing publications/assembler/worker/pipeline and install original routes once."""
    if not isinstance(assembly, GbaV1Assembly) or type(offline) is not bool:
        raise ValueError('Tender assembly hook requires the actual GBA assembly and explicit model mode')
    assembly._validate_components()
    config = GbaModuleHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = ContractorTenderModuleSettings.model_validate(config.settings)
    factory = _load_source_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(assembly=assembly, request=request.model_copy(deep=True),
        output_directory=Path(output_directory), offline=offline,
        settings=deepcopy(settings.source_settings), **({'authority':authority} if authority is not None else {}))
    if not isinstance(sources, ContractorTenderSources):
        raise ValueError('Tender source factory must return ContractorTenderSources')
    try:
        if authority is not None and (authority.assembly is not assembly or sources.registry is not authority.registry
                or sources.organizations is not authority.organizations or sources.read_guard != authority.read_guard):
            raise TaskConflict('Tender host requires its exact original borrowed shared authority and writer guard')
        client = assembly.client
        if (sources.version != settings.source_version or sources.organizations.run_id != client.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Tender source factory changes its declared version, original run or actual code')
        registration = sources.registry.get('CONTRACTOR-A02')
        if not registration.implemented or registration.skill is None:
            raise ValueError('Configured tender host requires the original A02 processor and Skill')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline tender hook must not receive a model host or bound model strategies')
        elif (model_host is None or model_host.store is not client.tasks or model_host.registry is not sources.registry
                or model_host.model_version != client.versions['model']
                or not any('CONTRACTOR-A02' in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM tender hook requires an actual same-journal model host with original A02 strategy and budget')
        descriptors = _source_descriptors(sources)
        snapshot_reader = None
        source_provider = sources.provider
        if settings.snapshot_sources is not None:
            snapshot_reader = build_snapshot_reader(assembly=assembly, organizations=sources.organizations,
                read_guard=sources.read_guard, settings=settings.snapshot_sources)
            source_provider = snapshot_reader
        original_provider = sources.provider
        declared = {'schema_version': 'contractor-tender-module-host.v1', 'run_id': client.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': descriptors,
            'macro_version': settings.macro_version, 'requested_model_mode': 'offline' if offline else 'llm',
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if snapshot_reader is not None:
            declared['snapshot_source'] = {
                'configuration_sha256': task_digest(settings.snapshot_sources.model_dump(mode='json')),
                'factory': module_factory_descriptor(build_snapshot_reader, 'build_snapshot_reader'),
                'reader': module_factory_descriptor(snapshot_reader.project, 'snapshot_reader.project')}
        publications = GbaTenderPublicationStore(store=client.tasks, organizations=sources.organizations,
            validate_source=sources.validators.publication)
        provider = GbaTenderPublishedViewProvider(provider=source_provider, publications=publications)
        assembler = ContractorBidActionAssembler(registry=sources.registry, organizations=sources.organizations,
            provider=provider, macro_version=settings.macro_version, source_mode='formal', methods=sources.methods,
            policy_version=settings.policy_version, model_version=client.versions['model'], model_host=model_host)
        snapshots = InvocationSnapshotStore(client.tasks)
        worker = ContractorBidResultWorker(store=client.tasks, snapshots=snapshots, registry=sources.registry,
            client_version=settings.final_client_version, model_version=client.versions['model'],
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)
        pipeline = GbaContractorBidPipeline(assembly=assembly, assembler=assembler, worker=worker,
            publications=publications, source_provider=sources.quantity_provider, read_guard=sources.read_guard,
            validate_quantity=sources.validators.quantity, validate_cost=sources.validators.cost,
            validate_handoff=sources.validators.handoff, validate_programme=sources.validators.programme)
        host = GbaContractorTenderHost(pipeline=pipeline, callbacks=sources.tender_callbacks,
            host_configuration_sha256=task_digest(declared), proposal_client_version=settings.proposal_client_version,
            final_client_version=settings.final_client_version)
        if getattr(client, '_native_checkpoint_pending', None) is not None:
            host.restore_from_checkpoint()
        else:
            host.install()
        if sources.attach_host(host) is not None:
            raise TaskConflict('Actual tender source host attachment must explicitly finish without substituting a component')

        def evidence():
            if (_source_descriptors(sources) != descriptors
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or sources.registry is not worker.registry or sources.organizations is not assembler.organizations
                    or sources.provider is not original_provider or provider.provider is not source_provider
                    or sources.quantity_provider is not pipeline.source_provider
                    or sources.read_guard is not pipeline.read_guard or sources.methods is not assembler.methods
                    or sources.model_host is not model_host
                    or model_host is not None and (model_host.registry is not worker.registry
                        or model_host.store is not client.tasks or model_host.model_version != worker.model_version
                        or assembler.decision_strategies != model_host.bindings)):
                raise TaskConflict('Configured tender sources or callbacks changed after original route installation')
            if snapshot_reader is not None:
                snapshot_reader._check()
                if (module_factory_descriptor(build_snapshot_reader, 'build_snapshot_reader')
                        != declared['snapshot_source']['factory']
                        or module_factory_descriptor(snapshot_reader.project, 'snapshot_reader.project')
                            != declared['snapshot_source']['reader']):
                    raise TaskConflict('Configured tender snapshot factory or reader source changed')
            source_evidence = sources.evidence()
            if not isinstance(source_evidence, dict):
                raise ValueError('Actual tender source evidence must be an explicit JSON object')
            return {'configuration': deepcopy(declared), 'tender_host': host.evidence(),
                'sources': deepcopy(source_evidence),
                'model_host': model_host.evidence() if model_host is not None else None,
                'limitations': ['Application provides actual professional records, current authorization and task selection.',
                    'This fresh-engine hook does not restore a whole macro engine or automatically execute actions.']}

        evidence()
        return GbaModuleHostExtension(version='contractor-tender-module-host.v1', evidence=evidence,
            close=sources.close, writer_guard=sources.read_guard)
    except Exception:
        sources.close()
        raise
