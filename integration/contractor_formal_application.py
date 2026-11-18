"""Configured formal Contractor application assembly over original actual dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field, replace
import importlib
import json
from pathlib import Path
from typing import Callable

from pydantic import model_validator

from integration.commercial_worker import CommercialTaskWorker
from integration.commercial_formal_recovery import (
    CommercialFormalRecoverySettings, CommercialFormalRecoveryBindings, CommercialFormalRecoveryReader,
    build_formal_commercial_recovery,
)
from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from integration.owner_contractor_payment_handoff import CONTRACTOR_RECEIVED_PAYMENT_SOURCE_VERSION
from integration.owner_payment_execution_reader import (
    OwnerPaymentExecutionReader, OwnerPaymentExecutionReaderSettings, bind_contractor_payment_reader,
)
from integration.contractor_role_contract_host import ContractorRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.contractor_submission import ContractorSubmissionCallbacks
from integration.contractor_submission_feedback import ContractorSubmissionFeedback
from integration.contractor_formation_actions import ContractorFormationActionAssembler
from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler
from integration.contractor_execution_actions import ContractorExecutionActionAssembler
from integration.contractor_closeout_actions import ContractorCloseoutActionAssembler
from integration.contractor_payment_actions import ContractorPaymentActionAssembler
from integration.contractor_claim_actions import ContractorClaimActionAssembler
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from integration.contractor_readiness_actions import ContractorReadinessActionAssembler
from integration.contractor_readiness_recovery_reader import (
    ContractorReadinessRecoveryReader, ContractorReadinessRecoverySettings, ContractorReadinessRecoveryBindings,
    build_assembled_contractor_readiness_dispatcher,
)
from integration.contractor_supply_recovery_reader import (
    ContractorSupplyRecoveryReader, ContractorSupplyRecoverySettings, ContractorSupplyRecoveryBindings,
    build_assembled_contractor_supply_dispatcher,
)
from integration.contractor_claim_recovery_reader import (
    ContractorClaimRecoveryReader, ContractorClaimRecoverySettings, ContractorClaimRecoveryBindings,
    build_assembled_contractor_claim_dispatcher,
)
from integration.contractor_measurement_recovery_reader import (
    ContractorMeasurementRecoveryReader, ContractorMeasurementRecoverySettings, ContractorMeasurementRecoveryBindings,
    build_assembled_contractor_measurement_dispatcher,
)
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutRecoverySettings, ContractorCloseoutRecoveryBindings,
    build_assembled_contractor_closeout_dispatcher,
)
from integration.contractor_execution_reader import (
    ContractorExecutionReader, ContractorExecutionRecoveryBindings, ContractorExecutionRecoverySettings,
    build_assembled_contractor_execution_dispatcher,
)
from integration.contractor_amendment_command_reader import (
    ContractorAmendmentCommandReader, ContractorAmendmentRecoveryBindings,
    build_assembled_contractor_amendment_command_dispatcher,
)
from integration.contractor_formation_command_reader import (
    ContractorFormationCommandReader, ContractorFormationRecoveryBindings, ContractorFormationRecoverySettings,
    build_assembled_contractor_formation_command_dispatcher,
)
from integration.contractor_submission_host import ContractorSubmissionHost, ContractorSubmissionHostConfiguration
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, canonical, task_digest


class ContractorFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False


class ContractorFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: ContractorSubmissionHostConfiguration | None = None
    feedback: ContractorFormalFeedbackSettings | None = None
    execution_recovery: CommercialFormalRecoverySettings | ContractorFormationRecoverySettings | ContractorExecutionRecoverySettings | ContractorCloseoutRecoverySettings | ContractorMeasurementRecoverySettings | ContractorClaimRecoverySettings | ContractorSupplyRecoverySettings | ContractorReadinessRecoverySettings | None = None
    payment_reception: OwnerPaymentExecutionReaderSettings | None = None

    @model_validator(mode='before')
    @classmethod
    def commercial_recovery_type(cls, value):
        if isinstance(value, dict) and value.get('execution_recovery') is not None:
            types = {'CONTRACTOR-A12': CommercialFormalRecoverySettings, 'CONTRACTOR-A07': ContractorExecutionRecoverySettings,
                'CONTRACTOR-A03': ContractorFormationRecoverySettings, 'CONTRACTOR-A04': ContractorFormationRecoverySettings,
                'CONTRACTOR-A11': ContractorCloseoutRecoverySettings, 'CONTRACTOR-A10': ContractorMeasurementRecoverySettings,
                'CONTRACTOR-A09': ContractorClaimRecoverySettings, 'CONTRACTOR-A05': ContractorSupplyRecoverySettings,
                'CONTRACTOR-A06': ContractorReadinessRecoverySettings}
            selected_type = types.get(value.get('action_id'))
            if selected_type is not None:
                return {**value, 'execution_recovery': selected_type.model_validate(value['execution_recovery'])}
        return value

    @model_validator(mode='after')
    def recovery_matches_original_action(self):
        if self.execution_recovery is not None:
            if (self.action_id not in {'CONTRACTOR-A03', 'CONTRACTOR-A04', 'CONTRACTOR-A05', 'CONTRACTOR-A06', 'CONTRACTOR-A07', 'CONTRACTOR-A09', 'CONTRACTOR-A10', 'CONTRACTOR-A11', 'CONTRACTOR-A12'}
                    or (self.action_id == 'CONTRACTOR-A12') != isinstance(self.execution_recovery, CommercialFormalRecoverySettings)
                    or (self.action_id == 'CONTRACTOR-A07') != isinstance(
                        self.execution_recovery, ContractorExecutionRecoverySettings)
                    or (self.action_id == 'CONTRACTOR-A11') != isinstance(self.execution_recovery, ContractorCloseoutRecoverySettings)
                    or (self.action_id == 'CONTRACTOR-A10') != isinstance(self.execution_recovery, ContractorMeasurementRecoverySettings)
                    or (self.action_id == 'CONTRACTOR-A09') != isinstance(self.execution_recovery, ContractorClaimRecoverySettings)
                    or (self.action_id == 'CONTRACTOR-A05') != isinstance(self.execution_recovery, ContractorSupplyRecoverySettings)
                    or (self.action_id == 'CONTRACTOR-A06') != isinstance(self.execution_recovery, ContractorReadinessRecoverySettings)):
                raise ValueError('Contractor execution recovery settings must match the original action')
        return self

    @property
    def declared_source_version(self):
        version = ContractorFormalApplication.VERSION
        if self.payment_reception is not None:
            version += '+' + CONTRACTOR_RECEIVED_PAYMENT_SOURCE_VERSION
        return version


@dataclass(frozen=True)
class ContractorFormalApplicationDependencies:
    """Actual application supplies original sources and an existing model host.

    The factory owns partial resources until returning this bundle. Original
    invocation/wait/recovery validators apply to all submission workers; actual
    action-specific transport and business validation are explicitly supplied.
    """
    version: str
    sources: ContractorRoleContractSources
    submission_callbacks: dict[str, ContractorSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    owner_payment_reader: OwnerPaymentExecutionReader | None = None
    validate_payment_reception: Callable | None = None
    execution_recovery: CommercialFormalRecoveryBindings | ContractorFormationRecoveryBindings | ContractorExecutionRecoveryBindings | ContractorCloseoutRecoveryBindings | ContractorMeasurementRecoveryBindings | ContractorClaimRecoveryBindings | ContractorSupplyRecoveryBindings | ContractorReadinessRecoveryBindings | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, ContractorRoleContractSources)
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or not isinstance(self.submission_callbacks, dict)
                or self.execution_recovery is not None and not isinstance(
                    self.execution_recovery, (CommercialFormalRecoveryBindings, ContractorFormationRecoveryBindings,
                        ContractorExecutionRecoveryBindings, ContractorCloseoutRecoveryBindings))
                or any(not isinstance(value, ContractorSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(callback is not None and not callable(callback) for callback in
                    (self.submission_read_guard, self.validate_feedback_relation,
                        self.validate_feedback_read, self.validate_feedback_input,
                        self.validate_payment_reception))
                or self.owner_payment_reader is not None and not isinstance(self.owner_payment_reader, OwnerPaymentExecutionReader)):
            raise ValueError('Formal Contractor dependencies require original sources and actual callback bindings')


def _check_commercial_worker(base, config):
    """Retain the application's existing A12 assembler, journal and model binding."""
    worker = base.commercial_worker
    if not isinstance(worker, CommercialTaskWorker):
        raise ValueError('Formal Contractor A12 requires the original commercial worker and wait journal')
    assembler = worker.assembler
    view = assembler._views['CONTRACTOR-A12']
    if (worker.store is not base.store or worker.snapshots.store is not base.store
            or worker.journal.store is not base.store or assembler.registry is not base.registry
            or assembler.organizations is not base.organizations or assembler.methods is not base.methods
            or assembler.source_mode != 'formal' or view.source_mode != 'formal'
            or view.provider is not base.provider or view.organizations is not base.organizations
            or worker.client_version != config.client_version or worker.model_version != config.model_version
            or assembler.model_version != config.model_version
            or assembler.decision_strategies != tuple(base.model_host.bindings)
            or any(getattr(worker, 'validate_' + name) is not getattr(base.validators, name)
                for name in ('invocation', 'wait', 'recovery'))):
        raise TaskConflict('Formal Contractor A12 changes its original commercial sources, versions or callbacks')


