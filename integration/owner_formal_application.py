"""Configured formal Owner application assembly over original actual dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field, replace
import importlib
import json
from pathlib import Path
from typing import Callable

from pydantic import Field, field_validator, model_validator

from integration.contractor_handover_reader import (
    ContractorHandoverReader, ContractorHandoverReaderSettings, bind_contractor_handover_reader_sources,
)
from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from integration.owner_closeout_feedback import OwnerCloseoutSubmissionFeedback
from integration.owner_closeout_recovery_reader import (
    OwnerCloseoutRecoveryBindings, OwnerCloseoutRecoverySettings, build_assembled_owner_closeout_dispatcher,
)
from integration.owner_observation_recovery_reader import (
    OwnerObservationRecoveryBindings, OwnerObservationRecoverySettings,
    build_assembled_owner_observation_dispatcher,
)
from integration.owner_study_recovery_reader import (
    OwnerStudyRecoveryBindings, OwnerStudyRecoverySettings, build_assembled_owner_study_dispatcher,
)
from integration.owner_investment_recovery_reader import (
    OwnerInvestmentRecoveryBindings, OwnerInvestmentRecoverySettings, build_assembled_owner_investment_dispatcher,
)
from integration.owner_commission_recovery_reader import (
    OwnerCommissionRecoveryBindings, OwnerCommissionRecoverySettings, build_assembled_owner_commission_dispatcher,
)
from integration.owner_financing_recovery_reader import (
    OwnerFinancingRecoveryBindings, OwnerFinancingRecoverySettings, build_assembled_owner_financing_dispatcher,
)
from integration.owner_regulatory_recovery_reader import (
    OwnerRegulatoryRecoveryBindings, OwnerRegulatoryRecoverySettings, build_assembled_owner_regulatory_dispatcher,
)
from integration.owner_asset_execution_reader import (
    OwnerAssetRecoveryBindings, build_assembled_owner_asset_execution_dispatcher,
)
from integration.owner_closeout_feedback_reader import (
    OwnerCloseoutFeedbackReader, OwnerCloseoutFeedbackReaderSettings, bind_closeout_feedback_reader_sources,
)
from integration.owner_continuation_execution_reader import (
    OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings,
    build_assembled_owner_continuation_execution_dispatcher,
)
from integration.owner_operating_execution_reader import (
    OwnerOperatingRecoveryBindings, build_assembled_owner_operating_execution_dispatcher,
)
from integration.owner_role_contract_host import OwnerRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.owner_submission import OwnerSubmissionCallbacks
from integration.owner_submission_feedback import OwnerSubmissionFeedback
from integration.owner_submission_host import OwnerSubmissionHost, OwnerSubmissionHostConfiguration
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


class OwnerFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False
    native_closeout: bool = False


class OwnerFormalPaymentReceptionSettings(StrictRecord):
    histories: dict[TextId, TaskIdentity] = Field(min_length=1)

    @field_validator('histories', mode='before')
    @classmethod
    def original_identities(cls, value):
        if isinstance(value, dict):
            return {key: TaskIdentity(**identity) if isinstance(identity, dict) else identity
                for key, identity in value.items()}
        return value


class OwnerFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: OwnerSubmissionHostConfiguration | None = None
    feedback: OwnerFormalFeedbackSettings | None = None
    payment_reception: OwnerFormalPaymentReceptionSettings | None = None
    handover_reception: ContractorHandoverReaderSettings | None = None
    closeout_history: OwnerCloseoutFeedbackReaderSettings | None = None
    execution_recovery: OwnerObservationRecoverySettings | OwnerStudyRecoverySettings | OwnerInvestmentRecoverySettings | OwnerCommissionRecoverySettings | OwnerFinancingRecoverySettings | OwnerRegulatoryRecoverySettings | OwnerCloseoutRecoverySettings | OwnerContinuationRecoverySettings | None = None

    @model_validator(mode='before')
    @classmethod
    def select_original_recovery_settings(cls, value):
        if not isinstance(value, dict) or value.get('execution_recovery') is None:
            return value
        result = dict(value)
        types = {'OWN-A01': OwnerObservationRecoverySettings, 'OWN-A02': OwnerStudyRecoverySettings,
            'OWN-A03': OwnerInvestmentRecoverySettings,
            'OWN-A04': OwnerCommissionRecoverySettings,
            'OWN-A05': OwnerFinancingRecoverySettings,
            'OWN-A08': OwnerRegulatoryRecoverySettings,
            'OWN-A12': OwnerCloseoutRecoverySettings,
            'OWN-A13': OwnerContinuationRecoverySettings, 'OWN-A14': OwnerContinuationRecoverySettings,
            'OWN-A15': OwnerContinuationRecoverySettings}
        settings_type = types.get(value.get('action_id'))
        if settings_type is None:
            raise ValueError('Owner recovery requires original OWN-A01/A02/A03/A04/A05/A08/A12/A13/A14/A15')
        recovery = value['execution_recovery']
        if isinstance(recovery, dict):
            result['execution_recovery'] = settings_type.model_validate(recovery)
        elif type(recovery) is not settings_type:
            raise ValueError('Owner recovery configuration belongs to another original action route')
        return result

    @model_validator(mode='after')
    def terminal_continuation_route(self):
        settings_types = {'OWN-A01': OwnerObservationRecoverySettings, 'OWN-A02': OwnerStudyRecoverySettings,
            'OWN-A03': OwnerInvestmentRecoverySettings, 'OWN-A04': OwnerCommissionRecoverySettings,
            'OWN-A05': OwnerFinancingRecoverySettings, 'OWN-A08': OwnerRegulatoryRecoverySettings,
            'OWN-A12': OwnerCloseoutRecoverySettings,
            'OWN-A13': OwnerContinuationRecoverySettings, 'OWN-A14': OwnerContinuationRecoverySettings,
            'OWN-A15': OwnerContinuationRecoverySettings}
        if (self.execution_recovery is not None
                and type(self.execution_recovery) is not settings_types.get(self.action_id)):
            raise ValueError('Owner recovery settings belong only to their original action route')
        if (self.execution_recovery is not None and self.execution_recovery.terminal_execution_enabled
                and self.action_id != 'OWN-A13'):
            raise ValueError('Owner continuation terminal archive belongs only to original OWN-A13')
        if (self.execution_recovery is not None and self.execution_recovery.terminal_asset_execution_enabled
                and self.action_id != 'OWN-A14'):
            raise ValueError('Owner asset terminal archive belongs only to original OWN-A14')
        if (self.execution_recovery is not None and self.execution_recovery.terminal_operating_execution_enabled
                and self.action_id != 'OWN-A15'):
            raise ValueError('Owner operating terminal archive belongs only to original OWN-A15')
        return self

    @property
    def declared_source_version(self):
        if self.handover_reception is not None:
            return OwnerFormalApplication.VERSION + '+contractor-handover-reception-sources.v1'
        if self.closeout_history is not None:
            return OwnerFormalApplication.VERSION + '+owner-closeout-continuation-sources.v1'
        if self.payment_reception is None:
            return OwnerFormalApplication.VERSION
        from integration.owner_native_payment_reception import native_payment_reception_source_version

        return native_payment_reception_source_version(OwnerFormalApplication.VERSION)


@dataclass(frozen=True)
class OwnerFormalApplicationDependencies:
    """Actual application supplies original sources and an existing model host.

    The factory owns partial resources until returning this bundle. Original
    invocation/wait/recovery validators apply to all submission workers; actual
    action-specific transport and business validation are explicitly supplied.
    """
    version: str
    sources: OwnerRoleContractSources
    submission_callbacks: dict[str, OwnerSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    read_native_payment_execution: Callable | None = None
    read_native_payment_settlement: Callable | None = None
    validate_native_payment_settlement: Callable | None = None
    prepare_payment_reception: Callable | None = None
    validate_payment_history: Callable | None = None
    validate_payment_reception: Callable | None = None
    validate_closeout_native_relation: Callable | None = None
    closeout_history_reader: OwnerCloseoutFeedbackReader | None = None
    validate_closeout_continuation: Callable | None = None
    contractor_handover_reader: ContractorHandoverReader | None = None
    validate_handover_reception: Callable | None = None
    execution_recovery: OwnerContinuationRecoveryBindings | OwnerAssetRecoveryBindings | OwnerOperatingRecoveryBindings | OwnerCloseoutRecoveryBindings | OwnerObservationRecoveryBindings | OwnerStudyRecoveryBindings | OwnerInvestmentRecoveryBindings | OwnerCommissionRecoveryBindings | OwnerFinancingRecoveryBindings | OwnerRegulatoryRecoveryBindings | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, OwnerRoleContractSources)
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or not isinstance(self.submission_callbacks, dict)
                or self.execution_recovery is not None and not isinstance(
                    self.execution_recovery, (OwnerContinuationRecoveryBindings, OwnerAssetRecoveryBindings,
                        OwnerOperatingRecoveryBindings))
                or any(not isinstance(value, OwnerSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(callback is not None and not callable(callback) for callback in
                    (self.submission_read_guard, self.validate_feedback_relation,
                        self.validate_feedback_read, self.validate_feedback_input,
                        self.read_native_payment_execution, self.read_native_payment_settlement,
                        self.validate_native_payment_settlement, self.prepare_payment_reception,
                        self.validate_payment_history, self.validate_payment_reception,
                        self.validate_closeout_native_relation, self.validate_closeout_continuation,
                        self.validate_handover_reception))
                or self.contractor_handover_reader is not None and not isinstance(self.contractor_handover_reader, ContractorHandoverReader)
                or self.closeout_history_reader is not None and not isinstance(self.closeout_history_reader, OwnerCloseoutFeedbackReader)):
            raise ValueError('Formal Owner dependencies require original sources and actual callback bindings')


class OwnerFormalApplication:
    """Assemble original workers and configured routes; business calls stay explicit.

    Source health and native endpoint effects require observed application
    evidence. Construction is configured_unverified and never runs an action,
    sends a submission, constructs a model client or invents a native source.
    """
    VERSION = 'owner-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = OwnerFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, OwnerFormalApplicationDependencies):
            raise ValueError('Formal Owner factory must return OwnerFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version):
            raise ValueError('Formal Owner assembly requires original same-run sources and configured model host')
        registration = base.registry.get(config.action_id)
        if (registration.role != 'Owner' or not registration.implemented or registration.skill is None
                or request.execution_path not in {None, registration.strategy}
                or not any(config.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Formal Owner application requires its original implemented action and bound strategy')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if config.handover_reception is not None:
            reader = dependencies.contractor_handover_reader
            if (config.action_id != 'OWN-A12' or config.payment_reception is not None or config.closeout_history is not None
                    or not isinstance(reader, ContractorHandoverReader)
                    or not callable(dependencies.validate_handover_reception)
                    or reader.settings != config.handover_reception or reader.settings.recipient_context != request.context
                    or reader.worker.store is not base.store or reader.worker.registry is not base.registry
                    or reader.assembler.organizations is not base.organizations
                    or base.read_contractor_closeout is not None or base.validate_handover_reception is not None):
                raise ValueError('Formal Owner handover requires its original same-journal Contractor reader and actual reception validator')
            reader._check()
        elif dependencies.contractor_handover_reader is not None or dependencies.validate_handover_reception is not None:
            raise ValueError('Owner handover components require an explicit reception declaration')
        if config.closeout_history is not None:
            reader = dependencies.closeout_history_reader
            if (config.action_id != 'OWN-A13' or config.payment_reception is not None
                    or not isinstance(reader, OwnerCloseoutFeedbackReader)
                    or not callable(dependencies.validate_closeout_continuation)
                    or reader.settings != config.closeout_history or reader.settings.recipient_context != request.context
                    or reader.feedback.host.store is not base.store or reader.feedback.host.registry is not base.registry
                    or reader.assembler.organizations is not base.organizations
                    or base.read_closeout_feedback is not None or base.validate_closeout_continuation is not None):
                raise ValueError('Formal Owner continuation requires its original same-journal closeout reader and current mapping validator')
            reader._check()
        elif dependencies.closeout_history_reader is not None or dependencies.validate_closeout_continuation is not None:
            raise ValueError('Owner closeout history components require an explicit declaration')
        if (not actions <= set(_ACTIONS) or set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.submission is None and dependencies.submission_read_guard is not None):
            raise ValueError('Configured Owner submission must match its explicit callbacks and current read guard')
        native_payment = (config.submission is not None
            and any(route.native_payment_execution for route in config.submission.routes))
        if (native_payment and not callable(dependencies.read_native_payment_execution)
                or not native_payment and dependencies.read_native_payment_execution is not None):
            raise ValueError('Owner native payment reader must match an explicitly enabled payment route')
        native_settlement = (config.submission is not None
            and any(route.native_payment_settlement for route in config.submission.routes))
        settlement_callbacks = (dependencies.read_native_payment_settlement,
            dependencies.validate_native_payment_settlement)
        if (native_settlement and (not native_payment
                    or not all(callable(callback) for callback in settlement_callbacks))
                or not native_settlement and any(callback is not None for callback in settlement_callbacks)):
            raise ValueError('Owner native settlement must match enabled execution and actual reader/validator')
        reception_callbacks = (dependencies.prepare_payment_reception,
            dependencies.validate_payment_history, dependencies.validate_payment_reception)
        if (config.payment_reception is not None and (config.action_id != 'OWN-A06' or not native_settlement
                    or base.read_owner_payment_execution is not None
                    or not all(callable(callback) for callback in reception_callbacks)
                    or not all(key == identity.key and identity.role == 'Owner' and identity.action_id == 'OWN-A06'
                        and identity.purpose == 'action' and identity.run_id == base.store.run_id
                        and identity.organization_id in base.store.organization_ids
                        for key, identity in config.payment_reception.histories.items()))
                or config.payment_reception is None and any(callback is not None for callback in reception_callbacks)):
            raise ValueError('Owner payment reception requires explicit original histories, native settlement and current validators')
        if config.feedback is not None:
            if (config.submission is None or not actions or not callable(dependencies.validate_feedback_read)):
                raise ValueError('Owner feedback requires configured submission routes and actual relation/read validators')
            if config.feedback.native_closeout:
                if (config.action_id != 'OWN-A12' or actions != {'OWN-A12'}
                        or not callable(dependencies.validate_closeout_native_relation)
                        or dependencies.validate_feedback_relation is not None):
                    raise ValueError('Native closeout feedback requires a dedicated original A12 route and actual native relation validator')
            elif not callable(dependencies.validate_feedback_relation) or dependencies.validate_closeout_native_relation is not None:
                raise ValueError('Generic Owner feedback requires its original relation validator without closeout callbacks')
        elif dependencies.validate_feedback_relation is not None or dependencies.validate_feedback_read is not None:
            raise ValueError('Owner feedback validators require an explicit feedback configuration')
        if config.feedback is None and dependencies.validate_closeout_native_relation is not None:
            raise ValueError('Native closeout relation validator requires explicit closeout feedback configuration')
        input_enabled = config.feedback is not None and config.feedback.input_enabled
        if (input_enabled and not callable(dependencies.validate_feedback_input)
                or not input_enabled and dependencies.validate_feedback_input is not None):
            raise ValueError('Owner feedback input validation must match the explicit input-enabled configuration')
        self.dependencies, self.base = dependencies, base
        self._original_handover_components = (dependencies.contractor_handover_reader,
            dependencies.validate_handover_reception)
        self._original_closeout_history_components = (dependencies.closeout_history_reader,
            dependencies.validate_closeout_continuation)
        self._original_payment_reception_callbacks = reception_callbacks
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model)
        self._closed = False
        self.submissions = self.feedback = self.execution_dispatcher = None
        self._recovery_components = None
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.owner_' + module + '_results'),
                    'Owner' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = OwnerSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission,
                read_native_payment_execution=dependencies.read_native_payment_execution,
                read_native_payment_settlement=dependencies.read_native_payment_settlement,
                validate_native_payment_settlement=dependencies.validate_native_payment_settlement)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            if config.feedback.native_closeout:
                self.feedback = OwnerCloseoutSubmissionFeedback(host=self.submissions, inbox=inbox,
                    version=config.feedback.version, validate_native_relation=dependencies.validate_closeout_native_relation,
                    validate_read=dependencies.validate_feedback_read)
            else:
                self.feedback = OwnerSubmissionFeedback(host=self.submissions, inbox=inbox,
                    version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                    validate_read=dependencies.validate_feedback_read)
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('Owner execution recovery bindings must match explicit configuration')
        if recovery is not None:
            assembler = recovery.assembler
            if config.action_id == 'OWN-A01':
                if (type(recovery) is not OwnerObservationRecoveryBindings or recovery.snapshots.store is not base.store):
                    raise ValueError('Owner screening recovery requires its original same-store snapshot reader')
                expected_reader_action = 'OWN-A01'
                dispatcher_factory = build_assembled_owner_observation_dispatcher
            elif config.action_id == 'OWN-A02':
                if (type(recovery) is not OwnerStudyRecoveryBindings or recovery.snapshots.store is not base.store):
                    raise ValueError('Owner study recovery requires its original same-store saved-result reader')
                expected_reader_action = 'OWN-A02'
                dispatcher_factory = build_assembled_owner_study_dispatcher
            elif config.action_id == 'OWN-A03':
                if (type(recovery) is not OwnerInvestmentRecoveryBindings or recovery.snapshots.store is not base.store):
                    raise ValueError('Owner investment recovery requires its original same-store saved-result reader')
                expected_reader_action = 'OWN-A03'
                dispatcher_factory = build_assembled_owner_investment_dispatcher
            elif config.action_id == 'OWN-A04':
                if (type(recovery) is not OwnerCommissionRecoveryBindings or recovery.snapshots.store is not base.store):
                    raise ValueError('Owner commission recovery requires its original same-store saved-result reader')
                expected_reader_action = 'OWN-A04'
                dispatcher_factory = build_assembled_owner_commission_dispatcher
            elif config.action_id == 'OWN-A05':
                if (type(recovery) is not OwnerFinancingRecoveryBindings or recovery.snapshots.store is not base.store):
                    raise ValueError('Owner financing recovery requires its original same-store saved-result reader')
                expected_reader_action = 'OWN-A05'
                dispatcher_factory = build_assembled_owner_financing_dispatcher
            elif config.action_id == 'OWN-A08':
                if (type(recovery) is not OwnerRegulatoryRecoveryBindings or recovery.snapshots.store is not base.store
                        or recovery.command_ids != tuple(config.execution_recovery.command_ids)
                        or recovery._reader.command_ids != recovery.command_ids):
                    raise ValueError('Owner regulatory recovery requires its original same-store reader and explicit command IDs')
                expected_reader_action = 'OWN-A08'
                dispatcher_factory = build_assembled_owner_regulatory_dispatcher
            elif config.action_id == 'OWN-A12':
                if (type(recovery) is not OwnerCloseoutRecoveryBindings or recovery.snapshots.store is not base.store):
                    raise ValueError('Owner closeout recovery requires its original same-store snapshot reader')
                expected_reader_action = 'OWN-A12'
                dispatcher_factory = build_assembled_owner_closeout_dispatcher
            elif config.action_id == 'OWN-A13':
                expected_reader_action = 'OWN-A13'
                dispatcher_factory = build_assembled_owner_continuation_execution_dispatcher
            elif config.action_id == 'OWN-A14':
                expected_reader_action = 'OWN-A14'
                dispatcher_factory = build_assembled_owner_asset_execution_dispatcher
            elif config.action_id == 'OWN-A15':
                expected_reader_action = 'OWN-A15'
                dispatcher_factory = build_assembled_owner_operating_execution_dispatcher
            else:
                raise ValueError('Owner recovery supports only original A01/A02/A03/A04/A05/A08/A12/A13/A14/A15 waits')
            if config.action_id != 'OWN-A12' and isinstance(recovery, OwnerCloseoutRecoveryBindings):
                raise ValueError('Owner closeout recovery callbacks belong only to original OWN-A12')
            if (config.action_id not in actions or self.feedback is None
                    or recovery._reader.assembler is not assembler
                    or assembler.ACTION_ID != expected_reader_action or assembler.source_mode != 'formal'
                    or assembler.registry is not base.registry or assembler.organizations is not base.organizations
                    or assembler.provider is not base.provider or assembler.methods is not base.methods
                    or assembler.macro_version != config.execution_recovery.macro_version
                    or assembler.policy_version != config.execution_recovery.policy_version
                    or assembler.model_version != config.model_version
                    or len(assembler.decision_strategies) != len(model.bindings)
                    or any(actual is not original for actual, original in zip(assembler.decision_strategies, model.bindings))):
                raise ValueError('Owner recovery requires original action formal sources, model bindings and feedback route')
            self.execution_dispatcher = dispatcher_factory(
                inbox=self.feedback.inbox, store=base.store, assembler=assembler,
                select_current=recovery.select_current, read_guard=recovery.read_guard,
                validate_relation=recovery.validate_relation, project_signal=recovery.project_signal,
                prepare=recovery.prepare, revalidate=recovery.revalidate,
                **({'reader': recovery._reader} if config.action_id in {'OWN-A01', 'OWN-A02', 'OWN-A03', 'OWN-A04', 'OWN-A05', 'OWN-A08', 'OWN-A12'} else {}))
            self._recovery_components = (recovery, *recovery.components(), recovery._reader,
                self.execution_dispatcher, self.feedback.inbox)
        self._declared = self._configuration()
        self._key = 'owner_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal Owner application configuration changed; explicit review required')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.base.store.run_id,
            'settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'dependency_version': self.dependencies.version, 'source_version': self.base.version,
            'dependency_factory': self.factory_descriptor, 'sources': _descriptors(self.base),
            'code': module_factory_descriptor(type(self).sources, self.VERSION),
            'model_configuration_sha256': self.base.model_host.configuration_sha256,
            'handover_reception': {
                'reader': self.dependencies.contractor_handover_reader.configuration_evidence()
                    if self.dependencies.contractor_handover_reader is not None else None,
                'reception_validator': module_factory_descriptor(self.dependencies.validate_handover_reception,
                    'validate_handover_reception') if self.dependencies.validate_handover_reception is not None else None},
            'closeout_history': {
                'reader': self.dependencies.closeout_history_reader.configuration_evidence()
                    if self.dependencies.closeout_history_reader is not None else None,
                'mapping_validator': module_factory_descriptor(self.dependencies.validate_closeout_continuation,
                    'validate_closeout_continuation') if self.dependencies.validate_closeout_continuation is not None else None},
            'submission_sha256': task_digest(self.submissions._declared) if self.submissions is not None else None,
            'feedback_sha256': task_digest(self.feedback._declared) if self.feedback is not None else None,
            'execution_recovery': self.dependencies.execution_recovery.configuration_evidence()
                if self.dependencies.execution_recovery is not None else None,
            'feedback_validators': {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in (('validate_feedback_relation', self.dependencies.validate_feedback_relation),
                    ('validate_feedback_read', self.dependencies.validate_feedback_read),
                    ('validate_feedback_input', self.dependencies.validate_feedback_input),
                    ('validate_closeout_native_relation', self.dependencies.validate_closeout_native_relation))},
            'submission_read_guard': module_factory_descriptor(self.dependencies.submission_read_guard, 'submission_read_guard')
                if self.dependencies.submission_read_guard is not None else None,
            'native_payment_execution_reader': module_factory_descriptor(
                self.dependencies.read_native_payment_execution, 'read_native_payment_execution')
                if self.dependencies.read_native_payment_execution is not None else None,
            'native_payment_settlement_callbacks': {name: module_factory_descriptor(callback, name)
                if callback is not None else None for name, callback in (
                    ('reader', self.dependencies.read_native_payment_settlement),
                    ('validator', self.dependencies.validate_native_payment_settlement))},
            'payment_reception_callbacks': {name: module_factory_descriptor(callback, name)
                if callback is not None else None for name, callback in (
                    ('prepare', self.dependencies.prepare_payment_reception),
                    ('history', self.dependencies.validate_payment_history),
                    ('reception', self.dependencies.validate_payment_reception))},
            'submission_callbacks': {action: {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in vars(callbacks).items()}
                for action, callbacks in sorted(self.dependencies.submission_callbacks.items())}}

    def _check(self):
        components = (self.base, self.base.store, self.base.registry,
            self.base.organizations, self.base.provider, self.base.model_host)
        if (self._closed or any(actual is not original for actual, original in zip(components, self._components))
                or self.dependencies.sources is not self.base
                or any(actual is not original for actual, original in zip((self.dependencies.contractor_handover_reader,
                    self.dependencies.validate_handover_reception), self._original_handover_components))
                or any(actual is not original for actual, original in zip((self.dependencies.closeout_history_reader,
                    self.dependencies.validate_closeout_continuation), self._original_closeout_history_components))
                or any(actual is not original for actual, original in zip((
                    self.dependencies.prepare_payment_reception, self.dependencies.validate_payment_history,
                    self.dependencies.validate_payment_reception), self._original_payment_reception_callbacks))
                or self.base.model_host.store is not self.base.store or self.base.model_host.registry is not self.base.registry
                or self.base.model_host.model_version != self.settings.model_version
                or module_factory_descriptor(_load_factory(self.settings.dependency_factory),
                    self.settings.dependency_factory) != self.factory_descriptor
                or self._configuration() != self._declared):
            raise TaskConflict('Original formal Owner components or configuration changed, or application closed')
        recovery = self.dependencies.execution_recovery
        if self._recovery_components is None and (recovery is not None or self.execution_dispatcher is not None):
            raise TaskConflict('Undeclared Owner execution recovery components were added')
        if self._recovery_components is not None:
            current = (recovery, *recovery.components(), recovery._reader,
                self.execution_dispatcher, self.feedback.inbox)
            assembler = recovery.assembler
            if (len(current) != len(self._recovery_components)
                    or any(actual is not original for actual, original in zip(current, self._recovery_components))
                    or assembler.registry is not self.base.registry or assembler.organizations is not self.base.organizations
                    or assembler.provider is not self.base.provider or assembler.methods is not self.base.methods
                    or len(assembler.decision_strategies) != len(self.base.model_host.bindings)
                    or any(actual is not original for actual, original in zip(
                        assembler.decision_strategies, self.base.model_host.bindings))):
                raise TaskConflict('Formal Owner execution recovery source or callback bindings changed')
        if self.settings.handover_reception is not None:
            self.dependencies.contractor_handover_reader._check()
            if self.dependencies.contractor_handover_reader.settings != self.settings.handover_reception:
                raise TaskConflict('Formal Owner original handover reception declaration changed')
        if self.settings.closeout_history is not None:
            self.dependencies.closeout_history_reader._check()
            if self.dependencies.closeout_history_reader.settings != self.settings.closeout_history:
                raise TaskConflict('Formal Owner original closeout history declaration changed')
        if self.submissions is not None:
            self.submissions._check()
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or self.dependencies.read_native_payment_execution is not None
                        and self.submissions.routes['OWN-A06'].read_native_execution
                            is not self.dependencies.read_native_payment_execution
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal Owner submission components changed')
            for reconciler in self.submissions.payment_settlements.values():
                if (reconciler.read_native_settlement is not self.dependencies.read_native_payment_settlement
                        or reconciler.validate_native_settlement is not self.dependencies.validate_native_payment_settlement):
                    raise TaskConflict('Formal Owner native settlement callbacks changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal Owner feedback components or validators changed')
            if self.settings.feedback.native_closeout:
                if (not isinstance(self.feedback, OwnerCloseoutSubmissionFeedback)
                        or self.feedback.validate_native_relation is not self.dependencies.validate_closeout_native_relation):
                    raise TaskConflict('Formal Owner original native closeout feedback changed')
            elif self.feedback.validate_relation is not self.dependencies.validate_feedback_relation:
                raise TaskConflict('Formal Owner original feedback relation validator changed')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal Owner application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal Owner source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'payment_reception_configured': self.settings.payment_reception is not None,
            'handover_reception_configured': self.settings.handover_reception is not None,
            'closeout_history_configured': self.settings.closeout_history is not None,
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
            from integration.owner_native_payment_reception import bind_owner_native_payment_reception

            sources = bind_owner_native_payment_reception(sources, submission_host=self.submissions,
                histories=self.settings.payment_reception.histories,
                prepare_current=self.dependencies.prepare_payment_reception,
                validate_history=self.dependencies.validate_payment_history,
                validate_reception=self.dependencies.validate_payment_reception)
        if self.settings.handover_reception is not None:
            sources = bind_contractor_handover_reader_sources(sources=sources,
                reader=self.dependencies.contractor_handover_reader,
                validate_reception=self.dependencies.validate_handover_reception,
                version=self.settings.declared_source_version)
        if self.settings.closeout_history is not None:
            sources = bind_closeout_feedback_reader_sources(sources=sources,
                reader=self.dependencies.closeout_history_reader,
                validate_relation=self.dependencies.validate_closeout_continuation,
                version=self.settings.declared_source_version)
        return sources

    def _dispatch_submission(self, identity, operation):
        self._check()
        if self.submissions is None:
            raise ValueError('No actual Owner submission routes are configured')
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
        """Explicitly evaluate saved feedback and queue a fresh checked judgment."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Owner original execution recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def reconcile_continuation_execution(self, identity, *, signal):
        """Archive actual original transition without replaying or releasing resources."""
        from integration.owner_continuation_terminal import reconcile_owner_continuation_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'OWN-A13' or settings is None or not settings.terminal_execution_enabled
                or self.execution_dispatcher is None):
            raise ValueError('Owner continuation archive requires explicit OWN-A13 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_owner_continuation_execution(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_closeout_history(self, identity, *, signal):
        """Archive original decision disposition while retaining payment and residual duties."""
        from integration.owner_closeout_terminal import reconcile_owner_closeout_history
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'OWN-A12' or not isinstance(settings, OwnerCloseoutRecoverySettings)
                or not settings.terminal_closeout_history_enabled or self.execution_dispatcher is None):
            raise ValueError('Owner closeout archive requires explicit original OWN-A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_owner_closeout_history(identity=identity, signal=signal, reader=recovery._reader,
                dispatcher=self.execution_dispatcher.dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_asset_execution(self, identity, *, signal):
        """Archive actual original asset operation without repeating disposition or cash work."""
        from integration.owner_asset_terminal import reconcile_owner_asset_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'OWN-A14' or settings is None or not settings.terminal_asset_execution_enabled
                or self.execution_dispatcher is None):
            raise ValueError('Owner asset archive requires explicit OWN-A14 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_owner_asset_execution(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_operating_execution(self, identity, *, signal):
        """Archive original operating outcome without repeating policy, budget or allocation work."""
        from integration.owner_operating_terminal import reconcile_owner_operating_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'OWN-A15' or settings is None or not settings.terminal_operating_execution_enabled
                or self.execution_dispatcher is None):
            raise ValueError('Owner operating archive requires explicit OWN-A15 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_owner_operating_execution(identity=identity, signal=signal,
                bridge=self.execution_dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the original action journal to one selected V7 wait."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Owner original execution recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def query_payment_execution(self, identity):
        return self._dispatch_submission(identity, 'query_payment_execution')

    def query_payment_settlement(self, identity):
        return self._dispatch_submission(identity, 'query_payment_settlement')

    def record_feedback(self, identity, *, context, reading, observation):
        """Explicitly correlate actual feedback under current source/authorization guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Owner actual feedback inbox is configured')
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
            raise ValueError('No Owner actual feedback inbox is configured')
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
    config = OwnerFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != config.action_id or config.action_id not in _ACTIONS):
        raise ValueError('Formal Owner source factory requires its explicit non-offline original invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, OwnerFormalApplicationDependencies):
        raise ValueError('Actual Owner dependency factory must return OwnerFormalApplicationDependencies')
    application = None
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual Owner dependency factory changed during assembly')
        application = OwnerFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
