"""Configured formal Supplier application assembly over original actual dependencies."""
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
from integration.supplier_role_contract_host import SupplierRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.supplier_submission import SupplierSubmissionCallbacks
from integration.supplier_submission_feedback import SupplierSubmissionFeedback
from integration.supplier_logistics_actions import SupplierLogisticsActionAssembler
from integration.supplier_execution_actions import SupplierExecutionActionAssembler
from integration.supplier_remedy_actions import SupplierRemedyActionAssembler
from integration.supplier_receiving_actions import SupplierReceivingActionAssembler
from integration.supplier_payment_actions import SupplierPaymentActionAssembler
from integration.supplier_planning_actions import SupplierPlanningActionAssembler
from integration.supplier_screening_actions import SupplierScreeningActionAssembler
from integration.supplier_policy_recovery_reader import (
    SupplierPolicyRecoveryReader, SupplierPolicyRecoverySettings, SupplierPolicyRecoveryBindings,
    build_assembled_supplier_policy_dispatcher,
)
from integration.supplier_procurement_recovery_reader import (
    SupplierProcurementRecoveryReader, SupplierProcurementRecoverySettings, SupplierProcurementRecoveryBindings,
    build_assembled_supplier_procurement_dispatcher,
)
from integration.supplier_payment_recovery_reader import (
    SupplierPaymentRecoveryReader, SupplierPaymentRecoverySettings, SupplierPaymentRecoveryBindings,
    build_assembled_supplier_payment_dispatcher,
)
from integration.supplier_receiving_recovery_reader import (
    SupplierReceivingRecoveryReader, SupplierReceivingRecoverySettings, SupplierReceivingRecoveryBindings,
    build_assembled_supplier_receiving_dispatcher,
)
from integration.supplier_remedy_recovery_reader import (
    SupplierRemedyRecoveryReader, SupplierRemedyRecoverySettings, SupplierRemedyRecoveryBindings,
    build_assembled_supplier_remedy_dispatcher,
)
from integration.supplier_execution_reader import (
    SupplierExecutionReader, SupplierExecutionRecoveryBindings, SupplierExecutionRecoverySettings,
    build_assembled_supplier_execution_dispatcher,
)
from integration.supplier_resource_reader import (
    SupplierResourceReader, SupplierResourceRecoveryBindings, SupplierResourceRecoverySettings,
    build_assembled_supplier_resource_dispatcher,
)
from integration.supplier_inventory_reader import (
    SupplierInventoryReader, SupplierInventoryRecoveryBindings, SupplierInventoryRecoverySettings,
    build_assembled_supplier_inventory_dispatcher,
)
from integration.supplier_quality_actions import SupplierQualityActionAssembler
from integration.supplier_quality_reader import (
    SupplierQualityReader, SupplierQualityRecoveryBindings, SupplierQualityRecoverySettings,
    build_assembled_supplier_quality_dispatcher,
)
from integration.supplier_transport_reader import (
    SupplierTransportReader, SupplierTransportRecoveryBindings, SupplierTransportRecoverySettings,
    build_assembled_supplier_transport_dispatcher,
)
from integration.supplier_submission_host import SupplierSubmissionHost, SupplierSubmissionHostConfiguration
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, canonical, task_digest


class SupplierFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False


class SupplierFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: SupplierSubmissionHostConfiguration | None = None
    feedback: SupplierFormalFeedbackSettings | None = None
    execution_recovery: CommercialFormalRecoverySettings | SupplierQualityRecoverySettings | SupplierInventoryRecoverySettings | SupplierResourceRecoverySettings | SupplierExecutionRecoverySettings | SupplierTransportRecoverySettings | SupplierRemedyRecoverySettings | SupplierReceivingRecoverySettings | SupplierPaymentRecoverySettings | SupplierProcurementRecoverySettings | SupplierPolicyRecoverySettings | None = None

    @model_validator(mode='before')
    @classmethod
    def select_original_recovery_settings(cls, value):
        if not isinstance(value, dict) or value.get('execution_recovery') is None:
            return value
        recovery = value['execution_recovery']
        action_id = value.get('action_id')
        types = {'SUPPLIER-A01': SupplierPolicyRecoverySettings, 'SUPPLIER-A05': SupplierProcurementRecoverySettings,
            'SUPPLIER-A06': SupplierExecutionRecoverySettings, 'SUPPLIER-A07': SupplierQualityRecoverySettings,
            'SUPPLIER-A08': SupplierTransportRecoverySettings, 'SUPPLIER-A12': CommercialFormalRecoverySettings,
            'SUPPLIER-A11': SupplierRemedyRecoverySettings, 'SUPPLIER-A09': SupplierReceivingRecoverySettings,
            'SUPPLIER-A10': SupplierPaymentRecoverySettings}
        if action_id not in types:
            raise ValueError('Supplier recovery requires original A01/A05/A06/A07/A08/A09/A10/A11/A12 action configuration')
        settings_type = types[action_id]
        resource_query = (isinstance(recovery, SupplierResourceRecoverySettings)
            or isinstance(recovery, dict) and recovery.get('wait_kind') == 'resource_query')
        if resource_query:
            if action_id != 'SUPPLIER-A06':
                raise ValueError('Supplier resource query recovery is only available for original A06 production waits')
            settings_type = SupplierResourceRecoverySettings
        inventory_query = (isinstance(recovery, SupplierInventoryRecoverySettings)
            or isinstance(recovery, dict) and recovery.get('wait_kind') == 'inventory_query')
        if inventory_query:
            if action_id != 'SUPPLIER-A06':
                raise ValueError('Supplier inventory query recovery is only available for original A06 production waits')
            settings_type = SupplierInventoryRecoverySettings
        if isinstance(recovery, SupplierTransportRecoverySettings) and type(recovery) is not settings_type:
            raise ValueError('Supplier execution recovery configuration changes original action type')
        if isinstance(recovery, CommercialFormalRecoverySettings) and settings_type is not CommercialFormalRecoverySettings:
            raise ValueError('Commercial recovery settings belong only to Supplier A12')
        return {**value, 'execution_recovery': settings_type.model_validate(recovery)}