class ContractorFormalApplication:
    """Assemble original workers and configured routes; business calls stay explicit.

    Source health and native endpoint effects require observed application
    evidence. Construction is configured_unverified and never runs an action,
    sends a submission, constructs a model client or invents a native source.
    A12 keeps the supplied commercial worker and wait journal; tender routes
    require the actual application transport and are never installed implicitly.
    """
    VERSION = 'contractor-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = ContractorFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, ContractorFormalApplicationDependencies):
            raise ValueError('Formal Contractor factory must return ContractorFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version):
            raise ValueError('Formal Contractor assembly requires original same-run sources and configured model host')
        registration = base.registry.get(config.action_id)
        if (registration.role != 'Contractor' or not registration.implemented or registration.skill is None
                or request.execution_path not in {None, registration.strategy}
                or not any(config.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Formal Contractor application requires its original implemented action and bound strategy')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if (not actions <= set(_ACTIONS) or set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.submission is None and dependencies.submission_read_guard is not None):
            raise ValueError('Configured Contractor submission must match its explicit callbacks and current read guard')
        if config.payment_reception is not None:
            if (config.action_id != 'CONTRACTOR-A10'
                    or not isinstance(dependencies.owner_payment_reader, OwnerPaymentExecutionReader)
                    or not callable(dependencies.validate_payment_reception)
                    or base.read_owner_payment is not None or base.validate_received_payments is not None
                    or dependencies.owner_payment_reader.settings != config.payment_reception
                    or config.payment_reception.recipient_context != request.context):
                raise ValueError('Formal Contractor payment reception requires its exact original reader, recipient and actual validator')
            dependencies.owner_payment_reader._check()
        elif dependencies.owner_payment_reader is not None or dependencies.validate_payment_reception is not None:
            raise ValueError('Contractor payment reader/validator require an explicit reception declaration')
        if config.feedback is not None:
            if (config.submission is None or not actions
                    or not callable(dependencies.validate_feedback_relation)
                    or not callable(dependencies.validate_feedback_read)):
                raise ValueError('Contractor feedback requires configured submission routes and actual relation/read validators')
        elif dependencies.validate_feedback_relation is not None or dependencies.validate_feedback_read is not None:
            raise ValueError('Contractor feedback validators require an explicit feedback configuration')
        input_enabled = config.feedback is not None and config.feedback.input_enabled
        if (input_enabled and not callable(dependencies.validate_feedback_input)
                or not input_enabled and dependencies.validate_feedback_input is not None):
            raise ValueError('Contractor feedback input validation must match the explicit input-enabled configuration')
        self._require_commercial = config.action_id == 'CONTRACTOR-A12' or 'CONTRACTOR-A12' in actions
        if self._require_commercial:
            _check_commercial_worker(base, config)
        self.dependencies, self.base = dependencies, base
        self._original_payment_reception_components = (dependencies.owner_payment_reader, dependencies.validate_payment_reception)
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model, base.commercial_worker)
        self._closed = False
        self.submissions = self.feedback = self.execution_dispatcher = None
        self.formation_assembler = self.command_reader = None
        self._formation_recovery_components = None
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                if action_id == 'CONTRACTOR-A12':
                    workers[action_id] = base.commercial_worker
                    continue
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.contractor_' + module + '_results'),
                    'Contractor' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = ContractorSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            self.feedback = ContractorSubmissionFeedback(host=self.submissions, inbox=inbox,
                version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                validate_read=dependencies.validate_feedback_read)
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('Contractor original execution recovery must match its explicit configuration')
        if recovery is not None and config.action_id == 'CONTRACTOR-A12':
            if (type(recovery) is not CommercialFormalRecoveryBindings
                    or type(config.execution_recovery) is not CommercialFormalRecoverySettings
                    or config.action_id not in actions or self.feedback is None):
                raise ValueError('Contractor A12 recovery requires original commercial callbacks, submission and feedback routes')
            _check_commercial_worker(base, config)
            self.formation_assembler = base.commercial_worker.assembler
            view = self.formation_assembler._views[config.action_id]
            if (view.macro_version != config.execution_recovery.macro_version
                    or self.formation_assembler.policy_version != config.execution_recovery.policy_version):
                raise ValueError('Contractor A12 recovery must retain original commercial source/policy versions')
            self.command_reader = CommercialFormalRecoveryReader(worker=base.commercial_worker,
                bindings=recovery, action_id=config.action_id)
            self.execution_dispatcher = build_formal_commercial_recovery(inbox=self.feedback.inbox,
                worker=base.commercial_worker, bindings=recovery, action_id=config.action_id, reader=self.command_reader)
            self._formation_recovery_components = (recovery, *recovery.components(), self.formation_assembler,
                self.command_reader, self.execution_dispatcher, self.feedback.inbox, base.provider)
        elif recovery is not None:
            if isinstance(recovery, CommercialFormalRecoveryBindings):
                raise ValueError('Commercial recovery callbacks belong only to Contractor A12')
            if config.action_id not in {'CONTRACTOR-A03', 'CONTRACTOR-A04', 'CONTRACTOR-A05', 'CONTRACTOR-A06', 'CONTRACTOR-A07', 'CONTRACTOR-A09', 'CONTRACTOR-A10', 'CONTRACTOR-A11'} or config.action_id not in actions or self.feedback is None:
                raise ValueError('Contractor recovery requires original A03/A04/A05/A06/A07/A09/A10/A11 submission and feedback routes')
            amendment = config.action_id == 'CONTRACTOR-A03'
            execution = config.action_id == 'CONTRACTOR-A07'
            closeout = config.action_id == 'CONTRACTOR-A11'
            measurement = config.action_id == 'CONTRACTOR-A10'
            claim = config.action_id == 'CONTRACTOR-A09'
            supply = config.action_id == 'CONTRACTOR-A05'
            readiness = config.action_id == 'CONTRACTOR-A06'
            if (amendment != isinstance(recovery, ContractorAmendmentRecoveryBindings)
                    or execution != isinstance(recovery, ContractorExecutionRecoveryBindings)
                    or execution != isinstance(config.execution_recovery, ContractorExecutionRecoverySettings)
                    or closeout != isinstance(recovery, ContractorCloseoutRecoveryBindings)
                    or closeout != isinstance(config.execution_recovery, ContractorCloseoutRecoverySettings)
                    or measurement != isinstance(recovery, ContractorMeasurementRecoveryBindings)
                    or measurement != isinstance(config.execution_recovery, ContractorMeasurementRecoverySettings)
                    or claim != isinstance(recovery, ContractorClaimRecoveryBindings)
                    or claim != isinstance(config.execution_recovery, ContractorClaimRecoverySettings)
                    or supply != isinstance(recovery, ContractorSupplyRecoveryBindings)
                    or supply != isinstance(config.execution_recovery, ContractorSupplyRecoverySettings)
                    or readiness != isinstance(recovery, ContractorReadinessRecoveryBindings)
                    or readiness != isinstance(config.execution_recovery, ContractorReadinessRecoverySettings)):
                raise ValueError('Contractor bid command recovery callbacks must bind their declared original action')
            assembler_type = (ContractorReadinessActionAssembler if readiness else ContractorPlanningActionAssembler if supply else ContractorClaimActionAssembler if claim else ContractorPaymentActionAssembler if measurement else ContractorCloseoutActionAssembler if closeout else ContractorExecutionActionAssembler if execution else
                ContractorAmendmentActionAssembler if amendment else ContractorFormationActionAssembler)
            reader_type = (ContractorReadinessRecoveryReader if readiness else ContractorSupplyRecoveryReader if supply else ContractorClaimRecoveryReader if claim else ContractorMeasurementRecoveryReader if measurement else ContractorCloseoutRecoveryReader if closeout else ContractorExecutionReader if execution else
                ContractorAmendmentCommandReader if amendment else ContractorFormationCommandReader)
            build_dispatcher = (build_assembled_contractor_readiness_dispatcher if readiness else build_assembled_contractor_supply_dispatcher if supply else build_assembled_contractor_claim_dispatcher if claim else build_assembled_contractor_measurement_dispatcher if measurement else build_assembled_contractor_closeout_dispatcher if closeout else build_assembled_contractor_execution_dispatcher if execution else
                build_assembled_contractor_amendment_command_dispatcher if amendment else
                build_assembled_contractor_formation_command_dispatcher)
            self.formation_assembler = assembler_type(registry=base.registry,
                organizations=base.organizations, provider=base.provider, methods=base.methods,
                macro_version=config.execution_recovery.macro_version, source_mode='formal',
                policy_version=config.execution_recovery.policy_version, model_version=config.model_version,
                model_host=model)
            selection = {} if execution or closeout or measurement or claim or supply or readiness else {'command_ids': config.execution_recovery.command_ids}
            self.command_reader = reader_type(assembler=self.formation_assembler,
                select_current=recovery.select_current, **selection,
                **({'snapshots': InvocationSnapshotStore(base.store)} if closeout or measurement or claim or supply or readiness else {}))
            self.execution_dispatcher = build_dispatcher(
                inbox=self.feedback.inbox, store=base.store, assembler=self.formation_assembler,
                select_current=recovery.select_current, **selection,
                read_guard=recovery.read_guard, validate_relation=recovery.validate_relation,
                project_signal=recovery.project_signal, prepare=recovery.prepare, revalidate=recovery.revalidate,
                **({'reader': self.command_reader} if closeout or measurement or claim or supply or readiness else {}))
            self._formation_recovery_components = (recovery, *recovery.components(), self.formation_assembler,
                self.command_reader, self.execution_dispatcher, self.feedback.inbox, base.provider)
        self._declared = self._configuration()
        self._key = 'contractor_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal Contractor application configuration changed; explicit review required')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.base.store.run_id,
            'settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'dependency_version': self.dependencies.version, 'source_version': self.base.version,
            'dependency_factory': self.factory_descriptor, 'sources': _descriptors(self.base),
            'code': module_factory_descriptor(type(self).sources, self.VERSION),
            'model_configuration_sha256': self.base.model_host.configuration_sha256,
            'execution_recovery': None if self.command_reader is None else {
                'reader': self.command_reader.configuration_evidence(),
                'callbacks': self.dependencies.execution_recovery.configuration_evidence()},
            'payment_reception': {
                'original_reader_configuration': self.dependencies.owner_payment_reader.configuration_evidence()
                    if self.dependencies.owner_payment_reader is not None else None,
                'validator': module_factory_descriptor(self.dependencies.validate_payment_reception, 'validate_payment_reception')
                    if self.dependencies.validate_payment_reception is not None else None},
            'submission_sha256': task_digest(self.submissions._declared) if self.submissions is not None else None,
            'feedback_sha256': task_digest(self.feedback._declared) if self.feedback is not None else None,
            'feedback_validators': {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in (('validate_feedback_relation', self.dependencies.validate_feedback_relation),
                    ('validate_feedback_read', self.dependencies.validate_feedback_read),
                    ('validate_feedback_input', self.dependencies.validate_feedback_input))},
            'submission_read_guard': module_factory_descriptor(self.dependencies.submission_read_guard, 'submission_read_guard')
                if self.dependencies.submission_read_guard is not None else None,
            'submission_callbacks': {action: {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in vars(callbacks).items()}
                for action, callbacks in sorted(self.dependencies.submission_callbacks.items())}}

    def _check(self):
        components = (self.base, self.base.store, self.base.registry,
            self.base.organizations, self.base.provider, self.base.model_host, self.base.commercial_worker)
        if (self._closed or any(actual is not original for actual, original in zip(components, self._components))
                or self.dependencies.sources is not self.base
                or any(actual is not original for actual, original in zip((self.dependencies.owner_payment_reader,
                    self.dependencies.validate_payment_reception), self._original_payment_reception_components))
                or self.base.model_host.store is not self.base.store or self.base.model_host.registry is not self.base.registry
                or self.base.model_host.model_version != self.settings.model_version
                or module_factory_descriptor(_load_factory(self.settings.dependency_factory),
                    self.settings.dependency_factory) != self.factory_descriptor
                or self._configuration() != self._declared):
            raise TaskConflict('Original formal Contractor components or configuration changed, or application closed')
        recovery = self.dependencies.execution_recovery
        if self._formation_recovery_components is None:
            if any(value is not None for value in (recovery, self.formation_assembler,
                    self.command_reader, self.execution_dispatcher)):
                raise TaskConflict('Undeclared Contractor formation recovery components were added')
        else:
            current = (recovery, *recovery.components(), self.formation_assembler, self.command_reader,
                self.execution_dispatcher, self.feedback.inbox, self.base.provider)
            assembler = self.formation_assembler
            if (any(actual is not original for actual, original in zip(current, self._formation_recovery_components))
                    or assembler.registry is not self.base.registry or assembler.organizations is not self.base.organizations
                    or (assembler._views[self.settings.action_id].provider is not self.base.provider
                        if self.settings.action_id == 'CONTRACTOR-A12' else assembler.provider is not self.base.provider)
                    or assembler.methods is not self.base.methods
                    or self.settings.action_id != 'CONTRACTOR-A12' and assembler.ACTION_ID != self.settings.action_id
                    or self.command_reader.ACTION_ID != self.settings.action_id
                    or self.execution_dispatcher.action_id != self.settings.action_id
                    or isinstance(self.settings.execution_recovery, ContractorFormationRecoverySettings)
                        and self.command_reader.command_ids != tuple(self.settings.execution_recovery.command_ids)
                    or len(assembler.decision_strategies) != len(self.base.model_host.bindings)
                    or any(actual is not original for actual, original in zip(
                        assembler.decision_strategies, self.base.model_host.bindings))):
                raise TaskConflict('Contractor formation recovery changed original source/model/command/callback bindings')
            self.command_reader._check()
            self.execution_dispatcher._check()
        if self.settings.payment_reception is not None:
            self.dependencies.owner_payment_reader._check()
            if self.dependencies.owner_payment_reader.settings != self.settings.payment_reception:
                raise TaskConflict('Formal Contractor original payment reader declaration changed')
        if self._require_commercial:
            _check_commercial_worker(self.base, self.settings)
        if self.submissions is not None:
            self.submissions._check()
            if ('CONTRACTOR-A12' in self.submissions.workers
                    and self.submissions.workers['CONTRACTOR-A12'] is not self.base.commercial_worker):
                raise TaskConflict('Formal Contractor submission substituted the original A12 worker')
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal Contractor submission components changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_relation is not self.dependencies.validate_feedback_relation
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal Contractor feedback components or validators changed')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal Contractor application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal Contractor source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'payment_reception_configured': self.settings.payment_reception is not None,
            'feedback_configured': self.feedback is not None,
            'execution_recovery_configured': self.execution_dispatcher is not None,
            'feedback_input_enabled': self.settings.feedback is not None and self.settings.feedback.input_enabled}

    def sources(self):
        self._check()
        enabled = self.settings.feedback is not None and self.settings.feedback.input_enabled
        sources = replace(self.base, version=self.VERSION,
            evidence=self.evidence,
            close=self.close,
            feedback=self.feedback if enabled else None,
            validate_feedback_input=self.dependencies.validate_feedback_input if enabled else None)
        if self.settings.payment_reception is not None:
            sources = bind_contractor_payment_reader(sources=sources,
                reader=self.dependencies.owner_payment_reader,
                validate_reception=self.dependencies.validate_payment_reception)
        return sources

    def _dispatch_submission(self, identity, operation):
        self._check()
        if self.submissions is None:
            raise ValueError('No actual Contractor submission routes are configured')
        result = getattr(self.submissions, operation)(identity)
        self._check()
        return result

    def submit(self, identity):
        return self._dispatch_submission(identity, 'submit')

    def recover(self, identity):
        return self._dispatch_submission(identity, 'recover')

    def read_receipt(self, identity):
        return self._dispatch_submission(identity, 'read_receipt')

    def resume_execution_waits(self, *, run_id, organization_id):
        """Explicitly query original bid/work executions before independent fresh judgment."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Contractor original execution recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def reconcile_commercial_execution(self, identity, *, signal):
        """Archive the actual original A12 outcome under current source authority."""
        from integration.commercial_terminal import reconcile_commercial_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'CONTRACTOR-A12' or not isinstance(settings, CommercialFormalRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Commercial reconciliation requires explicit A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_commercial_execution(identity=identity, signal=signal,
                reader=self.command_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_closeout_history(self, identity, *, signal):
        """Archive actual A11 request/account disposition while preserving unpaid debts and defect duties."""
        from integration.contractor_closeout_terminal import reconcile_contractor_closeout_history
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'CONTRACTOR-A11' or not isinstance(settings, ContractorCloseoutRecoverySettings)
                or not settings.terminal_history_enabled or self.execution_dispatcher is None):
            raise ValueError('Contractor closeout archive requires explicit original A11 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_contractor_closeout_history(identity=identity, signal=signal,
                reader=self.command_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the same configured action journal and protected callbacks to selected V7 waits."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Contractor original execution recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def reconcile_readiness_history(self, identity, *, signal):
        """Archive original task status while preserving actual release, work and remaining duties."""
        from integration.contractor_readiness_terminal import reconcile_contractor_readiness_history
        from src.coordination.contractor_readiness_conditions import STATE_CODE
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'CONTRACTOR-A06' or not isinstance(settings, ContractorReadinessRecoverySettings)
                or not settings.terminal_readiness_enabled or self.execution_dispatcher is None):
            raise ValueError('Readiness archive requires explicit original A06 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            source = self.base.store.get(identity)
            if len(source['conditions']) != 1 or source['conditions'][0]['condition_code'] != STATE_CODE:
                raise ValueError('Readiness cycle must resume its actual gates; it cannot archive the task wait')
            result = reconcile_contractor_readiness_history(identity=identity, signal=signal,
                reader=self.command_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_supply_history(self, identity, *, signal):
        """Archive actual original commitment status without inventing supply fulfilment."""
        from integration.contractor_supply_terminal import reconcile_contractor_supply_history
        from src.coordination.contractor_supply_conditions import CODE
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'CONTRACTOR-A05' or not isinstance(settings, ContractorSupplyRecoverySettings)
                or not settings.terminal_supply_enabled or self.execution_dispatcher is None):
            raise ValueError('Supply archive requires explicit original A05 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            source = self.base.store.get(identity)
            if len(source['conditions']) != 1 or source['conditions'][0]['condition_code'] != CODE:
                raise ValueError('Procurement limit wait must resume its authorized purchase; it cannot archive the action')
            result = reconcile_contractor_supply_history(identity=identity, signal=signal,
                reader=self.command_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_claim_history(self, identity, *, signal):
        """Archive original claim status without creating entitlement, debt or an extension."""
        from integration.contractor_claim_terminal import reconcile_contractor_claim_history
        from src.coordination.contractor_claim_conditions import CLAIM_CODE
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'CONTRACTOR-A09' or not isinstance(settings, ContractorClaimRecoverySettings)
                or not settings.terminal_claim_enabled or self.execution_dispatcher is None):
            raise ValueError('Claim archive requires explicit original A09 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            source = self.base.store.get(identity)
            if len(source['conditions']) != 1 or source['conditions'][0]['condition_code'] != CLAIM_CODE:
                raise ValueError('Notice deadline must resume its authorized procedure; it cannot archive the action wait')
            result = reconcile_contractor_claim_history(identity=identity, signal=signal,
                reader=self.command_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_measurement_history(self, identity, *, signal):
        """Archive actual original measurement outcome without issuing certificates or posting cash."""
        from integration.contractor_measurement_terminal import reconcile_contractor_measurement_history
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'CONTRACTOR-A10' or not isinstance(settings, ContractorMeasurementRecoverySettings)
                or not settings.terminal_measurement_enabled or self.execution_dispatcher is None):
            raise ValueError('Measurement archive requires explicit original A10 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_contractor_measurement_history(identity=identity, signal=signal,
                reader=self.command_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def record_feedback(self, identity, *, context, reading, observation):
        """Explicitly correlate actual feedback under current source/authorization guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Contractor actual feedback inbox is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            result = self.feedback.record(identity, context=context, reading=reading, observation=observation)
            self._check()
            return result

    def read_feedback(self, *, context, reading):
        """Read original persisted feedback under current recipient/scope authority."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Contractor actual feedback inbox is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            result = self.feedback.read(context=context, reading=reading)
            self._check()
            return result

    def close(self):
        if not self._closed:
            self._closed = True
            self.base.close()


def build_sources(*, request, output_directory, offline, settings):
    """role_contract source factory; no source, credential or model construction."""
    config = ContractorFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != config.action_id or config.action_id not in _ACTIONS):
        raise ValueError('Formal Contractor source factory requires its explicit non-offline original invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, ContractorFormalApplicationDependencies):
        raise ValueError('Actual Contractor dependency factory must return ContractorFormalApplicationDependencies')
    application = None
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual Contractor dependency factory changed during assembly')
        application = ContractorFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
