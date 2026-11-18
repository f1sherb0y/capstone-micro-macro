"""Explicit same-run host wiring for the existing A02 pipeline and native tender routes."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Callable

from integration.bindings.gba_v1_tender_binding import saved_tender_binding
from integration.bindings.gba_v1_tender_query import query_tender_submission, query_prior_tender_submissions, query_tender_source_history
from integration.contractor_bid_pipeline import GbaContractorBidPipeline
from integration.contractor_bid_results import ContractorTenderOutputReader
from integration.contractor_bid_source_history import read_bid_source_history
from integration.module_host import module_factory_descriptor
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class ContractorTenderHostCallbacks:
    """Host selects the exact saved task and independently checks current exposure/final facts."""
    select_current: Callable
    revalidate: Callable
    validate_current: Callable
    # Optional explicit request scheduler. It must persist and register the
    # original task before the read-only reader consumes it.
    prepare_request: Callable | None = None
    # Mapping publication precedes exact task selection. The later exposure
    # validator may require that selection, so it cannot serve both phases.
    validate_mapping: Callable | None = None
    recover_request: Callable | None = None

    def __post_init__(self):
        if not all(callable(callback) for callback in
                    (self.select_current, self.revalidate, self.validate_current)) or (
                self.prepare_request is not None and not callable(self.prepare_request)) or (
                self.validate_mapping is not None and not callable(self.validate_mapping)) or (
                self.recover_request is not None and not callable(self.recover_request)):
            raise ValueError('Exact original task selection and both fresh tender validators are required')


class GbaContractorTenderHost:
    """Wire existing business components; never create models, facts or native bids.

    Install routes before executing any A02 task. Restoring routes requires the
    actual original engine/client and unchanged host configuration. Preparation,
    execution and core observation remain separate explicit host operations.
    """
    VERSION = 'gba-contractor-tender-host.v4'

    def __init__(self, *, pipeline, callbacks, host_configuration_sha256,
            proposal_client_version, final_client_version):
        if (not isinstance(pipeline, GbaContractorBidPipeline)
                or not isinstance(callbacks, ContractorTenderHostCallbacks)
                or not isinstance(host_configuration_sha256, str)
                or re.fullmatch(r'[0-9a-f]{64}', host_configuration_sha256) is None
                or any(not isinstance(value, str) or not value.strip()
                    for value in (proposal_client_version, final_client_version))
                or proposal_client_version == final_client_version
                or pipeline.worker.client_version != final_client_version
                or pipeline.worker.model_version != pipeline.assembly.client.versions['model']):
            raise ValueError('Tender host requires an original pipeline, declared configuration and matching final worker versions')
        self.pipeline, self.callbacks = pipeline, callbacks
        self.recovery_guard = pipeline.read_guard
        self.proposal_client_version, self.final_client_version = proposal_client_version, final_client_version
        self._versions = {**pipeline.assembly.client.versions, 'client': final_client_version}
        self.declared_configuration_sha256 = host_configuration_sha256
        self.reader = ContractorTenderOutputReader(worker=pipeline.worker,
            assembler=pipeline.assembler, select_current=callbacks.select_current)
        self._components = (pipeline.assembly, pipeline.assembler, pipeline.worker, pipeline.publications,
            pipeline.source_provider, pipeline.read_guard, callbacks, self.reader)
        self._configuration = self._describe_configuration()
        self.configuration_sha256 = task_digest(self._configuration)
        self._state = 'unbound'
        self._routes = None

    def _describe_configuration(self):
        pipeline = self.pipeline
        callbacks = {'select_current': self.callbacks.select_current,
            'prepare_request': self.callbacks.prepare_request,
            'recover_request': self.callbacks.recover_request,
            'validate_mapping': self.callbacks.validate_mapping,
            'revalidate': self.callbacks.revalidate, 'validate_current': self.callbacks.validate_current,
            'read_guard': pipeline.read_guard, 'validate_quantity': pipeline.validate_quantity,
            'validate_cost': pipeline.validate_cost, 'validate_handoff': pipeline.validate_handoff,
            'validate_programme': pipeline.validate_programme,
            'source_project': pipeline.source_provider.project}
        return {'schema_version': self.VERSION, 'run_id': pipeline.worker.store.run_id,
            'simulation_id': pipeline.assembly.client.simulation_id,
            'declared_configuration_sha256': self.declared_configuration_sha256,
            'pipeline_version': pipeline.VERSION, 'proposal_client_version': self.proposal_client_version,
            'final_client_version': self.final_client_version, 'model_version': pipeline.worker.model_version,
            'execution_versions': deepcopy(self._versions),
            'submission_query': module_factory_descriptor(query_tender_submission, 'query_tender_submission'),
            'source_history_query': module_factory_descriptor(query_tender_source_history, 'query_tender_source_history'),
            'source_history_reader': module_factory_descriptor(read_bid_source_history, 'read_bid_source_history'),
            'prior_submission_query': module_factory_descriptor(query_prior_tender_submissions, 'query_prior_tender_submissions'),
            'callbacks': {key: module_factory_descriptor(value, key) if value is not None else None
                for key, value in callbacks.items()},
            'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def _check(self, *, bound=False):
        pipeline = self.pipeline
        current = (pipeline.assembly, pipeline.assembler, pipeline.worker, pipeline.publications,
            pipeline.source_provider, pipeline.read_guard, self.callbacks, self.reader)
        if (any(actual is not expected for actual, expected in zip(current, self._components))
                or self.recovery_guard is not pipeline.read_guard
                or pipeline.worker.store is not pipeline.assembly.client.tasks
                or pipeline.worker.snapshots.store is not pipeline.worker.store
                or pipeline.worker.registry is not pipeline.assembler.registry
                or self.reader.worker is not pipeline.worker or self.reader.assembler is not pipeline.assembler
                or self.reader.select_current is not self.callbacks.select_current
                or pipeline.assembler.organizations.run_id != pipeline.worker.store.run_id
                or pipeline.worker.client_version != self.final_client_version
                or pipeline.worker.model_version != self._versions['model']
                or self._describe_configuration() != self._configuration):
            raise TaskConflict('Tender host components, original journal, execution versions or declared configuration changed')
        pipeline.assembly._validate_components()
        if bound and (self._state not in {'installed', 'restored'} or self._routes is None
                or pipeline.assembly.client.proposal_handlers.get(('Contractor', 'consider_tender')) is not self._routes['proposal']
                or pipeline.assembly.client.decision_handler is not self._routes['decision']
                or pipeline.assembly.client.versions != self._versions):
            raise TaskConflict('Tender host requires its actual installed original proposal/final routes')

    def _read_output(self, request):
        self._check(bound=True)
        with self.pipeline.read_guard():
            if self.callbacks.prepare_request is not None:
                if self.callbacks.prepare_request(request.model_copy(deep=True)) is not None:
                    raise TaskConflict('Tender request preparation must persist its result without substituting the reader')
                self._check(bound=True)
            return self.reader(request)

    def _revalidate(self, *args, **kwargs):
        self._check(bound=True)
        with self.pipeline.read_guard():
            return self.callbacks.revalidate(*args, **kwargs)

    def _read_saved_output(self, request):
        """Query original work only; never enter normal request preparation."""
        self._check(bound=True)
        with self.pipeline.read_guard():
            if self.callbacks.recover_request is None:
                raise TaskConflict('Tender saved-result recovery was not explicitly configured')
            if self.callbacks.recover_request(request.model_copy(deep=True)) is not None:
                raise TaskConflict('Tender recovery must restore its original selection without substituting the reader')
            self._check(bound=True)
            return self.reader(request)

    def _validate_current(self, *args, **kwargs):
        self._check(bound=True)
        with self.pipeline.read_guard():
            return self.callbacks.validate_current(*args, **kwargs)

    def install(self):
        self._check()
        if self._state != 'unbound' or self.final_client_version == self.pipeline.assembly.client.versions['client']:
            raise TaskConflict('Fresh tender installation requires an unused host and new final client version')
        self._state = 'installation_started'
        assembly = self.pipeline.assembly
        try:
            with assembly.client._lock:
                proposal = assembly.bind_contractor_tender_proposal(registry=self.pipeline.worker.registry,
                    read_output=self._read_output, revalidate=self._revalidate,
                    client_version=self.proposal_client_version)
                decision = assembly.bind_contractor_tender_decision(validate_current=self._validate_current,
                    client_version=self.final_client_version, host_configuration_sha256=self.configuration_sha256)
                self._routes = {'proposal': proposal, 'decision': decision}
                self._state = 'installed'
        except Exception:
            self._state = 'installation_failed'
            raise
        return self.evidence()

    def restore(self):
        self._check()
        if self._state != 'unbound' or self.pipeline.assembly.client.versions['client'] != self.final_client_version:
            raise TaskConflict('Tender restoration requires a fresh host with the original final versions')
        self._state = 'restoration_started'
        try:
            self._routes = self.pipeline.assembly.restore_contractor_tender_bindings(
                registry=self.pipeline.worker.registry, read_output=self._read_output,
                revalidate=self._revalidate, validate_current=self._validate_current,
                host_configuration_sha256=self.configuration_sha256)
            self._state = 'restored'
        except Exception:
            self._state = 'restoration_failed'
            raise
        return self.evidence()

    def restore_from_checkpoint(self):
        """Reuse original tender restoration inside the verified host window.

        The fresh process has reconstructed other role routes in their original
        order. Restore the saved final transport versions before the existing
        tender binding verifier checks every original tender task and adapter.
        Failure is never followed by fresh installation or business replay.
        """
        from integration.native_checkpoint import checkpoint_binding_installation_allowed

        client = self.pipeline.assembly.client
        with client._lock:
            if not checkpoint_binding_installation_allowed(client):
                raise TaskConflict('Tender checkpoint restoration requires the verified application reinstallation window')
            self._check()
            saved = saved_tender_binding(client.tasks)
            if (self._state != 'unbound' or saved is None
                    or saved['versions'] != self._versions
                    or saved['host_configuration_sha256'] != self.configuration_sha256
                    or any(client.versions[k] != v for k, v in self._versions.items() if k != 'client')):
                raise TaskConflict('Tender checkpoint restoration changes original final versions or host configuration')
            client.versions = deepcopy(self._versions)
            return self.restore()

    def prepare(self, plan, *, screening, screening_result, screening_audit):
        self._check(bound=True)
        return self.pipeline.prepare(plan, screening=screening,
            screening_result=screening_result, screening_audit=screening_audit)

    def prepare_from_saved_screening(self, plan, *, identity, record_sha256):
        """Use one explicit original A01 record; retain the independent handoff gate."""
        from integration.contractor_bid_pipeline import ContractorBidPipelinePlan
        from integration.contractor_screening_results import read_screening_history

        self._check(bound=True)
        plan = ContractorBidPipelinePlan.model_validate(plan).model_copy(deep=True)
        with self.pipeline.read_guard():
            reading = self.pipeline.assembler.build_capacity_reading(plan.capacity_context)
            screening = read_screening_history(store=self.pipeline.worker.store,
                registry=self.pipeline.worker.registry, snapshots=self.pipeline.worker.snapshots,
                identity=identity, record_sha256=record_sha256,
                current_context=plan.capacity_context, reading=reading)
            result = self.pipeline.prepare(plan, screening=screening,
                screening_result=screening.result, screening_audit=screening.audit)
            self._check(bound=True)
            return result

    def execute(self, prepared, *, request_id, purpose='action'):
        self._check(bound=True)
        return self.pipeline.execute(prepared, request_id=request_id, purpose=purpose)

    def feedback(self, *, organization_id):
        self._check(bound=True)
        return self.pipeline.assembly.client.tender_feedback(organization_id=organization_id)

    def query_submission(self, original_request):
        return query_tender_submission(self, original_request)

    def query_source_history(self, original_request, identity, *, current_context):
        return query_tender_source_history(self, original_request, identity, current_context=current_context)

    def publish_tender_mapping(self, *, request, identity, source_context, next_context, mapping_ref):
        """Expose only the original separately sourced indicators at a fresh token."""
        self._check(bound=True)
        with self.pipeline.read_guard():
            reading = self.pipeline.assembler.build_result_reading(source_context)
            revalidate = self.callbacks.revalidate
            if self.callbacks.validate_mapping is not None:
                def revalidate(**kwargs):
                    # Publication precedes selector registration. Pass the exact
                    # saved task explicitly instead of looking up a selection
                    # whose mapping has not yet been published.
                    return self.callbacks.validate_mapping(identity=deepcopy(identity),
                        mapping_ref=deepcopy(mapping_ref), **kwargs)
            return self.pipeline.publications.publish_bid_tender_mapping(request=request,
                assembly=self.pipeline.assembly, worker=self.pipeline.worker, identity=identity,
                source_context=source_context, reading=reading, next_context=next_context,
                mapping_ref=mapping_ref,
                revalidate=revalidate)

    def evidence(self):
        self._check(bound=True)
        binding = saved_tender_binding(self.pipeline.worker.store)
        if binding is None or binding['host_configuration_sha256'] != self.configuration_sha256:
            raise TaskConflict('Tender host lacks its original matching persisted route binding')
        return {'component': type(self).__module__ + '.' + type(self).__qualname__,
            'version': self.VERSION, 'state': self._state, 'configuration': deepcopy(self._configuration),
            'configuration_sha256': self.configuration_sha256, 'binding_sha256': binding['record_sha256'],
            'limitations': ['Host must supply original independent professional sources and exact task selection.',
                'Callbacks hold the host read guard separately; the host owns core writer serialization.',
                'Failed installation/restoration requires inspection, never automatic retry or version migration.',
                'Native bid effects are owned by the original core; route installation is not runtime verification.']}
