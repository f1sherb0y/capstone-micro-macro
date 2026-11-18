"""Configured formal bank application assembly over supplied actual dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field, replace
import importlib
import json
from pathlib import Path
from typing import Callable, Literal

from pydantic import model_serializer, model_validator

from integration.bank_role_contract_host import BankRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.bank_submission import BankSubmissionCallbacks
from integration.bank_submission_feedback import BankSubmissionFeedback
from integration.bank_submission_host import BankSubmissionHost, BankSubmissionHostConfiguration
from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, canonical, task_digest


class BankFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False


class BankFormalExecutionRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    wait_kind: Literal['execution_query', 'funding_cash', 'debt_receipts', 'notice_delivery', 'draw_batch'] = 'execution_query'
    terminal_existing_measure_enabled: bool = False
    terminal_draw_batch_enabled: bool = False
    terminal_learning_execution_enabled: bool = False
    terminal_resolution_execution_enabled: bool = False
    terminal_closeout_execution_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_query_configuration(self, handler):
        result = handler(self)
        if not self.terminal_existing_measure_enabled:
            result.pop('terminal_existing_measure_enabled', None)
        if not self.terminal_draw_batch_enabled:
            result.pop('terminal_draw_batch_enabled', None)
        if not self.terminal_learning_execution_enabled:
            result.pop('terminal_learning_execution_enabled', None)
        if not self.terminal_resolution_execution_enabled:
            result.pop('terminal_resolution_execution_enabled', None)
        if not self.terminal_closeout_execution_enabled:
            result.pop('terminal_closeout_execution_enabled', None)
        if self.wait_kind == 'execution_query':
            result.pop('wait_kind', None)
        return result


@dataclass(frozen=True)
class BankFormalExecutionRecoveryBindings:
    """Actual current selection, native validation and successor preparation.

    read_guard(run_id, organization_id) covers the persisted inbox, old/current
    sources, authority and continuation journal for the entire wake operation.
    """
    assembler: object
    select_current: Callable
    read_guard: Callable
    validate_relation: Callable
    project_signal: Callable
    prepare: Callable
    revalidate: Callable

    def components(self):
        return (self.assembler, self.select_current, self.read_guard, self.validate_relation,
            self.project_signal, self.prepare, self.revalidate)

    def configuration_evidence(self):
        assembler = self.assembler
        return {'macro_version': assembler.macro_version, 'policy_version': assembler.policy_version,
            'model_version': assembler.model_version, 'source_mode': assembler.source_mode,
            'assemble_current': module_factory_descriptor(assembler.build, 'assemble_current'),
            **{name: module_factory_descriptor(getattr(self, name), name) for name in (
                'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}}

    def __post_init__(self):
        if not all(callable(callback) for callback in self.components()[1:]):
            raise ValueError('Bank execution recovery requires actual selection, guard and validation callbacks')


class BankFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: BankSubmissionHostConfiguration | None = None
    feedback: BankFormalFeedbackSettings | None = None
    execution_recovery: BankFormalExecutionRecoverySettings | None = None

    @model_validator(mode='after')
    def validate_cash_recovery_action(self):
        if (self.execution_recovery is not None and self.execution_recovery.terminal_closeout_execution_enabled
                and (self.action_id != 'BANK-A11' or self.execution_recovery.wait_kind != 'execution_query')):
            raise ValueError('Bank closeout archive requires explicit BANK-A11 execution_query recovery')
        if (self.execution_recovery is not None and self.execution_recovery.terminal_resolution_execution_enabled
                and (self.action_id != 'BANK-A10' or self.execution_recovery.wait_kind != 'execution_query')):
            raise ValueError('Bank resolution archive requires explicit BANK-A10 execution_query recovery')
        if (self.execution_recovery is not None and self.execution_recovery.terminal_learning_execution_enabled
                and (self.action_id != 'BANK-A12' or self.execution_recovery.wait_kind != 'execution_query')):
            raise ValueError('Bank learning archive requires explicit BANK-A12 execution_query recovery')
        if (self.execution_recovery is not None and self.execution_recovery.wait_kind == 'draw_batch'
                and self.action_id != 'BANK-A06'):
            raise ValueError('Original draw batch recovery belongs only to BANK-A06')
        if (self.execution_recovery is not None and self.execution_recovery.terminal_draw_batch_enabled
                and (self.action_id != 'BANK-A06' or self.execution_recovery.wait_kind != 'draw_batch')):
            raise ValueError('Original draw batch archive requires explicit BANK-A06 draw_batch recovery')
        if (self.execution_recovery is not None and self.execution_recovery.terminal_existing_measure_enabled
                and (self.action_id != 'BANK-A08' or self.execution_recovery.wait_kind != 'notice_delivery')):
            raise ValueError('Existing measure archive requires explicit BANK-A08 notice_delivery recovery')
        if (self.execution_recovery is not None and self.execution_recovery.wait_kind == 'funding_cash'
                and self.action_id != 'BANK-A07'):
            raise ValueError('Bank cash recovery is only available for original BANK-A07 funding waits')
        if (self.execution_recovery is not None and self.execution_recovery.wait_kind == 'debt_receipts'
                and self.action_id != 'BANK-A09'):
            raise ValueError('Bank debt receipt recovery belongs only to original BANK-A09 allocation waits')
        if (self.execution_recovery is not None and self.execution_recovery.wait_kind == 'notice_delivery'
                and self.action_id != 'BANK-A08'):
            raise ValueError('Bank notice delivery recovery belongs only to original BANK-A08 monitoring waits')
        return self


@dataclass(frozen=True)
class BankFormalApplicationDependencies:
    """Application supplies actual sources and an already configured model host.

    The factory owns partial resources until this object is returned. No
    registry, provider, credential, transport or model client is invented here.
    All action workers use the supplied invocation/wait/recovery validators.
    """
    version: str
    sources: BankRoleContractSources
    submission_callbacks: dict[str, BankSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    execution_recovery: BankFormalExecutionRecoveryBindings | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, BankRoleContractSources)
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or not isinstance(self.submission_callbacks, dict)
                or self.execution_recovery is not None and not isinstance(
                    self.execution_recovery, BankFormalExecutionRecoveryBindings)
                or any(not isinstance(value, BankSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(value is not None and not callable(value) for value in (self.submission_read_guard,
                    self.validate_feedback_relation, self.validate_feedback_read, self.validate_feedback_input))):
            raise ValueError('Formal bank dependencies require original sources and explicit actual callback bindings')


class BankFormalApplication:
    """Assemble declared submission/feedback components; calls remain explicit.

    Actual source health and native endpoint support must be observed by the
    application. Assembly alone reports configured_unverified. Closing releases
    only the resources owned by the supplied application, once.
    """
    VERSION = 'bank-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = BankFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, BankFormalApplicationDependencies):
            raise ValueError('Formal bank factory must return BankFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version
                or not any(config.action_id in binding.action_ids for binding in model.bindings)
                or config.feedback is not None and config.submission is None):
            raise ValueError('Formal bank assembly requires original same-run sources/model host and configured feedback routes')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if (set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.feedback is not None and (not callable(dependencies.validate_feedback_relation)
                    or not callable(dependencies.validate_feedback_read)
                    or config.feedback.input_enabled and not callable(dependencies.validate_feedback_input))):
            raise ValueError('Configured bank submission/feedback requires all actual transport and relation callbacks')
        self.dependencies, self.base = dependencies, base
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model)
        self._closed = False
        self.submissions = self.feedback = self.execution_dispatcher = None
        self._recovery_components = None
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                if action_id not in _ACTIONS:
                    raise ValueError('Formal bank application requires a closed bank action route')
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.bank_' + module + '_results'),
                    'Bank' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = BankSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            self.feedback = BankSubmissionFeedback(host=self.submissions, inbox=inbox,
                version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                validate_read=dependencies.validate_feedback_read)
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('Bank execution recovery bindings must match explicit configuration')
        if recovery is not None:
            if self.feedback is None or config.action_id not in actions:
                raise ValueError('Bank execution recovery requires its original persisted feedback inbox')
            assembler_type, dispatcher_factory = self._recovery_types()
            assembler = recovery.assembler
            if (not isinstance(assembler, assembler_type) or assembler.ACTION_ID != config.action_id
                    or assembler.source_mode != 'formal' or assembler.registry is not base.registry
                    or assembler.organizations is not base.organizations or assembler.provider is not base.provider
                    or assembler.methods is not base.methods
                    or assembler.macro_version != config.execution_recovery.macro_version
                    or assembler.policy_version != config.execution_recovery.policy_version
                    or assembler.model_version != config.model_version
                    or len(assembler.decision_strategies) != len(model.bindings)
                    or any(actual is not original for actual, original in zip(assembler.decision_strategies, model.bindings))):
                raise ValueError('Bank recovery requires its original formal action assembler and source/model bindings')
            self.execution_dispatcher = dispatcher_factory(inbox=self.feedback.inbox, store=base.store,
                assembler=assembler, select_current=recovery.select_current, read_guard=recovery.read_guard,
                validate_relation=recovery.validate_relation, project_signal=recovery.project_signal,
                prepare=recovery.prepare, revalidate=recovery.revalidate)
            self._recovery_components = (recovery, *recovery.components(), self.execution_dispatcher,
                self.feedback.inbox)
        self._operation_components = (dependencies, self.submissions, self.feedback,
            dependencies.submission_read_guard, dependencies.validate_feedback_relation,
            dependencies.validate_feedback_read, dependencies.validate_feedback_input)
        self._declared = self._configuration()
        self._key = 'bank_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal bank application configuration changed; explicit review required')

    def _recovery_types(self):
        recovery = self.settings.execution_recovery
        if recovery is not None and recovery.wait_kind == 'draw_batch':
            if self.settings.action_id != 'BANK-A06':
                raise ValueError('Original draw batch recovery belongs only to BANK-A06')
            from integration.bank_draw_actions import BankDrawActionAssembler
            from integration.bank_draw_reader import build_assembled_bank_draw_batch_dispatcher
            return BankDrawActionAssembler, build_assembled_bank_draw_batch_dispatcher
        if recovery is not None and recovery.wait_kind == 'notice_delivery':
            if self.settings.action_id != 'BANK-A08':
                raise ValueError('Bank notice delivery recovery belongs only to original BANK-A08 monitoring waits')
            from integration.bank_monitoring_actions import BankMonitoringActionAssembler
            from integration.bank_monitoring_reader import build_assembled_bank_monitoring_notice_dispatcher
            return BankMonitoringActionAssembler, build_assembled_bank_monitoring_notice_dispatcher
        if recovery is not None and recovery.wait_kind == 'debt_receipts':
            if self.settings.action_id != 'BANK-A09':
                raise ValueError('Bank debt receipt recovery belongs only to original BANK-A09 allocation waits')
            from integration.bank_debt_actions import BankDebtActionAssembler
            from integration.bank_debt_reader import build_assembled_bank_debt_dispatcher
            return BankDebtActionAssembler, build_assembled_bank_debt_dispatcher
        if recovery is not None and recovery.wait_kind == 'funding_cash':
            if self.settings.action_id != 'BANK-A07':
                raise ValueError('Bank cash recovery is only available for original BANK-A07 funding waits')
            from integration.bank_execution_actions import BankExecutionActionAssembler
            from integration.bank_funding_reader import build_assembled_bank_funding_dispatcher

            return BankExecutionActionAssembler, build_assembled_bank_funding_dispatcher
        if self.settings.action_id == 'BANK-A07':
            from integration.bank_execution_actions import BankExecutionActionAssembler
            from integration.bank_payment_command_reader import build_assembled_bank_payment_command_dispatcher

            return BankExecutionActionAssembler, build_assembled_bank_payment_command_dispatcher
        modules = {'BANK-A10': ('resolution', 'Resolution'), 'BANK-A11': ('closeout', 'Closeout'),
            'BANK-A12': ('learning', 'Learning')}
        if self.settings.action_id not in modules:
            raise ValueError('Bank execution recovery supports only original A07/A10/A11/A12 query waits')
        module, name = modules[self.settings.action_id]
        actions = importlib.import_module('integration.bank_' + module + '_actions')
        reader = importlib.import_module('integration.bank_' + module + '_execution_reader')
        return (getattr(actions, 'Bank' + name + 'ActionAssembler'),
            getattr(reader, 'build_assembled_bank_' + module + '_execution_dispatcher'))

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.base.store.run_id,
            'settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'dependency_version': self.dependencies.version, 'source_version': self.base.version,
            'dependency_factory': self.factory_descriptor, 'sources': _descriptors(self.base),
            'code': module_factory_descriptor(type(self).sources, self.VERSION),
            'model_configuration_sha256': self.base.model_host.configuration_sha256,
            'submission_sha256': task_digest(self.submissions._declared) if self.submissions is not None else None,
            'feedback_sha256': task_digest(self.feedback._declared) if self.feedback is not None else None,
            'input_validator': module_factory_descriptor(self.dependencies.validate_feedback_input, 'validate_feedback_input')
                if self.settings.feedback is not None and self.settings.feedback.input_enabled else None,
            'execution_recovery': self.dependencies.execution_recovery.configuration_evidence()
                if self.dependencies.execution_recovery is not None else None}

    def _check(self):
        components = (self.base, self.base.store, self.base.registry,
            self.base.organizations, self.base.provider, self.base.model_host)
        operations = (self.dependencies, self.submissions, self.feedback,
            self.dependencies.submission_read_guard, self.dependencies.validate_feedback_relation,
            self.dependencies.validate_feedback_read, self.dependencies.validate_feedback_input)
        if (self._closed or any(actual is not original for actual, original in zip(components, self._components))
                or any(actual is not original for actual, original in zip(operations, self._operation_components))
                or self.dependencies.sources is not self.base
                or self.base.model_host.store is not self.base.store or self.base.model_host.registry is not self.base.registry
                or self.base.model_host.model_version != self.settings.model_version
                or module_factory_descriptor(_load_factory(self.settings.dependency_factory),
                    self.settings.dependency_factory) != self.factory_descriptor
                or self._configuration() != self._declared):
            raise TaskConflict('Original formal bank application components/configuration changed or closed')
        if self.submissions is not None:
            self.submissions._check()
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or set(self.submissions.callbacks) != set(self.dependencies.submission_callbacks)
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal bank submission components or actual callbacks changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_relation is not self.dependencies.validate_feedback_relation
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal bank feedback components or actual validators changed')
        recovery = self.dependencies.execution_recovery
        if self._recovery_components is None and (recovery is not None or self.execution_dispatcher is not None):
            raise TaskConflict('Undeclared Bank execution recovery components were added')
        if self._recovery_components is not None:
            current = (recovery, *recovery.components(), self.execution_dispatcher, self.feedback.inbox)
            assembler = recovery.assembler
            if (any(actual is not original for actual, original in zip(current, self._recovery_components))
                    or assembler.registry is not self.base.registry or assembler.organizations is not self.base.organizations
                    or assembler.provider is not self.base.provider or assembler.methods is not self.base.methods
                    or len(assembler.decision_strategies) != len(self.base.model_host.bindings)
                    or any(actual is not original for actual, original in zip(
                        assembler.decision_strategies, self.base.model_host.bindings))):
                raise TaskConflict('Formal bank execution recovery source or callback bindings changed')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal bank application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal bank application source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'feedback_configured': self.feedback is not None,
            'execution_recovery_configured': self.execution_dispatcher is not None,
            'feedback_input_enabled': self.settings.feedback is not None and self.settings.feedback.input_enabled}

    def sources(self):
        self._check()
        enabled = self.settings.feedback is not None and self.settings.feedback.input_enabled
        return replace(self.base, version=self.VERSION,
            evidence=self.evidence,
            close=self.close,
            feedback=self.feedback if enabled else None,
            validate_feedback_input=self.dependencies.validate_feedback_input if enabled else None)

    def _dispatch_submission(self, identity, operation):
        self._check()
        if self.submissions is None:
            raise ValueError('No actual Bank submission routes are configured')
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
        """Explicitly evaluate saved feedback and queue independently checked successors."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Bank original execution wait recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def reconcile_existing_monitoring_measure(self, identity, *, signal):
        """Archive actual original measures without submitting or repeating notices."""
        from integration.bank_monitoring_terminal import reconcile_existing_monitoring_measure
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'BANK-A08' or settings is None or settings.wait_kind != 'notice_delivery'
                or not settings.terminal_existing_measure_enabled or self.execution_dispatcher is None):
            raise ValueError('Existing measure archive requires explicit BANK-A08 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_existing_monitoring_measure(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_original_draw_batch(self, identity, *, signal):
        """Archive actual original batch outcomes without approving or transferring again."""
        from integration.bank_draw_reader import reconcile_original_draw_batch
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'BANK-A06' or settings is None or settings.wait_kind != 'draw_batch'
                or not settings.terminal_draw_batch_enabled or self.execution_dispatcher is None):
            raise ValueError('Original draw batch archive requires explicit BANK-A06 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_original_draw_batch(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_learning_execution(self, identity, *, signal):
        """Archive actual original learning without repeating a policy or outcome application."""
        from integration.bank_learning_terminal import reconcile_bank_learning_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'BANK-A12' or settings is None or settings.wait_kind != 'execution_query'
                or not settings.terminal_learning_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Bank learning archive requires explicit BANK-A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_bank_learning_execution(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_resolution_execution(self, identity, *, signal):
        """Archive actual original resolution without replaying or clearing debt."""
        from integration.bank_resolution_terminal import reconcile_bank_resolution_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'BANK-A10' or settings is None or settings.wait_kind != 'execution_query'
                or not settings.terminal_resolution_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Bank resolution archive requires explicit BANK-A10 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_bank_resolution_execution(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_closeout_execution(self, identity, *, signal):
        """Archive actual original closure while preserving all remaining obligations."""
        from integration.bank_closeout_terminal import reconcile_bank_closeout_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'BANK-A11' or settings is None or settings.wait_kind != 'execution_query'
                or not settings.terminal_closeout_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Bank closeout archive requires explicit BANK-A11 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_bank_closeout_execution(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the same assembled journal to one explicitly selected V7 wait."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Bank original execution wait recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def record_feedback(self, identity, *, context, reading, observation):
        """Correlate explicitly supplied actual feedback under the source guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Bank actual feedback inbox is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            result = self.feedback.record(identity, context=context, reading=reading, observation=observation)
            self._check()
            return result

    def read_feedback(self, *, context, reading):
        """Read saved feedback under current recipient and source authority."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Bank actual feedback inbox is configured')
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
    """Configured role_contract source factory; never construct or call a model."""
    config = BankFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if offline is not False or request.context.execution_mode != 'llm' or request.context.contract_ref.id != config.action_id:
        raise ValueError('Formal bank source factory requires its explicit original non-offline invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, BankFormalApplicationDependencies):
        raise ValueError('Actual bank dependency factory must return BankFormalApplicationDependencies')
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual bank dependency factory changed during assembly')
        application = BankFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        dependencies.sources.close()
        raise