@dataclass(frozen=True)
class SupplierFormalApplicationDependencies:
    """Actual application supplies original sources and an existing model host.

    The factory owns partial resources until returning this bundle. Original
    invocation/wait/recovery validators apply to all submission workers; actual
    action-specific transport and business validation are explicitly supplied.
    """
    version: str
    sources: SupplierRoleContractSources
    submission_callbacks: dict[str, SupplierSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    execution_recovery: CommercialFormalRecoveryBindings | SupplierQualityRecoveryBindings | SupplierInventoryRecoveryBindings | SupplierResourceRecoveryBindings | SupplierExecutionRecoveryBindings | SupplierTransportRecoveryBindings | SupplierRemedyRecoveryBindings | SupplierReceivingRecoveryBindings | SupplierPaymentRecoveryBindings | SupplierProcurementRecoveryBindings | SupplierPolicyRecoveryBindings | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, SupplierRoleContractSources)
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or not isinstance(self.submission_callbacks, dict)
                or self.execution_recovery is not None and not isinstance(
                    self.execution_recovery, (CommercialFormalRecoveryBindings, SupplierTransportRecoveryBindings))
                or any(not isinstance(value, SupplierSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(callback is not None and not callable(callback) for callback in
                    (self.submission_read_guard, self.validate_feedback_relation,
                        self.validate_feedback_read, self.validate_feedback_input))):
            raise ValueError('Formal Supplier dependencies require original sources and actual callback bindings')


def _check_commercial_worker(base, config):
    """Retain the application's existing A12 assembler, journal and model binding."""
    worker = base.commercial_worker
    if not isinstance(worker, CommercialTaskWorker):
        raise ValueError('Formal Supplier A12 requires the original commercial worker and wait journal')
    assembler = worker.assembler
    view = assembler._views['SUPPLIER-A12']
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
        raise TaskConflict('Formal Supplier A12 changes its original commercial sources, versions or callbacks')


class SupplierFormalApplication:
    """Assemble original workers and configured routes; business calls stay explicit.

    Source health and native endpoint effects require observed application
    evidence. Construction is configured_unverified and never runs an action,
    sends a submission, constructs a model client or invents a native source.
    A12 keeps the supplied commercial worker and wait journal. Supply routes
    require the actual application transport; no order, inventory, production,
    delivery or payment effect is inferred from configuration or a receipt.
    """
    VERSION = 'supplier-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = SupplierFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, SupplierFormalApplicationDependencies):
            raise ValueError('Formal Supplier factory must return SupplierFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version):
            raise ValueError('Formal Supplier assembly requires original same-run sources and configured model host')
        registration = base.registry.get(config.action_id)
        if (registration.role != 'Supplier' or not registration.implemented or registration.skill is None
                or request.execution_path not in {None, registration.strategy}
                or not any(config.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Formal Supplier application requires its original implemented action and bound strategy')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if (not actions <= set(_ACTIONS) or set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.submission is None and dependencies.submission_read_guard is not None):
            raise ValueError('Configured Supplier submission must match its explicit callbacks and current read guard')
        if config.feedback is not None:
            if (config.submission is None or not actions
                    or not callable(dependencies.validate_feedback_relation)
                    or not callable(dependencies.validate_feedback_read)):
                raise ValueError('Supplier feedback requires configured submission routes and actual relation/read validators')
        elif dependencies.validate_feedback_relation is not None or dependencies.validate_feedback_read is not None:
            raise ValueError('Supplier feedback validators require an explicit feedback configuration')
        input_enabled = config.feedback is not None and config.feedback.input_enabled
        if (input_enabled and not callable(dependencies.validate_feedback_input)
                or not input_enabled and dependencies.validate_feedback_input is not None):
            raise ValueError('Supplier feedback input validation must match the explicit input-enabled configuration')
        self._require_commercial = config.action_id == 'SUPPLIER-A12' or 'SUPPLIER-A12' in actions
        if self._require_commercial:
            _check_commercial_worker(base, config)
        self.dependencies, self.base = dependencies, base
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model, base.commercial_worker)
        self._closed = False
        self.submissions = self.feedback = self.execution_dispatcher = None
        self.transport_assembler = self.transport_reader = None
        self._transport_recovery_components = None
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                if action_id == 'SUPPLIER-A12':
                    workers[action_id] = base.commercial_worker
                    continue
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.supplier_' + module + '_results'),
                    'Supplier' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = SupplierSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            self.feedback = SupplierSubmissionFeedback(host=self.submissions, inbox=inbox,
                version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                validate_read=dependencies.validate_feedback_read)
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('Supplier execution recovery must match its explicit configuration')
        if recovery is not None and config.action_id == 'SUPPLIER-A12':
            if (type(recovery) is not CommercialFormalRecoveryBindings
                    or type(config.execution_recovery) is not CommercialFormalRecoverySettings
                    or config.action_id not in actions or self.feedback is None):
                raise ValueError('Supplier A12 recovery requires original commercial callbacks, submission and feedback routes')
            _check_commercial_worker(base, config)
            self.transport_assembler = base.commercial_worker.assembler
            view = self.transport_assembler._views[config.action_id]
            if (view.macro_version != config.execution_recovery.macro_version
                    or self.transport_assembler.policy_version != config.execution_recovery.policy_version):
                raise ValueError('Supplier A12 recovery must retain original commercial source/policy versions')
            self.transport_reader = CommercialFormalRecoveryReader(worker=base.commercial_worker,
                bindings=recovery, action_id=config.action_id)
            self.execution_dispatcher = build_formal_commercial_recovery(inbox=self.feedback.inbox,
                worker=base.commercial_worker, bindings=recovery, action_id=config.action_id, reader=self.transport_reader)
            self._transport_recovery_components = (recovery, *recovery.components(), self.transport_assembler,
                self.transport_reader, self.execution_dispatcher, self.feedback.inbox, base.provider)
        elif recovery is not None:
            if isinstance(recovery, CommercialFormalRecoveryBindings):
                raise ValueError('Commercial recovery callbacks belong only to Supplier A12')
            if config.action_id not in {'SUPPLIER-A01', 'SUPPLIER-A05', 'SUPPLIER-A06', 'SUPPLIER-A07', 'SUPPLIER-A08', 'SUPPLIER-A09', 'SUPPLIER-A10', 'SUPPLIER-A11'} or config.action_id not in actions or self.feedback is None:
                raise ValueError('Supplier recovery requires original A01/A05/A06/A07/A08/A09/A10/A11 submission and feedback routes')
            assembler_type, reader_type, dispatcher_factory, bindings_type = self._recovery_types()
            if type(recovery) is not bindings_type:
                raise ValueError('Supplier execution recovery callbacks change original production/transport action')
            self.transport_assembler = assembler_type(registry=base.registry,
                organizations=base.organizations, provider=base.provider, methods=base.methods,
                macro_version=config.execution_recovery.macro_version, source_mode='formal',
                policy_version=config.execution_recovery.policy_version, model_version=config.model_version,
                model_host=model)
            reader_options = ({'snapshots': InvocationSnapshotStore(base.store)}
                if reader_type in {SupplierResourceReader, SupplierInventoryReader, SupplierQualityReader, SupplierRemedyRecoveryReader, SupplierReceivingRecoveryReader, SupplierPaymentRecoveryReader, SupplierProcurementRecoveryReader, SupplierPolicyRecoveryReader} else {})
            self.transport_reader = reader_type(assembler=self.transport_assembler,
                select_current=recovery.select_current, **reader_options)
            self.execution_dispatcher = dispatcher_factory(
                inbox=self.feedback.inbox, store=base.store, assembler=self.transport_assembler,
                select_current=recovery.select_current, read_guard=recovery.read_guard,
                validate_relation=recovery.validate_relation, project_signal=recovery.project_signal,
                prepare=recovery.prepare, revalidate=recovery.revalidate,
                **({'reader': self.transport_reader} if reader_type in {SupplierRemedyRecoveryReader, SupplierReceivingRecoveryReader, SupplierPaymentRecoveryReader, SupplierProcurementRecoveryReader, SupplierPolicyRecoveryReader} else {}))
            self._transport_recovery_components = (recovery, *recovery.components(), self.transport_assembler,
                self.transport_reader, self.execution_dispatcher, self.feedback.inbox, base.provider)
        self._declared = self._configuration()
        self._key = 'supplier_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal Supplier application configuration changed; explicit review required')

    def _recovery_types(self):
        if self.settings.action_id == 'SUPPLIER-A01':
            return (SupplierScreeningActionAssembler, SupplierPolicyRecoveryReader,
                build_assembled_supplier_policy_dispatcher, SupplierPolicyRecoveryBindings)
        if self.settings.action_id == 'SUPPLIER-A05':
            return (SupplierPlanningActionAssembler, SupplierProcurementRecoveryReader,
                build_assembled_supplier_procurement_dispatcher, SupplierProcurementRecoveryBindings)
        if self.settings.action_id == 'SUPPLIER-A10':
            return (SupplierPaymentActionAssembler, SupplierPaymentRecoveryReader,
                build_assembled_supplier_payment_dispatcher, SupplierPaymentRecoveryBindings)
        if self.settings.action_id == 'SUPPLIER-A09':
            return (SupplierReceivingActionAssembler, SupplierReceivingRecoveryReader,
                build_assembled_supplier_receiving_dispatcher, SupplierReceivingRecoveryBindings)
        if self.settings.action_id == 'SUPPLIER-A11':
            return (SupplierRemedyActionAssembler, SupplierRemedyRecoveryReader,
                build_assembled_supplier_remedy_dispatcher, SupplierRemedyRecoveryBindings)
        if self.settings.action_id == 'SUPPLIER-A06':
            if isinstance(self.settings.execution_recovery, SupplierInventoryRecoverySettings):
                return (SupplierExecutionActionAssembler, SupplierInventoryReader,
                    build_assembled_supplier_inventory_dispatcher, SupplierInventoryRecoveryBindings)
            if isinstance(self.settings.execution_recovery, SupplierResourceRecoverySettings):
                return (SupplierExecutionActionAssembler, SupplierResourceReader,
                    build_assembled_supplier_resource_dispatcher, SupplierResourceRecoveryBindings)
            return (SupplierExecutionActionAssembler, SupplierExecutionReader,
                build_assembled_supplier_execution_dispatcher, SupplierExecutionRecoveryBindings)
        if self.settings.action_id == 'SUPPLIER-A07':
            return (SupplierQualityActionAssembler, SupplierQualityReader,
                build_assembled_supplier_quality_dispatcher, SupplierQualityRecoveryBindings)
        if self.settings.action_id == 'SUPPLIER-A08':
            return (SupplierLogisticsActionAssembler, SupplierTransportReader,
                build_assembled_supplier_transport_dispatcher, SupplierTransportRecoveryBindings)
        raise ValueError('Supplier execution recovery requires an original configured A05–A11 action')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.base.store.run_id,
            'settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'dependency_version': self.dependencies.version, 'source_version': self.base.version,
            'dependency_factory': self.factory_descriptor, 'sources': _descriptors(self.base),
            'code': module_factory_descriptor(type(self).sources, self.VERSION),
            'model_configuration_sha256': self.base.model_host.configuration_sha256,
            'execution_recovery': None if self.transport_reader is None else {
                'reader': self.transport_reader.configuration_evidence(),
                'callbacks': self.dependencies.execution_recovery.configuration_evidence()},
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
                or self.base.model_host.store is not self.base.store or self.base.model_host.registry is not self.base.registry
                or self.base.model_host.model_version != self.settings.model_version
                or module_factory_descriptor(_load_factory(self.settings.dependency_factory),
                    self.settings.dependency_factory) != self.factory_descriptor
                or self._configuration() != self._declared):
            raise TaskConflict('Original formal Supplier components or configuration changed, or application closed')
        recovery = self.dependencies.execution_recovery
        if self._transport_recovery_components is None:
            if any(value is not None for value in (recovery, self.transport_assembler,
                    self.transport_reader, self.execution_dispatcher)):
                raise TaskConflict('Undeclared Supplier execution recovery components were added')
        else:
            current = (recovery, *recovery.components(), self.transport_assembler, self.transport_reader,
                self.execution_dispatcher, self.feedback.inbox, self.base.provider)
            assembler = self.transport_assembler
            if (any(actual is not original for actual, original in zip(current, self._transport_recovery_components))
                    or assembler.registry is not self.base.registry or assembler.organizations is not self.base.organizations
                    or (assembler._views[self.settings.action_id].provider is not self.base.provider
                        if self.settings.action_id == 'SUPPLIER-A12' else assembler.view_provider is not self.base.provider)
                    or assembler.methods is not self.base.methods
                    or self.transport_reader.ACTION_ID != self.settings.action_id
                    or self.execution_dispatcher.action_id != self.settings.action_id
                    or len(assembler.decision_strategies) != len(self.base.model_host.bindings)
                    or any(actual is not original for actual, original in zip(
                        assembler.decision_strategies, self.base.model_host.bindings))):
                raise TaskConflict('Supplier execution recovery changed original source/model/recipient/callback bindings')
            self.transport_reader._check()
            self.execution_dispatcher._check()
        if self._require_commercial:
            _check_commercial_worker(self.base, self.settings)
        if self.submissions is not None:
            self.submissions._check()
            if ('SUPPLIER-A12' in self.submissions.workers
                    and self.submissions.workers['SUPPLIER-A12'] is not self.base.commercial_worker):
                raise TaskConflict('Formal Supplier submission substituted the original A12 worker')
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal Supplier submission components changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_relation is not self.dependencies.validate_feedback_relation
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal Supplier feedback components or validators changed')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal Supplier application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal Supplier source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'feedback_configured': self.feedback is not None,
            'execution_recovery_configured': self.execution_dispatcher is not None,
            'feedback_input_enabled': self.settings.feedback is not None and self.settings.feedback.input_enabled}

    def sources(self):
        self._check()
        enabled = self.settings.feedback is not None and self.settings.feedback.input_enabled
        # Preserve the application's original lineage workers and validators.
        # Reconstructing only core fields drops the A04-to-A09 handoff bindings.
        return replace(self.base, version=self.VERSION, evidence=self.evidence, close=self.close,
            feedback=self.feedback if enabled else None,
            validate_feedback_input=self.dependencies.validate_feedback_input if enabled else None)

    def _dispatch_submission(self, identity, operation):
        self._check()
        if self.submissions is None:
            raise ValueError('No actual Supplier submission routes are configured')
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
        """Explicitly query original production/transport before independent reconciliation."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Supplier original execution recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def reconcile_commercial_execution(self, identity, *, signal):
        """Archive the actual original A12 outcome under current source authority."""
        from integration.commercial_terminal import reconcile_commercial_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'SUPPLIER-A12' or not isinstance(settings, CommercialFormalRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Commercial reconciliation requires explicit A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_commercial_execution(identity=identity, signal=signal,
                reader=self.transport_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_procurement_history(self, identity, *, signal):
        """Archive original procurement disposition; upstream fulfilment remains independent."""
        from integration.supplier_procurement_terminal import reconcile_supplier_procurement_history
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'SUPPLIER-A05' or not isinstance(settings, SupplierProcurementRecoverySettings)
                or not settings.terminal_procurement_enabled or self.execution_dispatcher is None):
            raise ValueError('Procurement archive requires explicit original A05 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_supplier_procurement_history(identity=identity, signal=signal,
                reader=self.transport_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_remedy_history(self, identity, *, signal):
        """Archive actual original remedy/refund disposition without creating physical work or cash."""
        from integration.supplier_remedy_terminal import reconcile_supplier_remedy_history
        from src.coordination.supplier_remedy_conditions import REQUEST_CODE, REFUND_CODE
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'SUPPLIER-A11' or not isinstance(settings, SupplierRemedyRecoverySettings)
                or self.execution_dispatcher is None):
            raise ValueError('Supplier remedy archive requires explicit original A11 recovery configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            source = self.base.store.get(identity)
            code = source['conditions'][0]['condition_code'] if len(source['conditions']) == 1 else None
            if not ((code == REQUEST_CODE and settings.terminal_history_enabled)
                    or (code == REFUND_CODE and settings.terminal_refund_enabled)):
                raise ValueError('Supplier remedy archive requires its explicitly enabled request or refund terminal route')
            result = reconcile_supplier_remedy_history(identity=identity, signal=signal,
                reader=self.transport_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the same recovery journal and protected callbacks to selected V7 waits."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Supplier original execution recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def reconcile_receiving_replacement(self, identity, *, signal):
        """Archive original replacement disposition without creating dispatch or received stock."""
        from integration.supplier_receiving_terminal import reconcile_supplier_receiving_replacement
        from src.coordination.supplier_receiving_conditions import REPLACEMENT_CODE
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'SUPPLIER-A09' or not isinstance(settings, SupplierReceivingRecoverySettings)
                or not settings.terminal_replacement_enabled or self.execution_dispatcher is None):
            raise ValueError('Receiving replacement archive requires explicit original A09 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            source = self.base.store.get(identity)
            if len(source['conditions']) != 1 or source['conditions'][0]['condition_code'] != REPLACEMENT_CODE:
                raise ValueError('Shipment query must resume receiving; it cannot archive the receiving response wait')
            result = reconcile_supplier_receiving_replacement(identity=identity, signal=signal,
                reader=self.transport_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_payment_claim(self, identity, *, signal):
        """Archive original same-business claim disposition without recognizing debt or paid cash."""
        from integration.supplier_payment_terminal import reconcile_supplier_payment_claim
        from src.coordination.supplier_payment_conditions import SAME_CODE
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'SUPPLIER-A10' or not isinstance(settings, SupplierPaymentRecoverySettings)
                or not settings.terminal_claim_enabled or self.execution_dispatcher is None):
            raise ValueError('Supplier claim archive requires explicit original A10 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            source = self.base.store.get(identity)
            if len(source['conditions']) != 1 or source['conditions'][0]['condition_code'] != SAME_CODE:
                raise ValueError('Overlapping contract-node claims must resume the original pending proposal')
            result = reconcile_supplier_payment_claim(identity=identity, signal=signal,
                reader=self.transport_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def record_feedback(self, identity, *, context, reading, observation):
        """Explicitly correlate actual feedback under current source/authorization guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Supplier actual feedback inbox is configured')
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
            raise ValueError('No Supplier actual feedback inbox is configured')
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
    config = SupplierFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != config.action_id or config.action_id not in _ACTIONS):
        raise ValueError('Formal Supplier source factory requires its explicit non-offline original invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, SupplierFormalApplicationDependencies):
        raise ValueError('Actual Supplier dependency factory must return SupplierFormalApplicationDependencies')
    application = None
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual Supplier dependency factory changed during assembly')
        application = SupplierFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
