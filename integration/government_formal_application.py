"""Configured formal Government application assembly over original actual dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field, replace
import importlib
import json
from pathlib import Path
from typing import Callable

from pydantic import model_validator

from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from integration.government_role_contract_host import GovernmentRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.government_submission import GovernmentSubmissionCallbacks
from integration.government_submission_feedback import GovernmentSubmissionFeedback
from integration.government_inspection_actions import GovernmentInspectionActionAssembler
from integration.government_scheduling_actions import GovernmentSchedulingActionAssembler
from integration.government_review_actions import GovernmentReviewActionAssembler
from integration.government_consultation_actions import GovernmentConsultationActionAssembler
from integration.government_supplement_actions import GovernmentSupplementActionAssembler
from integration.government_decision_actions import GovernmentDecisionActionAssembler
from integration.government_decision_reader import (
    GovernmentDecisionReader, GovernmentDecisionRecoverySettings, GovernmentDecisionRecoveryBindings,
    build_assembled_government_decision_dispatcher,
)
from integration.government_supplement_reader import (
    GovernmentSupplementReader, GovernmentSupplementRecoverySettings, GovernmentSupplementRecoveryBindings,
    build_assembled_government_supplement_dispatcher,
)
from integration.government_consultation_reader import (
    GovernmentConsultationReader, GovernmentConsultationRecoverySettings, GovernmentConsultationRecoveryBindings,
    build_assembled_government_consultation_dispatcher,
)
from integration.government_review_reader import (
    GovernmentReviewReader, GovernmentReviewRecoverySettings, GovernmentReviewRecoveryBindings,
    build_assembled_government_review_dispatcher,
)
from integration.government_scheduling_reader import (
    GovernmentSchedulingReader, GovernmentSchedulingRecoverySettings, GovernmentSchedulingRecoveryBindings,
    build_assembled_government_scheduling_dispatcher,
)
from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoveryBindings, GovernmentInspectionRecoverySettings,
    build_assembled_government_inspection_dispatcher,
)
from integration.government_use_actions import GovernmentUseActionAssembler
from integration.government_use_reader import (
    GovernmentUseReader, GovernmentUseRecoveryBindings, GovernmentUseRecoverySettings,
    build_assembled_government_use_dispatcher,
)
from integration.government_submission_host import GovernmentSubmissionHost, GovernmentSubmissionHostConfiguration
from integration.government_decision_notification_transport import (
    GovernmentDecisionNotificationSettings, GovernmentDecisionNotificationCallbacks,
    GovernmentDecisionNotificationTransport,
)
from integration.government_permit_actions import GovernmentPermitActionAssembler
from integration.government_permit_reader import (
    GovernmentPermitReader, GovernmentPermitRecoverySettings, GovernmentPermitRecoveryBindings,
    build_assembled_government_permit_dispatcher,
)
from integration.government_transition_actions import GovernmentTransitionActionAssembler
from integration.government_transition_reader import (
    GovernmentTransitionReader, GovernmentTransitionRecoverySettings, GovernmentTransitionRecoveryBindings,
    build_assembled_government_transition_dispatcher,
)
from integration.government_transition_notification_transport import GovernmentTransitionNotificationTransport
from integration.government_feedback_actions import GovernmentFeedbackActionAssembler
from integration.government_feedback_reader import (
    GovernmentFeedbackReader, GovernmentFeedbackRecoverySettings, GovernmentFeedbackRecoveryBindings,
    build_assembled_government_feedback_dispatcher,
)
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, canonical, task_digest


class GovernmentFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False


class GovernmentFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: GovernmentSubmissionHostConfiguration | None = None
    feedback: GovernmentFormalFeedbackSettings | None = None
    decision_notifications: GovernmentDecisionNotificationSettings | None = None
    execution_recovery: GovernmentSchedulingRecoverySettings | GovernmentReviewRecoverySettings | GovernmentConsultationRecoverySettings | GovernmentSupplementRecoverySettings | GovernmentDecisionRecoverySettings | GovernmentPermitRecoverySettings | GovernmentTransitionRecoverySettings | GovernmentFeedbackRecoverySettings | GovernmentUseRecoverySettings | GovernmentInspectionRecoverySettings | None = None

    @model_validator(mode='before')
    @classmethod
    def original_task_recovery(cls, value):
        if not isinstance(value, dict) or value.get('execution_recovery') is None:
            return value
        types = {'GOV-A10': GovernmentInspectionRecoverySettings, 'GOV-A11': GovernmentUseRecoverySettings,
            'GOV-A03': GovernmentSchedulingRecoverySettings, 'GOV-A04': GovernmentReviewRecoverySettings,
            'GOV-A05': GovernmentConsultationRecoverySettings, 'GOV-A06': GovernmentSupplementRecoverySettings,
            'GOV-A07': GovernmentDecisionRecoverySettings, 'GOV-A08': GovernmentPermitRecoverySettings,
            'GOV-A09': GovernmentTransitionRecoverySettings, 'GOV-A12': GovernmentFeedbackRecoverySettings}
        action_id, recovery = value.get('action_id'), value['execution_recovery']
        if action_id not in types:
            raise ValueError('Government task recovery requires original A03 scheduling, A04 review, A05 consultation, A06 supplement, A07 signing, A08 permit verification, A09 decision change, A10 inspection, A11 use planning or A12 feedback working')
        settings_type = types[action_id]
        if isinstance(recovery, GovernmentInspectionRecoverySettings) and type(recovery) is not settings_type:
            raise ValueError('Government recovery configuration changes its original action type')
        return {**value, 'execution_recovery': settings_type.model_validate(recovery)}


@dataclass(frozen=True)
class GovernmentFormalApplicationDependencies:
    """Actual application supplies original sources and an existing model host.

    The factory owns partial resources until returning this bundle. Original
    invocation/wait/recovery validators apply to all submission workers; actual
    action-specific transport and business validation are explicitly supplied.
    """
    version: str
    sources: GovernmentRoleContractSources
    submission_callbacks: dict[str, GovernmentSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    execution_recovery: GovernmentUseRecoveryBindings | GovernmentInspectionRecoveryBindings | GovernmentSchedulingRecoveryBindings | GovernmentReviewRecoveryBindings | GovernmentConsultationRecoveryBindings | GovernmentSupplementRecoveryBindings | GovernmentDecisionRecoveryBindings | GovernmentPermitRecoveryBindings | GovernmentTransitionRecoveryBindings | GovernmentFeedbackRecoveryBindings | None = None
    decision_notification_callbacks: GovernmentDecisionNotificationCallbacks | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, GovernmentRoleContractSources)
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or self.execution_recovery is not None and type(self.execution_recovery) not in {
                    GovernmentInspectionRecoveryBindings, GovernmentUseRecoveryBindings,
                    GovernmentSchedulingRecoveryBindings, GovernmentReviewRecoveryBindings, GovernmentConsultationRecoveryBindings,
                    GovernmentSupplementRecoveryBindings, GovernmentDecisionRecoveryBindings, GovernmentPermitRecoveryBindings,
                    GovernmentTransitionRecoveryBindings, GovernmentFeedbackRecoveryBindings}
                or not isinstance(self.submission_callbacks, dict)
                or self.decision_notification_callbacks is not None and not isinstance(
                    self.decision_notification_callbacks, GovernmentDecisionNotificationCallbacks)
                or any(not isinstance(value, GovernmentSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(callback is not None and not callable(callback) for callback in
                    (self.submission_read_guard, self.validate_feedback_relation,
                        self.validate_feedback_read, self.validate_feedback_input))):
            raise ValueError('Formal Government dependencies require original sources and actual callback bindings')


class GovernmentFormalApplication:
    """Assemble original workers and configured routes; business calls stay explicit.

    Source health and native endpoint effects require observed application
    evidence. Construction is configured_unverified and never runs an action,
    sends a submission, constructs a model client or invents a native source.
    Advice, intake, scheduling, review, consultation, supplement, signing,
    conditions, transitions, inspection, use and feedback routes require actual
    application transport. A07 signing and A09 formal decision changes require
    original-command query callbacks. A11 use proposals retain independent A07
    signing and A10 supervision; configuration and receipts never prove permit
    effect, actual delivery, enforcement or discharge of retained obligations.
    """
    VERSION = 'government-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = GovernmentFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, GovernmentFormalApplicationDependencies):
            raise ValueError('Formal Government factory must return GovernmentFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version):
            raise ValueError('Formal Government assembly requires original same-run sources and configured model host')
        registration = base.registry.get(config.action_id)
        if (registration.role != 'Government' or not registration.implemented or registration.skill is None
                or request.execution_path not in {None, registration.strategy}
                or not any(config.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Formal Government application requires its original implemented action and bound strategy')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if (not actions <= set(_ACTIONS) or set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.submission is None and dependencies.submission_read_guard is not None):
            raise ValueError('Configured Government submission must match its explicit callbacks and current read guard')
        if config.submission is not None:
            for route in config.submission.routes:
                if ((route.action_id == 'GOV-A07'
                        or route.action_id == 'GOV-A09' and set(route.supported_choices)
                            & {'renew', 'suspend', 'revoke', 'restore'})
                        and dependencies.submission_callbacks[route.action_id].query is None):
                    raise ValueError('Government signing and formal decision changes require original-command query callbacks')
        if config.feedback is not None:
            if (config.submission is None or not actions
                    or not callable(dependencies.validate_feedback_relation)
                    or not callable(dependencies.validate_feedback_read)):
                raise ValueError('Government feedback requires configured submission routes and actual relation/read validators')
        elif dependencies.validate_feedback_relation is not None or dependencies.validate_feedback_read is not None:
            raise ValueError('Government feedback validators require an explicit feedback configuration')
        input_enabled = config.feedback is not None and config.feedback.input_enabled
        if (input_enabled and not callable(dependencies.validate_feedback_input)
                or not input_enabled and dependencies.validate_feedback_input is not None):
            raise ValueError('Government feedback input validation must match the explicit input-enabled configuration')
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('Government inspection recovery must match its explicit configuration')
        if recovery is not None:
            if config.action_id not in {'GOV-A03', 'GOV-A04', 'GOV-A05', 'GOV-A06', 'GOV-A07', 'GOV-A08', 'GOV-A09', 'GOV-A10', 'GOV-A11', 'GOV-A12'} or config.action_id not in actions or config.feedback is None:
                raise ValueError('Government task recovery requires original A03/A04/A05/A06/A07/A08/A09/A10/A11/A12 submission and persisted feedback routes')
            expected_bindings = {'GOV-A03': GovernmentSchedulingRecoveryBindings,
                'GOV-A04': GovernmentReviewRecoveryBindings, 'GOV-A05': GovernmentConsultationRecoveryBindings, 'GOV-A06': GovernmentSupplementRecoveryBindings, 'GOV-A07': GovernmentDecisionRecoveryBindings, 'GOV-A10': GovernmentInspectionRecoveryBindings,
                'GOV-A08': GovernmentPermitRecoveryBindings, 'GOV-A09': GovernmentTransitionRecoveryBindings,
                'GOV-A11': GovernmentUseRecoveryBindings, 'GOV-A12': GovernmentFeedbackRecoveryBindings}[config.action_id]
            if type(recovery) is not expected_bindings:
                raise ValueError('Government task recovery callbacks change the original action type')
        notification_bindings = {'GOV-A07': GovernmentDecisionRecoveryBindings, 'GOV-A09': GovernmentTransitionRecoveryBindings}
        if ((config.decision_notifications is None) != (dependencies.decision_notification_callbacks is None)
                or config.decision_notifications is not None and (config.action_id not in notification_bindings
                    or type(recovery) is not notification_bindings[config.action_id]
                    or not config.execution_recovery.terminal_notification_enabled
                    or config.decision_notifications.macro_version != config.execution_recovery.macro_version)):
            raise ValueError('Decision notification transport requires matching explicit A07/A09 recovery, terminal and native callback configuration')
        self.dependencies, self.base = dependencies, base
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model)
        self._closed = False
        self.submissions = self.feedback = None
        self.inspection_assembler = self.inspection_reader = self.execution_dispatcher = None
        self._inspection_recovery_components = None
        self.decision_notifications = None
        self._notification_components = None
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.government_' + module + '_results'),
                    'Government' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = GovernmentSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            self.feedback = GovernmentSubmissionFeedback(host=self.submissions, inbox=inbox,
                version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                validate_read=dependencies.validate_feedback_read)
        if recovery is not None:
            assembler_type, reader_type, dispatcher_factory = self._recovery_types()
            self.inspection_assembler = assembler_type(registry=base.registry,
                organizations=base.organizations, provider=base.provider, methods=base.methods,
                macro_version=config.execution_recovery.macro_version, source_mode='formal',
                policy_version=config.execution_recovery.policy_version, model_version=config.model_version,
                model_host=model)
            self.inspection_reader = reader_type(assembler=self.inspection_assembler,
                snapshots=InvocationSnapshotStore(base.store), select_current=recovery.select_current)
            self.execution_dispatcher = dispatcher_factory(
                inbox=self.feedback.inbox, store=base.store, assembler=self.inspection_assembler,
                select_current=recovery.select_current, read_guard=recovery.read_guard,
                validate_relation=recovery.validate_relation, project_signal=recovery.project_signal,
                prepare=recovery.prepare, revalidate=recovery.revalidate)
            self._inspection_recovery_components = (recovery, *recovery.components(), self.inspection_assembler,
                self.inspection_reader, self.execution_dispatcher, self.feedback.inbox, base.provider)
        if config.decision_notifications is not None:
            transport_type = GovernmentDecisionNotificationTransport if config.action_id == 'GOV-A07' else GovernmentTransitionNotificationTransport
            self.decision_notifications = transport_type(store=base.store,
                reader=self.inspection_reader, dispatcher=self.execution_dispatcher.dispatcher,
                settings=config.decision_notifications, callbacks=dependencies.decision_notification_callbacks,
                read_guard=recovery.read_guard, validate_relation=recovery.validate_relation)
            self._notification_components = (self.decision_notifications, dependencies.decision_notification_callbacks)
        self._declared = self._configuration()
        self._key = 'government_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal Government application configuration changed; explicit review required')

    def _recovery_types(self):
        if self.settings.action_id == 'GOV-A03':
            return GovernmentSchedulingActionAssembler, GovernmentSchedulingReader, build_assembled_government_scheduling_dispatcher
        if self.settings.action_id == 'GOV-A04':
            return GovernmentReviewActionAssembler, GovernmentReviewReader, build_assembled_government_review_dispatcher
        if self.settings.action_id == 'GOV-A05':
            return GovernmentConsultationActionAssembler, GovernmentConsultationReader, build_assembled_government_consultation_dispatcher
        if self.settings.action_id == 'GOV-A06':
            return GovernmentSupplementActionAssembler, GovernmentSupplementReader, build_assembled_government_supplement_dispatcher
        if self.settings.action_id == 'GOV-A07':
            return GovernmentDecisionActionAssembler, GovernmentDecisionReader, build_assembled_government_decision_dispatcher
        if self.settings.action_id == 'GOV-A08':
            return GovernmentPermitActionAssembler, GovernmentPermitReader, build_assembled_government_permit_dispatcher
        if self.settings.action_id == 'GOV-A09':
            return GovernmentTransitionActionAssembler, GovernmentTransitionReader, build_assembled_government_transition_dispatcher
        if self.settings.action_id == 'GOV-A10':
            return GovernmentInspectionActionAssembler, GovernmentInspectionReader, build_assembled_government_inspection_dispatcher
        if self.settings.action_id == 'GOV-A11':
            return GovernmentUseActionAssembler, GovernmentUseReader, build_assembled_government_use_dispatcher
        if self.settings.action_id == 'GOV-A12':
            return GovernmentFeedbackActionAssembler, GovernmentFeedbackReader, build_assembled_government_feedback_dispatcher
        raise ValueError('Government task recovery requires original A03 scheduling, A04 review, A05 consultation, A06 supplement, A07 signing, A08 permit verification, A09 decision change, A10 inspection, A11 use planning or A12 feedback working')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.base.store.run_id,
            'settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'dependency_version': self.dependencies.version, 'source_version': self.base.version,
            'dependency_factory': self.factory_descriptor, 'sources': _descriptors(self.base),
            'code': module_factory_descriptor(type(self).sources, self.VERSION),
            'model_configuration_sha256': self.base.model_host.configuration_sha256,
            'execution_recovery': None if self.inspection_reader is None else {
                'reader': self.inspection_reader.configuration_evidence(),
                'callbacks': self.dependencies.execution_recovery.configuration_evidence()},
            'submission_sha256': task_digest(self.submissions._declared) if self.submissions is not None else None,
            'decision_notification_sha256': task_digest(self.decision_notifications._declared)
                if self.decision_notifications is not None else None,
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
            self.base.organizations, self.base.provider, self.base.model_host)
        if (self._closed or any(actual is not original for actual, original in zip(components, self._components))
                or self.dependencies.sources is not self.base
                or self.base.model_host.store is not self.base.store or self.base.model_host.registry is not self.base.registry
                or self.base.model_host.model_version != self.settings.model_version
                or module_factory_descriptor(_load_factory(self.settings.dependency_factory),
                    self.settings.dependency_factory) != self.factory_descriptor
                or self._configuration() != self._declared):
            raise TaskConflict('Original formal Government components or configuration changed, or application closed')
        recovery = self.dependencies.execution_recovery
        if self._notification_components is None:
            if self.decision_notifications is not None or self.dependencies.decision_notification_callbacks is not None:
                raise TaskConflict('Undeclared decision notification transport was added')
        else:
            if (self.decision_notifications is not self._notification_components[0]
                    or self.dependencies.decision_notification_callbacks is not self._notification_components[1]
                    or self.decision_notifications.reader is not self.inspection_reader
                    or self.decision_notifications.dispatcher is not self.execution_dispatcher.dispatcher
                    or self.decision_notifications.callbacks is not self.dependencies.decision_notification_callbacks
                    or self.decision_notifications.read_guard is not recovery.read_guard
                    or self.decision_notifications.validate_relation is not recovery.validate_relation):
                raise TaskConflict('Original decision notification endpoint/source bindings changed')
            self.decision_notifications._check()
        if self._inspection_recovery_components is None:
            if any(value is not None for value in (recovery, self.inspection_assembler,
                    self.inspection_reader, self.execution_dispatcher)):
                raise TaskConflict('Undeclared Government inspection recovery components were added')
        else:
            current = (recovery, *recovery.components(), self.inspection_assembler, self.inspection_reader,
                self.execution_dispatcher, self.feedback.inbox, self.base.provider)
            assembler = self.inspection_assembler
            if (len(current) != len(self._inspection_recovery_components)
                    or any(actual is not original for actual, original in zip(current, self._inspection_recovery_components))
                    or assembler.registry is not self.base.registry or assembler.organizations is not self.base.organizations
                    or assembler.provider is not self.base.provider or assembler.methods is not self.base.methods
                    or self.inspection_reader.snapshots.store is not self.base.store
                    or self.inspection_reader.ACTION_ID != self.settings.action_id
                    or self.execution_dispatcher.action_id != self.settings.action_id
                    or len(assembler.decision_strategies) != len(self.base.model_host.bindings)
                    or any(actual is not original for actual, original in zip(
                        assembler.decision_strategies, self.base.model_host.bindings))):
                raise TaskConflict('Government inspection recovery changed original source/model/journal/recipient/callback bindings')
            self.inspection_reader._check()
            self.execution_dispatcher._check()
        if self.submissions is not None:
            self.submissions._check()
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal Government submission components changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_relation is not self.dependencies.validate_feedback_relation
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal Government feedback components or validators changed')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal Government application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal Government source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'feedback_configured': self.feedback is not None,
            'execution_recovery_configured': self.execution_dispatcher is not None,
            'decision_notifications_configured': self.decision_notifications is not None,
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
            raise ValueError('No actual Government submission routes are configured')
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
        """Explicitly resume the original inspection/use task for a fresh judgment."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Government original inspection/use task recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def reconcile_scheduling_handoff(self, identity, *, signal):
        """Explicit native all-task reconciliation, with no fresh A03 invocation."""
        from integration.government_scheduling_terminal import reconcile_government_scheduling_handoff
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'GOV-A03' or not isinstance(settings, GovernmentSchedulingRecoverySettings)
                or not settings.terminal_handoff_enabled or self.execution_dispatcher is None):
            raise ValueError('Government all-task handoff reconciliation requires explicit A03 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_government_scheduling_handoff(identity=identity, signal=signal,
                reader=self.inspection_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_supplement_transfer(self, identity, *, signal):
        """Archive an original A06 wait after actual independently lawful new-case intake."""
        from integration.government_supplement_terminal import reconcile_government_supplement_transfer
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'GOV-A06' or not isinstance(settings, GovernmentSupplementRecoverySettings)
                or not settings.terminal_transfer_enabled or self.execution_dispatcher is None):
            raise ValueError('Government supplement transfer requires explicit A06 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_government_supplement_transfer(identity=identity, signal=signal,
                reader=self.inspection_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def send_decision_notification(self, identity, *, signal, recipient_id):
        """Explicit A07/A09 native notification call, independent of original signing."""
        self._check()
        if self.decision_notifications is None:
            raise ValueError('No independent Government decision notification transport is configured')
        result = self.decision_notifications.execute(identity, signal=signal, recipient_id=recipient_id)
        self._check()
        return result

    def query_decision_notification(self, identity, *, signal, recipient_id):
        """Read the original native notification identity without sending again."""
        self._check()
        if self.decision_notifications is None:
            raise ValueError('No independent Government decision notification transport is configured')
        result = self.decision_notifications.recover(identity, signal=signal, recipient_id=recipient_id)
        self._check()
        return result

    def reconcile_decision_notification(self, identity, *, signal):
        """Archive actual original-decision delivery without a fresh signing/submission."""
        from integration.government_decision_terminal import reconcile_government_decision_notification
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'GOV-A07' or not isinstance(settings, GovernmentDecisionRecoverySettings)
                or not settings.terminal_notification_enabled or self.execution_dispatcher is None):
            raise ValueError('Decision delivery requires explicit A07 terminal notification configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_government_decision_notification(identity=identity, signal=signal,
                reader=self.inspection_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_transition_notification(self, identity, *, signal):
        """Archive actual delivery of an original A09 change without replaying its command."""
        from integration.government_transition_terminal import reconcile_government_transition_notification
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'GOV-A09' or not isinstance(settings, GovernmentTransitionRecoverySettings)
                or not settings.terminal_notification_enabled or self.execution_dispatcher is None):
            raise ValueError('Change delivery requires explicit A09 terminal notification configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_government_transition_notification(identity=identity, signal=signal,
                reader=self.inspection_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_feedback_execution(self, identity, *, signal):
        """Read and archive actual disposition of the same original A12 business execution."""
        from integration.government_feedback_terminal import reconcile_government_feedback_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'GOV-A12' or not isinstance(settings, GovernmentFeedbackRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Feedback execution reconciliation requires explicit A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_government_feedback_execution(identity=identity, signal=signal,
                reader=self.inspection_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the original A10/A11 journal and protected callbacks to selected V7 waits."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Government original inspection/use task recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def record_feedback(self, identity, *, context, reading, observation):
        """Explicitly correlate actual feedback under current source/authorization guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Government actual feedback inbox is configured')
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
            raise ValueError('No Government actual feedback inbox is configured')
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
    config = GovernmentFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != config.action_id or config.action_id not in _ACTIONS):
        raise ValueError('Formal Government source factory requires its explicit non-offline original invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, GovernmentFormalApplicationDependencies):
        raise ValueError('Actual Government dependency factory must return GovernmentFormalApplicationDependencies')
    application = None
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual Government dependency factory changed during assembly')
        application = GovernmentFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
